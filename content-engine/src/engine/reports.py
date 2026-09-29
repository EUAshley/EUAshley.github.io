"""'What is working' report.

Uses rates (saves per view, etc.) rather than raw totals, shows sample sizes,
and refuses to recommend anything from fewer than MIN_N videos.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import scoring, workflow
from .models import Idea, Offer, Publication, RevenueEvent

MIN_N = 3


def _rate(num: float, den: float) -> float | None:
    return num / den if den else None


def publication_rows(session: Session) -> list[dict]:
    revenue_by_pub = dict(session.execute(
        select(RevenueEvent.publication_id, func.sum(RevenueEvent.revenue_cents))
        .where(RevenueEvent.publication_id.is_not(None)).group_by(RevenueEvent.publication_id)
    ).all())
    rows = []
    for pub in session.scalars(select(Publication).where(Publication.status == "published")):
        snap = pub.latest_snapshot
        if snap is None:
            continue
        idea = pub.idea
        rows.append({
            "publication_id": pub.id, "idea_id": idea.id, "title": idea.title, "url": pub.url,
            "platform": pub.platform,
            "category": idea.category.name if idea.category else "(none)",
            "hook_type": pub.package.script.hook_type or "(none)",
            "score": scoring.score_idea(idea).total,
            "views": snap.views, "likes": snap.likes, "comments": snap.comments, "shares": snap.shares,
            "saves": snap.saves, "follows": snap.follows, "link_clicks": snap.link_clicks,
            "retention_pct": snap.retention_pct,
            "revenue_cents": int(revenue_by_pub.get(pub.id) or 0),
        })
    return rows


def aggregate(rows: list[dict], key: str) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[r[key]].append(r)
    out = []
    for name, rs in groups.items():
        views = sum(r["views"] for r in rs)
        out.append({
            "group": name, "n": len(rs), "views": views,
            "median_views": median(r["views"] for r in rs),
            "save_rate": _rate(sum(r["saves"] for r in rs), views),
            "share_rate": _rate(sum(r["shares"] for r in rs), views),
            "click_rate": _rate(sum(r["link_clicks"] for r in rs), views),
            "follows_per_1k": _rate(1000 * sum(r["follows"] for r in rs), views),
            "revenue_cents": sum(r["revenue_cents"] for r in rs),
        })
    return sorted(out, key=lambda g: -g["views"])


def recommendations(rows: list[dict], by_category: list[dict]) -> list[dict]:
    if not rows:
        return []
    total_views = sum(r["views"] for r in rows)
    overall_save = _rate(sum(r["saves"] for r in rows), total_views) or 0
    overall_median = median(r["views"] for r in rows)
    recs = []
    for g in by_category:
        if g["n"] < MIN_N:
            verdict, why = "needs more data", f"only {g['n']} video(s); need {MIN_N}+"
        else:
            save_ratio = (g["save_rate"] or 0) / overall_save if overall_save else 1
            view_ratio = g["median_views"] / overall_median if overall_median else 1
            if save_ratio >= 1.25 or view_ratio >= 1.25 or g["revenue_cents"] > 0:
                verdict = "make more"
            elif save_ratio < 0.6 and view_ratio < 0.6:
                verdict = "consider stopping"
            else:
                verdict = "keep testing"
            why = f"saves {save_ratio:.1f}x avg, median views {view_ratio:.1f}x avg"
            if g["revenue_cents"]:
                why += f", ${g['revenue_cents'] / 100:.2f} revenue"
        recs.append({"category": g["group"], "verdict": verdict, "why": why})
    return recs


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 5:
        return None

    def ranks(v):
        order = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx) ** 0.5
    vy = sum((b - my) ** 2 for b in ry) ** 0.5
    return cov / (vx * vy) if vx and vy else None


def offer_summary(session: Session) -> list[dict]:
    stmt = (select(Offer, func.coalesce(func.sum(RevenueEvent.clicks), 0),
                   func.coalesce(func.sum(RevenueEvent.conversions), 0),
                   func.coalesce(func.sum(RevenueEvent.revenue_cents), 0))
            .outerjoin(RevenueEvent).group_by(Offer.id).order_by(Offer.id))
    return [{"offer": o, "clicks": c, "conversions": cv, "revenue_cents": r}
            for o, c, cv, r in session.execute(stmt).all()]


def build_report(session: Session) -> dict:
    rows = publication_rows(session)
    by_category = aggregate(rows, "category")
    scored = [(r["score"], r["views"]) for r in rows if r["score"] is not None]
    status_counts = Counter(session.scalars(select(Idea.status)))
    return {
        "pipeline": [(s, status_counts.get(s, 0)) for s in workflow.ALL_STATUSES],
        "rows": sorted(rows, key=lambda r: -r["views"]),
        "by_category": by_category,
        "by_hook_type": aggregate(rows, "hook_type"),
        "by_platform": aggregate(rows, "platform"),
        "top_by_save_rate": sorted(rows, key=lambda r: -(r["saves"] / r["views"] if r["views"] else 0))[:5],
        "recommendations": recommendations(rows, by_category),
        "offers": offer_summary(session),
        "score_vs_views": _spearman([s for s, _ in scored], [v for _, v in scored]),
        "n_measured": len(rows),
        "min_n": MIN_N,
    }


def format_text(report: dict) -> str:
    def pct(x):
        return "-" if x is None else f"{100 * x:.2f}%"

    out = ["PIPELINE"] + [f"  {s:<18} {n}" for s, n in report["pipeline"] if n]
    out += ["", f"MEASURED PUBLICATIONS: {report['n_measured']}"]
    for title, groups in (("BY CATEGORY", report["by_category"]), ("BY HOOK TYPE", report["by_hook_type"]),
                          ("BY PLATFORM", report["by_platform"])):
        out += ["", title, f"  {'group':<24}{'n':>3}{'views':>9}{'median':>9}{'save%':>8}{'share%':>8}{'click%':>8}{'rev$':>9}"]
        for g in groups:
            out.append(f"  {g['group'][:23]:<24}{g['n']:>3}{g['views']:>9}{g['median_views']:>9.0f}"
                       f"{pct(g['save_rate']):>8}{pct(g['share_rate']):>8}{pct(g['click_rate']):>8}"
                       f"{g['revenue_cents'] / 100:>9.2f}")
    out += ["", "RECOMMENDATIONS (heuristic)"] + [f"  {r['category']}: {r['verdict']} ({r['why']})"
                                                  for r in report["recommendations"]]
    sv = report["score_vs_views"]
    out += ["", "SCORE vs VIEWS (Spearman): " + ("need 5+ measured videos" if sv is None else f"{sv:.2f}")]
    return "\n".join(out)
