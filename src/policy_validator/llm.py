"""OpenRouter client with a committed response cache, retries and a hard budget cap.

- ADR-001: the `openai` SDK pointed at OpenRouter.
- ADR-007: every validated response is stored in `cache/<stage>/<sha256>.json`; the key covers the
  model, prompt version and the full request, so any prompt change is a cache miss. A cache hit
  never touches the network, which is what makes CI and reviewers' re-runs free.
- ADR-026: up to 2 retries with backoff on API errors, invalid JSON or schema violations.
- ADR-027: the cost OpenRouter reports for each call is stored with the entry and summed; a run
  refuses to make a call once its spend reaches the budget.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from .config import CACHE_DIR, Settings

T = TypeVar("T")


class LLMError(RuntimeError):
    """The model could not produce a valid answer after all retries."""


class CacheMiss(LLMError):
    """Offline (no API key) and the request is not in the cache."""


class BudgetExceeded(RuntimeError):
    """The run's spend reached the configured cap; no further calls are made."""


@dataclass
class Usage:
    calls: int = 0
    cache_hits: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0  # cost of every response used in this run, cached or not
    new_cost_usd: float = 0.0  # money spent by this run: every paid attempt, failed ones too
    by_stage: dict[str, dict[str, float]] = field(default_factory=dict)

    def record(self, stage: str, meta: dict[str, Any], *, hit: bool) -> None:
        self.calls += 1
        self.cache_hits += int(hit)
        self.prompt_tokens += meta.get("prompt_tokens", 0)
        self.completion_tokens += meta.get("completion_tokens", 0)
        cost = meta.get("cost_usd", 0.0)
        self.cost_usd += cost
        s = self.by_stage.setdefault(
            stage, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}
        )
        s["calls"] += 1
        s["prompt_tokens"] += meta.get("prompt_tokens", 0)
        s["completion_tokens"] += meta.get("completion_tokens", 0)
        s["cost_usd"] += cost


class LLMClient:
    def __init__(self, settings: Settings, cache_dir: Path = CACHE_DIR, max_retries: int = 2):
        self.settings = settings
        self.cache_dir = cache_dir
        self.max_retries = max_retries
        self.usage = Usage()
        self._client = None

    @property
    def model(self) -> str:
        return self.settings.model

    def _openai(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self.settings.api_key, base_url=self.settings.base_url, timeout=60
            )
        return self._client

    def _key(self, stage: str, prompt_version: str, messages: list[dict], schema: dict) -> str:
        payload = json.dumps(
            {
                "model": self.model,
                "temperature": self.settings.temperature,
                "stage": stage,
                "prompt_version": prompt_version,
                "messages": messages,
                "schema": schema,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def complete_json(
        self,
        *,
        stage: str,
        prompt_version: str,
        system: str,
        user: str,
        schema_name: str,
        schema: dict,
        validate: Callable[[dict], T],
    ) -> T:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        key = self._key(stage, prompt_version, messages, schema)
        path = self.cache_dir / stage / f"{key}.json"

        if path.exists():
            entry = json.loads(path.read_text(encoding="utf-8"))
            self.usage.record(stage, entry["meta"], hit=True)
            return validate(entry["response"])

        if not self.settings.api_key:
            raise CacheMiss(f"{stage}: not cached and no OPENROUTER_API_KEY set")
        if self.usage.new_cost_usd >= self.settings.budget_usd:
            raise BudgetExceeded(
                f"spent ${self.usage.new_cost_usd:.4f} of ${self.settings.budget_usd:.2f}"
            )

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            if attempt:
                time.sleep(2 ** (attempt - 1))
            try:
                response = self._openai().chat.completions.create(
                    model=self.model,
                    temperature=self.settings.temperature,
                    messages=messages,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {"name": schema_name, "strict": True, "schema": schema},
                    },
                    extra_body={"usage": {"include": True}},
                )
                meta = self._meta(response)
                self.usage.new_cost_usd += meta["cost_usd"]  # paid even if validation fails
                parsed = json.loads(_strip_fences(response.choices[0].message.content or ""))
                result = validate(parsed)
            except BudgetExceeded:
                raise
            except Exception as exc:  # API error, bad JSON or schema violation -> retry
                last_error = exc
                continue
            self.usage.record(stage, meta, hit=False)
            self._store(path, stage, prompt_version, messages, parsed, meta)
            return result
        raise LLMError(f"{stage}: failed after {self.max_retries + 1} attempts: {last_error}")

    def _meta(self, response) -> dict[str, Any]:
        usage = response.usage
        extra = getattr(usage, "model_extra", None) or {}
        return {
            "model": getattr(response, "model", self.model),
            "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
            "cost_usd": float(extra.get("cost") or 0.0),
        }

    def _store(self, path, stage, prompt_version, messages, parsed, meta) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "stage": stage,
            "prompt_version": prompt_version,
            "requested_model": self.model,
            "meta": meta,
            "request": messages,
            "response": parsed,
        }
        path.write_text(json.dumps(entry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    return text.strip()
