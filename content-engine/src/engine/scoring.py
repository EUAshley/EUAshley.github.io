"""Weighted idea scoring. Weights live in config/scoring.yaml and are applied at
read time, so changing them re-ranks every idea immediately."""
from __future__ import annotations

from dataclasses import dataclass, field

from . import config
from .models import Idea


@dataclass
class ScoreResult:
    total: float | None  # 0..100 (plus category adjustment), None if unscored
    complete: bool  # every configured criterion has a value
    breakdown: dict[str, dict] = field(default_factory=dict)
    adjustment: float = 0.0


def criteria() -> dict[str, dict]:
    return config.scoring_config()["criteria"]


def compute(values: dict[str, int], category_name: str | None = None) -> ScoreResult:
    cfg = config.scoring_config()
    lo, hi = cfg["scale"]["min"], cfg["scale"]["max"]
    crit = cfg["criteria"]
    weighted = weight_sum = 0.0
    breakdown = {}
    for key, spec in crit.items():
        w = float(spec["weight"])
        v = values.get(key)
        breakdown[key] = {"label": spec.get("label", key), "weight": w, "value": v}
        if v is None:
            continue
        v = max(lo, min(hi, int(v)))
        weighted += w * (v - lo) / (hi - lo)
        weight_sum += w
    if weight_sum == 0:
        return ScoreResult(total=None, complete=False, breakdown=breakdown)
    adjustment = float((cfg.get("category_adjustments") or {}).get(category_name, 0)) if category_name else 0.0
    total = round(100 * weighted / weight_sum + adjustment, 1)
    complete = all(b["value"] is not None for b in breakdown.values())
    return ScoreResult(total=total, complete=complete, breakdown=breakdown, adjustment=adjustment)


def score_idea(idea: Idea) -> ScoreResult:
    values = {s.criterion: s.value for s in idea.scores}
    return compute(values, idea.category.name if idea.category else None)


def rank(ideas: list[Idea]) -> list[tuple[Idea, ScoreResult]]:
    scored = [(i, score_idea(i)) for i in ideas]
    return sorted(scored, key=lambda p: (p[1].total is None, -(p[1].total or 0), p[0].id))
