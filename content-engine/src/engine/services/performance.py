"""Performance snapshots (manual, CSV, or platform exports), metrics-due
reminders, and learnings."""
from __future__ import annotations

import csv
import re
import shutil
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config, workflow
from ..models import Idea, Learning, PerformanceSnapshot, Publication, utcnow

METRIC_FIELDS = ["views", "likes", "comments", "shares", "saves", "follows", "link_clicks"]
OPTIONAL_FLOAT_FIELDS = ["avg_watch_seconds", "retention_pct"]


def _number(v) -> float | None:
    """Parse '1,234', '1.2K', '3M', '45.3%', '$4.50'. Blank -> None."""
    if v is None:
        return None
    s = str(v).strip().replace(",", "").replace("$", "").rstrip("%").strip()
    if not s or s in {"-", "--"}:
        return None
    mult = {"k": 1e3, "m": 1e6, "b": 1e9}.get(s[-1].lower(), 1)
    if mult != 1:
        s = s[:-1]
    return float(s) * mult


def _duration_seconds(v) -> float | None:
    """Parse '0:00:11', '0:11', '11s', '11.2'."""
    if v is None or str(v).strip() == "":
        return None
    s = str(v).strip().lower().rstrip("s")
    if ":" in s:
        total = 0.0
        for part in s.split(":"):
            total = total * 60 + float(part)
        return total
    return _number(s)


def _int(v) -> int:
    n = _number(v)
    return int(round(n)) if n is not None else 0


def record_snapshot(session: Session, pub: Publication, *, captured_at: datetime | None = None,
                    source: str = "manual", **metrics) -> PerformanceSnapshot:
    if pub.status != "published":
        raise workflow.WorkflowError(f"Publication #{pub.id} is not published yet")
    snap = PerformanceSnapshot(
        publication=pub, source=source,
        **({"captured_at": captured_at} if captured_at else {}),
        **{k: _int(metrics.get(k)) for k in METRIC_FIELDS},
        avg_watch_seconds=_duration_seconds(metrics.get("avg_watch_seconds")),
        retention_pct=_number(metrics.get("retention_pct")),
    )
    session.add(snap)
    session.flush()
    if pub.idea.status == workflow.PUBLISHED:
        workflow.transition(session, pub.idea, workflow.MEASURED, note="first performance data")
    return snap


# --- Importing exports -----------------------------------------------------------

@dataclass
class ImportResult:
    imported: int = 0
    unmatched: int = 0
    errors: list[str] = field(default_factory=list)


def _normalize_url(url: str) -> str:
    url = url.strip().lower().split("#")[0]
    url = re.sub(r"^https?://(www\.|m\.)?", "", url)
    if "youtube.com/watch" not in url:
        url = url.split("?")[0]
    return url.rstrip("/")


def video_id(url: str) -> str | None:
    for pattern in config.metrics_import_config().get("video_id_patterns", []):
        m = re.search(pattern, url or "")
        if m:
            return m.group(1)
    return None


def _publication_index(session: Session) -> tuple[dict, dict]:
    by_url, by_vid = {}, {}
    for pub in session.scalars(select(Publication).where(Publication.status == "published")):
        if pub.url:
            by_url[_normalize_url(pub.url)] = pub
            vid = video_id(pub.url)
            if vid:
                by_vid[vid] = pub
    return by_url, by_vid


def _canonical_row(raw: dict) -> dict:
    """Map an export row's headers onto our field names using config aliases."""
    row = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
    out = {}
    for field_name, aliases in config.metrics_import_config()["columns"].items():
        for alias in aliases:
            if row.get(alias.lower()):
                out[field_name] = row[alias.lower()]
                break
    return out


def _parse_when(v: str) -> datetime | None:
    if not v:
        return None
    for fmt in (None, "%m/%d/%Y", "%b %d, %Y", "%d/%m/%Y"):
        try:
            return datetime.fromisoformat(v) if fmt is None else datetime.strptime(v, fmt)
        except ValueError:
            continue
    raise ValueError(f"unrecognized date '{v}'")


def import_csv(session: Session, path: str | Path) -> ImportResult:
    """Import one export. Rows are matched to publications by publication_id,
    then URL, then video ID extracted from the stored URL. Rows that match no
    published video (totals, other videos) are counted as unmatched."""
    result = ImportResult()
    by_url, by_vid = _publication_index(session)
    with open(path, newline="", encoding="utf-8-sig") as f:
        for n, raw in enumerate(csv.DictReader(f), start=2):
            row = _canonical_row(raw)
            pub = None
            if row.get("publication_id", "").isdigit():
                pub = session.get(Publication, int(row["publication_id"]))
            if pub is None and row.get("url"):
                pub = by_url.get(_normalize_url(row["url"])) or by_vid.get(video_id(row["url"]) or "")
            if pub is None and row.get("video_id"):
                pub = by_vid.get(row["video_id"])
            if pub is None:
                result.unmatched += 1
                continue
            try:
                metrics = {k: row.get(k) for k in METRIC_FIELDS + OPTIONAL_FLOAT_FIELDS}
                record_snapshot(session, pub, captured_at=_parse_when(row.get("captured_at", "")),
                                source="csv", **metrics)
                result.imported += 1
            except (ValueError, workflow.WorkflowError) as e:
                result.errors.append(f"{Path(path).name} line {n}: {e}")
    return result


def inbox_dir() -> Path:
    return config.PROJECT_ROOT / "data" / "inbox"


def import_inbox(session: Session, inbox: Path | None = None) -> dict[str, ImportResult]:
    """Import every CSV in data/inbox/, then move each into data/inbox/processed/."""
    inbox = inbox or inbox_dir()
    processed = inbox / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    results = {}
    for path in sorted(inbox.glob("*.csv")):
        results[path.name] = import_csv(session, path)
        stamp = utcnow().strftime("%Y%m%d-%H%M%S")
        shutil.move(str(path), processed / f"{stamp}-{path.name}")
    return results


# --- Metrics due -----------------------------------------------------------------

def metrics_due(session: Session, today: date | None = None) -> list[dict]:
    """Published videos whose latest passed checkpoint (day 1/7/30 by default)
    has no snapshot taken on or after it."""
    today = today or date.today()
    days = sorted(config.metrics_import_config().get("snapshot_days", [1, 7, 30]))
    due = []
    for pub in session.scalars(select(Publication).where(Publication.status == "published")):
        if not pub.published_at:
            continue
        age = (today - pub.published_at).days
        passed = [d for d in days if d <= age]
        if not passed:
            continue
        checkpoint = passed[-1]
        needed_from = pub.published_at + timedelta(days=checkpoint)
        if not any(s.captured_at.date() >= needed_from for s in pub.snapshots):
            due.append({"publication": pub, "checkpoint": checkpoint, "age": age})
    return sorted(due, key=lambda d: -d["age"])


def add_learning(session: Session, text: str, *, idea: Idea | None = None, publication_id: int | None = None,
                 category_id: int | None = None, tags: str = "") -> Learning:
    learning = Learning(text=text, idea=idea, publication_id=publication_id,
                        category_id=category_id if category_id else (idea.category_id if idea else None), tags=tags)
    session.add(learning)
    session.flush()
    return learning
