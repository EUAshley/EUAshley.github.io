"""Episode spec: loading and structural validation.

An episode is one YAML file that holds everything the pipeline needs:
sources -> facts (the fact ledger) -> scenes (narration + visual + fact refs).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SCENE_TYPES = {
    "hook", "counter", "bars", "donut", "grid", "line", "quote", "compare", "statement", "end",
}
CONFIDENCE = {"official", "reported", "estimate", "calc"}


class SpecError(ValueError):
    pass


@dataclass
class Source:
    id: str
    title: str
    publisher: str
    url: str
    accessed: str
    primary: bool = False
    note: str = ""


@dataclass
class Fact:
    id: str
    value: float
    claim: str
    unit: str = ""
    period: str = ""
    sources: list[str] = field(default_factory=list)
    confidence: str = "official"
    calc: str = ""
    tolerance: float = 0.01  # relative tolerance for matching numbers in the script
    conflicts: str = ""


@dataclass
class Scene:
    id: str
    type: str
    say: str
    facts: list[str] = field(default_factory=list)
    visual: dict[str, Any] = field(default_factory=dict)
    source_note: str = ""
    allow_numbers: list[str] = field(default_factory=list)
    hold: float = 0.25  # seconds of silence after narration


@dataclass
class Episode:
    id: str
    title: str
    hook_question: str
    sources: dict[str, Source]
    facts: dict[str, Fact]
    scenes: list[Scene]
    voice: dict[str, Any]
    style: dict[str, Any]
    publish: dict[str, Any]
    path: Path

    @property
    def narration(self) -> str:
        return " ".join(s.say for s in self.scenes)


def _req(d: dict, key: str, where: str):
    if key not in d or d[key] in (None, ""):
        raise SpecError(f"{where}: missing required field '{key}'")
    return d[key]


def load_episode(path: str | Path) -> Episode:
    path = Path(path)
    raw = yaml.safe_load(path.read_text())
    where = path.name

    sources = {}
    for sid, s in (raw.get("sources") or {}).items():
        sources[sid] = Source(
            id=sid,
            title=_req(s, "title", f"{where} source {sid}"),
            publisher=_req(s, "publisher", f"{where} source {sid}"),
            url=_req(s, "url", f"{where} source {sid}"),
            accessed=str(_req(s, "accessed", f"{where} source {sid}")),
            primary=bool(s.get("primary", False)),
            note=s.get("note", ""),
        )

    facts = {}
    for fid, f in (raw.get("facts") or {}).items():
        fact = Fact(
            id=fid,
            value=float(_req(f, "value", f"{where} fact {fid}")),
            claim=_req(f, "claim", f"{where} fact {fid}"),
            unit=f.get("unit", ""),
            period=f.get("period", ""),
            sources=list(f.get("sources") or []),
            confidence=f.get("confidence", "calc" if f.get("calc") else "official"),
            calc=f.get("calc", ""),
            tolerance=float(f.get("tolerance", 0.01)),
            conflicts=f.get("conflicts", ""),
        )
        if fact.confidence not in CONFIDENCE:
            raise SpecError(f"{where} fact {fid}: confidence must be one of {sorted(CONFIDENCE)}")
        facts[fid] = fact

    scenes = []
    for i, s in enumerate(raw.get("scenes") or []):
        sid = s.get("id", f"scene{i + 1}")
        stype = _req(s, "type", f"{where} scene {sid}")
        if stype not in SCENE_TYPES:
            raise SpecError(f"{where} scene {sid}: unknown type '{stype}' (use one of {sorted(SCENE_TYPES)})")
        scenes.append(Scene(
            id=sid,
            type=stype,
            say=_req(s, "say", f"{where} scene {sid}").strip(),
            facts=list(s.get("facts") or []),
            visual=dict(s.get("visual") or {}),
            source_note=s.get("source_note", ""),
            allow_numbers=[str(n) for n in (s.get("allow_numbers") or [])],
            hold=float(s.get("hold", 0.25)),
        ))
    if not scenes:
        raise SpecError(f"{where}: episode has no scenes")

    return Episode(
        id=_req(raw, "id", where),
        title=_req(raw, "title", where),
        hook_question=raw.get("hook_question", raw["title"]),
        sources=sources,
        facts=facts,
        scenes=scenes,
        voice=dict(raw.get("voice") or {}),
        style=dict(raw.get("style") or {}),
        publish=dict(raw.get("publish") or {}),
        path=path,
    )
