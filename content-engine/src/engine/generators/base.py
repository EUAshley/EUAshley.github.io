"""Generator interface. A generator turns an Idea (+ brand profile) into a
ScriptDraft. New generators (LLM, different formats) just implement `generate`."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..models import Idea


@dataclass
class ScriptDraft:
    sections: list[dict]  # [{key, label, start, end, voiceover, on_screen_text, visual}]
    cta: str
    hook_type: str = ""
    generator: str = "template"
    notes: list[str] = field(default_factory=list)

    @property
    def target_seconds(self) -> int:
        return max((s["end"] for s in self.sections), default=0)


class ScriptGenerator(Protocol):
    name: str

    def available(self) -> bool: ...

    def generate(self, idea: Idea, brand: dict) -> ScriptDraft: ...


def retime(sections: list[dict]) -> list[dict]:
    """Recompute start/end from each section's `seconds`, keeping order."""
    t = 0
    for s in sections:
        secs = int(s.get("seconds") or max(1, s.get("end", 0) - s.get("start", 0)))
        s["start"], s["end"], s["seconds"] = t, t + secs, secs
        t += secs
    return sections
