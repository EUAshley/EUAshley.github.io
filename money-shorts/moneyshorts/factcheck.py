"""Fact-check gate. A video cannot render unless this passes.

Rules (errors block the build, warnings are reported):
  E1  every number spoken in the script must match a fact the scene cites
  E2  every cited fact must exist, and every fact must cite an existing source
  E3  calculated facts are recomputed from their inputs and must match
  E4  'estimate' facts must be spoken with a hedge word ("about", "roughly"...)
  E5  visuals must pull numbers from the ledger ("@fact_id"), not hard-code them
  W1  'official' facts should have a primary source or two independent sources
  W2  'reported' facts should be hedged ("reportedly", "about"...)
  W3  facts with recorded source conflicts are listed for review
  W4  facts that no scene uses
"""
from __future__ import annotations

import ast
import operator
import re
from dataclasses import dataclass, field
from typing import Any

from .numbers import bare_digits, find_numbers, template_refs
from .spec import Episode

HEDGES = re.compile(
    r"\b(about|around|roughly|nearly|almost|reportedly|estimated|estimate[sd]?|approximately|"
    r"more than|over|less than|under|up to|some|close to|at least|reported|report)\b|~",
    re.IGNORECASE,
)

VISUAL_NUMERIC_KEYS = {"value", "values", "points", "a", "b", "segments", "items"}


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    claims: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


# ------------------------------------------------------------ safe calc

_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg,
}


def safe_eval(expr: str, names: dict[str, float]) -> float:
    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in names:
                raise KeyError(node.id)
            return names[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        raise ValueError(f"unsupported expression element: {ast.dump(node)}")
    return float(ev(ast.parse(expr, mode="eval")))


def close(a: float, b: float, rel: float) -> bool:
    if b == 0:
        return abs(a) < 1e-9
    return abs(a - b) / abs(b) <= rel


# ------------------------------------------------------------ visuals

def resolve_visual(obj: Any, ep: Episode) -> Any:
    """Replace "@fact_id" strings in a visual config with ledger values."""
    if isinstance(obj, str) and obj.startswith("@"):
        return ep.facts[obj[1:]].value
    if isinstance(obj, list):
        return [resolve_visual(x, ep) for x in obj]
    if isinstance(obj, dict):
        return {k: resolve_visual(v, ep) for k, v in obj.items()}
    return obj


def _visual_literals(obj: Any, key: str = "", path: str = "") -> list[str]:
    out = []
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)) and key in VISUAL_NUMERIC_KEYS:
        out.append(f"{path}={obj}")
    elif isinstance(obj, list):
        for i, x in enumerate(obj):
            out += _visual_literals(x, key, f"{path}[{i}]")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            out += _visual_literals(v, k if k in VISUAL_NUMERIC_KEYS else key, f"{path}.{k}" if path else k)
    return out


CONFIG_KEYS = {"format", "legend_format", "color", "orient", "icon"}


def _visual_strings(obj: Any) -> list[str]:
    """On-screen strings in a visual config (style/config keys excluded)."""
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, list):
        return [r for x in obj for r in _visual_strings(x)]
    if isinstance(obj, dict):
        return [r for k, v in obj.items() if k not in CONFIG_KEYS for r in _visual_strings(v)]
    return []


def _visual_refs(obj: Any) -> list[str]:
    if isinstance(obj, str) and obj.startswith("@"):
        return [obj[1:]]
    if isinstance(obj, str):
        return template_refs(obj)
    if isinstance(obj, list):
        return [r for x in obj for r in _visual_refs(x)]
    if isinstance(obj, dict):
        return [r for v in obj.values() for r in _visual_refs(v)]
    return []


# ------------------------------------------------------------ main

def check(ep: Episode) -> Report:
    rep = Report()
    facts, sources = ep.facts, ep.sources

    # E2 / W1: ledger integrity
    for f in facts.values():
        for sid in f.sources:
            if sid not in sources:
                rep.errors.append(f"E2 fact '{f.id}' cites unknown source '{sid}'")
        if f.confidence != "calc" and not f.sources:
            rep.errors.append(f"E2 fact '{f.id}' has no source")
        if f.confidence == "official":
            prim = [s for s in f.sources if s in sources and sources[s].primary]
            if not prim and len(set(f.sources)) < 2:
                rep.warnings.append(f"W1 official fact '{f.id}' has no primary source and <2 sources")
        if f.conflicts:
            rep.warnings.append(f"W3 fact '{f.id}' has a recorded source conflict: {f.conflicts}")

    # E3: recompute calculated facts
    values = {k: f.value for k, f in facts.items()}
    for f in facts.values():
        if f.calc:
            try:
                got = safe_eval(f.calc, values)
            except Exception as e:  # noqa: BLE001
                rep.errors.append(f"E3 fact '{f.id}': cannot evaluate '{f.calc}': {e}")
                continue
            if not close(f.value, got, f.tolerance):
                rep.errors.append(f"E3 fact '{f.id}': stated {f.value:g} but {f.calc} = {got:g}")

    used: set[str] = set()
    for sc in ep.scenes:
        for fid in sc.facts:
            if fid not in facts:
                rep.errors.append(f"E2 scene '{sc.id}' cites unknown fact '{fid}'")
        cited = [facts[f] for f in sc.facts if f in facts]
        used.update(f.id for f in cited)

        # E1: every spoken number is backed by a cited fact
        for tok in find_numbers(sc.say):
            hit = next((f for f in cited for c in tok.candidates() if close(c, f.value, f.tolerance)), None)
            if hit:
                rep.claims.append({"scene": sc.id, "text": tok.text, "fact": hit.id})
                continue
            if tok.text in sc.allow_numbers or tok.text.lstrip("$") in sc.allow_numbers:
                rep.claims.append({"scene": sc.id, "text": tok.text, "fact": "(allowed: illustrative)"})
                continue
            other = next((f for f in facts.values() for c in tok.candidates() if close(c, f.value, f.tolerance)), None)
            if other:
                rep.errors.append(f"E1 scene '{sc.id}': '{tok.text}' matches fact '{other.id}' but the scene does not cite it")
            else:
                rep.errors.append(f"E1 scene '{sc.id}': '{tok.text}' is not backed by any fact")

        # E4 / W2: hedging
        hedged = bool(HEDGES.search(sc.say))
        for f in cited:
            if f.confidence == "estimate" and not hedged:
                rep.errors.append(f"E4 scene '{sc.id}' states estimate '{f.id}' without a hedge word")
            if f.confidence == "reported" and not hedged:
                rep.warnings.append(f"W2 scene '{sc.id}' states reported fact '{f.id}' without a hedge word")

        # E5: visuals use the ledger
        for lit in _visual_literals(sc.visual):
            rep.errors.append(f"E5 scene '{sc.id}' visual hard-codes {lit}; reference a fact with '@id'")
        allowed = {n.lstrip("$") for n in sc.allow_numbers}
        # source notes are citations (dates, report names) and are exempt
        for txt in _visual_strings(sc.visual):
            if txt.startswith("@") or txt.startswith("#"):
                continue
            for num in bare_digits(txt):
                if num.lstrip("$").rstrip("%") not in allowed and num.lstrip("$") not in allowed:
                    rep.errors.append(f"E5 scene '{sc.id}' on-screen text hard-codes '{num}' in \"{txt}\"; "
                                      "use '{fact_id:fmt}' or allow_numbers")
        for ref in _visual_refs(sc.visual):
            if ref not in facts:
                rep.errors.append(f"E5 scene '{sc.id}' visual references unknown fact '{ref}'")
            else:
                used.add(ref)
                if ref not in sc.facts:
                    sc.facts.append(ref)

    # facts used only by platform variants (see platforms.py) count as used
    for var in (ep.variants or {}).values():
        for raw in (var or {}).get("add_scenes") or []:
            used.update(raw.get("facts") or [])
            used.update(r for r in _visual_refs(raw.get("visual") or {}) if r in facts)

    # calc inputs count as used
    for f in facts.values():
        if f.calc and f.id in used:
            used.update(n.id for n in ast.walk(ast.parse(f.calc, mode="eval")) if isinstance(n, ast.Name))
    for f in facts.values():
        if f.id not in used:
            rep.warnings.append(f"W4 fact '{f.id}' is never used")
    return rep


def report_markdown(ep: Episode, rep: Report) -> str:
    lines = [f"# Fact-check report: {ep.title}", "",
             f"**Status:** {'PASS' if rep.ok else 'FAIL'} "
             f"({len(rep.errors)} errors, {len(rep.warnings)} warnings)", ""]
    if rep.errors:
        lines += ["## Errors", ""] + [f"- {e}" for e in rep.errors] + [""]
    if rep.warnings:
        lines += ["## Warnings", ""] + [f"- {w}" for w in rep.warnings] + [""]
    lines += ["## Spoken claims", "", "| Scene | Claim | Fact | Value | Confidence | Sources |",
              "|---|---|---|---|---|---|"]
    for c in rep.claims:
        f = ep.facts.get(c["fact"])
        if f:
            src = ", ".join(f.sources) or f"calc: `{f.calc}`"
            lines.append(f"| {c['scene']} | {c['text']} | {f.id} | {f.value:,.6g} | {f.confidence} | {src} |")
        else:
            lines.append(f"| {c['scene']} | {c['text']} | {c['fact']} | | | |")
    lines += ["", "## Fact ledger", ""]
    for f in ep.facts.values():
        lines.append(f"- **{f.id}** = {f.value:,.6g} {f.unit} — {f.claim}"
                     + (f" ({f.period})" if f.period else "")
                     + f" · _{f.confidence}_"
                     + (f" · calc `{f.calc}`" if f.calc else "")
                     + (f" · sources: {', '.join(f.sources)}" if f.sources else ""))
        if f.conflicts:
            lines.append(f"  - conflict: {f.conflicts}")
    lines += ["", "## Sources", ""]
    for s in ep.sources.values():
        lines.append(f"- **{s.id}** {'(primary) ' if s.primary else ''}{s.publisher}, "
                     f"\"{s.title}\" — {s.url} (accessed {s.accessed})" + (f" — {s.note}" if s.note else ""))
    return "\n".join(lines) + "\n"
