"""LLM client behaviour with a fake transport — no network, no key."""

import json
from types import SimpleNamespace

import pytest

from policy_validator.config import Settings
from policy_validator.llm import BudgetExceeded, CacheMiss, LLMClient, LLMError


def settings(api_key="test", budget=1.0):
    return Settings(api_key, "http://fake", "test/model", 0.0, 0.5, budget)


class FakeOpenAI:
    def __init__(self, contents, cost=0.01):
        self.contents = list(contents)
        self.cost = cost
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls += 1
        usage = SimpleNamespace(
            prompt_tokens=10, completion_tokens=5, model_extra={"cost": self.cost}
        )
        message = SimpleNamespace(content=self.contents.pop(0))
        return SimpleNamespace(
            model="test/model", usage=usage, choices=[SimpleNamespace(message=message)]
        )


def call(client, user="hello", validate=lambda d: d["answer"]):
    return client.complete_json(
        stage="test",
        prompt_version="v1",
        system="sys",
        user=user,
        schema_name="s",
        schema={"type": "object"},
        validate=validate,
    )


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("policy_validator.llm.time.sleep", lambda s: None)


def test_cache_hit_never_calls_the_network(tmp_path):
    client = LLMClient(settings(), cache_dir=tmp_path)
    client._client = FakeOpenAI([json.dumps({"answer": 42})])
    assert call(client) == 42
    again = LLMClient(settings(api_key=None), cache_dir=tmp_path)  # offline
    assert call(again) == 42
    assert again.usage.cache_hits == 1 and again.usage.new_cost_usd == 0
    assert again.usage.cost_usd == pytest.approx(0.01)


def test_offline_cache_miss_raises(tmp_path):
    with pytest.raises(CacheMiss):
        call(LLMClient(settings(api_key=None), cache_dir=tmp_path))


def test_retries_on_invalid_json_then_succeeds(tmp_path):
    client = LLMClient(settings(), cache_dir=tmp_path)
    client._client = FakeOpenAI(["not json", '```json\n{"answer": 1}\n```'])
    assert call(client) == 1
    assert client._client.calls == 2
    assert client.usage.new_cost_usd == pytest.approx(0.02)  # failed attempt is paid too


def test_gives_up_after_retries_and_caches_nothing(tmp_path):
    client = LLMClient(settings(), cache_dir=tmp_path)
    client._client = FakeOpenAI(["{}"] * 3)
    with pytest.raises(LLMError):
        call(client)  # validate raises KeyError on every attempt
    assert client._client.calls == 3
    assert not list(tmp_path.rglob("*.json"))


def test_budget_cap_blocks_further_calls(tmp_path):
    client = LLMClient(settings(budget=0.015), cache_dir=tmp_path)
    client._client = FakeOpenAI([json.dumps({"answer": 1}), json.dumps({"answer": 2})])
    call(client, user="a")
    call(client, user="b")  # 0.01 spent < 0.015: allowed
    with pytest.raises(BudgetExceeded):
        call(client, user="c")


def test_prompt_change_is_a_cache_miss(tmp_path):
    client = LLMClient(settings(), cache_dir=tmp_path)
    client._client = FakeOpenAI([json.dumps({"answer": 1}), json.dumps({"answer": 2})])
    assert call(client, user="a") == 1
    assert call(client, user="a changed") == 2
