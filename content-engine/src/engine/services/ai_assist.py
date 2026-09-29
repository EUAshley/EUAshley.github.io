"""AI-assisted research and scoring (Phase 2).

- suggest_ideas: researches new video ideas for a category, informed by what
  has performed, what hasn't, recorded learnings, and every existing idea (to
  avoid duplicates). Optionally searches the web to check steps against the
  current OS/app versions.
- suggest_scores: proposes 1-5 scores with rationales for an idea.

AI output always lands as a suggestion: new ideas start in `idea` status with
source "ai:…", and AI scores are marked scored_by="ai". They are ranked like
any other idea, but an idea only becomes `scored` once a human saves scores,
and only a human can select it for production.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import ai, config, reports, scoring
from ..models import Idea, Learning
from . import ideas as idea_service


def _score_schema() -> dict:
    crit = scoring.criteria()
    return {
        "type": "object",
        "properties": {
            key: {
                "type": "object",
                "properties": {"value": {"type": "integer", "enum": [1, 2, 3, 4, 5]}, "rationale": {"type": "string"}},
                "required": ["value", "rationale"],
                "additionalProperties": False,
            }
            for key in crit
        },
        "required": list(crit),
        "additionalProperties": False,
    }


def _idea_schema(categories: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "ideas": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "category": {"type": "string", "enum": categories},
                        "problem_solved": {"type": "string"},
                        "benefit": {"type": "string"},
                        "target_audience": {"type": "string"},
                        "hook": {"type": "string"},
                        "solution_steps": {"type": "array", "items": {"type": "string"}},
                        "tools": {"type": "array", "items": {"type": "string"}},
                        "research_notes": {"type": "string"},
                        "scores": _score_schema(),
                    },
                    "required": ["title", "category", "problem_solved", "benefit", "target_audience", "hook",
                                 "solution_steps", "tools", "research_notes", "scores"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["ideas"],
        "additionalProperties": False,
    }


def _criteria_text() -> str:
    return "\n".join(f"- {k} (weight {c['weight']}): {c['question']}" for k, c in scoring.criteria().items())


def _performance_context(session: Session) -> str:
    rows = reports.publication_rows(session)
    if not rows:
        return "No published videos have performance data yet."

    def line(r):
        rate = f"{100 * r['saves'] / r['views']:.1f}% saves" if r["views"] else "no views"
        return f"- {r['title']} [{r['category']}, hook {r['hook_type']}]: {r['views']:,} views, {rate}"

    by_views = sorted(rows, key=lambda r: -r["views"])
    parts = ["Best performing:", *map(line, by_views[:5])]
    if len(by_views) > 5:
        parts += ["Worst performing:", *map(line, by_views[-5:])]
    return "\n".join(parts)


SYSTEM = """You research ideas for short vertical videos (TikTok, Reels, Shorts) that show people \
one technology trick with an immediate everyday benefit. You favor tricks that are genuinely \
useful, can be demonstrated on screen in under 40 seconds, and that many people don't know. \
You never invent features: every step must work on the current version of the OS or app, and \
anything you are unsure about goes in research_notes as something to verify, with source URLs \
when you have them. Scores are honest 1-5 ratings, not flattery; use the full range."""


def suggest_ideas(session: Session, *, category: str | None = None, count: int = 5,
                  web_search: bool = True, brand_slug: str | None = None) -> list[Idea]:
    brand = idea_service.ensure_brand(session, brand_slug)
    cfg = config.brand_config(brand.slug)
    categories = [c.name for c in brand.categories]
    existing = [i.title for i in session.scalars(select(Idea).where(Idea.brand_id == brand.id))]
    learnings = [l.text for l in session.scalars(select(Learning).order_by(Learning.id.desc()).limit(20))]
    prompt = f"""Brand: {cfg.get('name')}
{cfg.get('description', '').strip()}
Voice: {cfg.get('voice', '').strip()}

Suggest {count} new video ideas{f' in the category "{category}"' if category else ''}.
Allowed categories: {', '.join(categories)}

Scoring criteria (rate each 1-5):
{_criteria_text()}

What has performed so far:
{_performance_context(session)}

Learnings recorded so far:
{chr(10).join('- ' + l for l in learnings) or '(none yet)'}

Existing ideas; do not repeat these or near-duplicates:
{chr(10).join('- ' + t for t in existing) or '(none yet)'}

For each idea give concrete, current, step-by-step solution_steps (one action per step, the \
exact menu and action names), the tools/apps involved, and a hook that states the benefit in \
the first sentence."""
    data, model = ai.structured(SYSTEM, prompt, _idea_schema(categories), web_search=web_search)
    created = []
    for item in data["ideas"][:count]:
        scores = item.pop("scores")
        idea = idea_service.create_idea(
            session, brand_slug=brand.slug, category=item.pop("category"),
            solution_steps="\n".join(item.pop("solution_steps")), tools=", ".join(item.pop("tools")),
            source=f"ai:{model}" + (" + web search" if web_search else ""), **item,
        )
        _apply_ai_scores(session, idea, scores)
        created.append(idea)
    return created


def suggest_scores(session: Session, idea: Idea) -> scoring.ScoreResult:
    """Fill in AI scores for criteria a human hasn't scored yet."""
    prompt = f"""Score this video idea for the brand "{config.brand_config(idea.brand.slug).get('name')}".

Criteria:
{_criteria_text()}

Idea: {idea.title}
Category: {idea.category.name if idea.category else ''}
Problem solved: {idea.problem_solved}
Benefit: {idea.benefit}
Audience: {idea.target_audience}
Hook: {idea.hook}
Tools: {idea.tools}
Steps:
{chr(10).join(f'{n}. {s}' for n, s in enumerate(idea.steps, 1)) or '(none given)'}

What has performed so far:
{_performance_context(session)}"""
    data, _ = ai.structured(SYSTEM, prompt, _score_schema())
    return _apply_ai_scores(session, idea, data)


def _apply_ai_scores(session: Session, idea: Idea, scores: dict) -> scoring.ScoreResult:
    human = {s.criterion for s in idea.scores if s.scored_by == "human"}
    todo = {k: v for k, v in scores.items() if k not in human}
    return idea_service.set_scores(
        session, idea, {k: v["value"] for k, v in todo.items()}, scored_by="ai",
        rationales={k: v["rationale"] for k, v in todo.items()},
    )
