"""Rule registry parsed from the policy markdown (ADR-029).

A rule starts with a paragraph `**ID — Title.** text` and continues through the following
paragraphs (bullets, italic notes, follow-up prose) until the next rule, a heading, a table, or a
bold-led paragraph that is not a rule (e.g. "**Note on identification.**"). The rule text is what
exceptions cite as evidence; the rule *logic* is code in `engine.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from .config import POLICY_DIR

_RULE_HEADER = re.compile(
    r"^\*\*(?P<id>[A-Z]+-\d{2}) — (?P<title>[^*]+?)\.\*\*\s*(?P<rest>.*)", re.S
)


@dataclass(frozen=True)
class Rule:
    rule_id: str
    title: str
    policy_doc: str
    text: str

    @property
    def summary(self) -> str:
        """First sentence of the rule text — a short citation for reports."""
        first = re.split(r"(?<=[.!?])\s+", self.text, maxsplit=1)[0]
        return _strip_markdown(first)

    @property
    def evidence(self) -> str:
        return _strip_markdown(self.text)


def _strip_markdown(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", text)
    text = text.replace("`", "")
    return re.sub(r"[ \t]*\n[ \t]*", " ", text).strip()


def _paragraphs(markdown: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", markdown) if p.strip()]


def _ends_rule(paragraph: str) -> bool:
    return (
        paragraph.startswith("#")
        or paragraph.startswith("|")
        or bool(_RULE_HEADER.match(paragraph))
        or (paragraph.startswith("**") and not paragraph.startswith("***"))
    )


def parse_policy_doc(path: Path) -> list[Rule]:
    rules: list[Rule] = []
    paragraphs = _paragraphs(path.read_text(encoding="utf-8"))
    i = 0
    while i < len(paragraphs):
        match = _RULE_HEADER.match(paragraphs[i])
        if not match:
            i += 1
            continue
        body = [match["rest"]]
        i += 1
        while i < len(paragraphs) and not _ends_rule(paragraphs[i]):
            body.append(paragraphs[i])
            i += 1
        rules.append(
            Rule(
                rule_id=match["id"],
                title=match["title"].strip(),
                policy_doc=path.name,
                text="\n\n".join(body).strip(),
            )
        )
    return rules


@cache
def load_registry(policy_dir: Path = POLICY_DIR) -> dict[str, Rule]:
    registry: dict[str, Rule] = {}
    for path in sorted(policy_dir.glob("*.md")):
        for rule in parse_policy_doc(path):
            if rule.rule_id in registry:
                raise ValueError(f"{rule.rule_id} defined twice ({path.name})")
            registry[rule.rule_id] = rule
    return registry
