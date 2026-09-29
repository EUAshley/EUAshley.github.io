"""Performance snapshots (manual or CSV), and learnings."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import workflow
from ..models import Idea, Learning, PerformanceSnapshot, Publication

METRIC_FIELDS = ["views", "likes", "comments", "shares", "saves", "follows", "link_clicks"]
OPTIONAL_FLOAT_FIELDS = ["avg_watch_seconds", "retention_pct"]


def _int(v) -> int:
    if v in (None, ""):
        return 0
    return int(float(str(v).replace(",", "")))


def _float(v) -> float | None:
    if v in (None, ""):
        return None
    return float(str(v).replace(",", "").rstrip("%"))


def record_snapshot(session: Session, pub: Publication, *, captured_at: datetime | None = None,
                    source: str = "manual", **metrics) -> PerformanceSnapshot:
    if pub.status != "published":
        raise workflow.WorkflowError(f"Publication #{pub.id} is not published yet")
    snap = PerformanceSnapshot(
        publication=pub, source=source,
        **({"captured_at": captured_at} if captured_at else {}),
        **{k: _int(metrics.get(k)) for k in METRIC_FIELDS},
        **{k: _float(metrics.get(k)) for k in OPTIONAL_FLOAT_FIELDS},
    )
    session.add(snap)
    session.flush()
    if pub.idea.status == workflow.PUBLISHED:
        workflow.transition(session, pub.idea, workflow.MEASURED, note="first performance data")
    return snap


def import_csv(session: Session, path: str | Path) -> tuple[int, list[str]]:
    """Import snapshots. Needs a `publication_id` or `url` column, plus any of
    METRIC_FIELDS / OPTIONAL_FLOAT_FIELDS and optional `captured_at` (ISO date)."""
    imported, errors = 0, []
    with open(path, newline="") as f:
        for n, row in enumerate(csv.DictReader(f), start=2):
            row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
            pub = None
            if row.get("publication_id"):
                pub = session.get(Publication, int(row["publication_id"]))
            elif row.get("url"):
                pub = session.scalar(select(Publication).where(Publication.url == row["url"]))
            if pub is None:
                errors.append(f"line {n}: no matching publication")
                continue
            try:
                captured = datetime.fromisoformat(row["captured_at"]) if row.get("captured_at") else None
                record_snapshot(session, pub, captured_at=captured, source="csv", **row)
                imported += 1
            except (ValueError, workflow.WorkflowError) as e:
                errors.append(f"line {n}: {e}")
    return imported, errors


def add_learning(session: Session, text: str, *, idea: Idea | None = None, publication_id: int | None = None,
                 category_id: int | None = None, tags: str = "") -> Learning:
    learning = Learning(text=text, idea=idea, publication_id=publication_id,
                        category_id=category_id if category_id else (idea.category_id if idea else None), tags=tags)
    session.add(learning)
    session.flush()
    return learning
