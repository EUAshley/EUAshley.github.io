from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config, scoring, workflow
from ..models import Brand, Category, Idea, IdeaScore, utcnow

IDEA_FIELDS = [
    "title", "problem_solved", "benefit", "target_audience", "hook",
    "solution_steps", "tools", "source", "research_notes", "notes",
]


def ensure_brand(session: Session, slug: str | None = None) -> Brand:
    """Get the brand row, creating it and its categories from config if needed."""
    slug = slug or config.default_brand_slug()
    cfg = config.brand_config(slug)
    brand = session.scalar(select(Brand).where(Brand.slug == slug))
    if brand is None:
        brand = Brand(slug=slug, name=cfg.get("name", slug))
        session.add(brand)
        session.flush()
    existing = {c.name for c in brand.categories}
    for name in cfg.get("categories", []):
        if name not in existing:
            session.add(Category(brand=brand, name=name))
    session.flush()
    return brand


def get_or_create_category(session: Session, brand: Brand, name: str | None) -> Category | None:
    if not name:
        return None
    cat = session.scalar(select(Category).where(Category.brand_id == brand.id, Category.name == name))
    if cat is None:
        cat = Category(brand=brand, name=name)
        session.add(cat)
        session.flush()
    return cat


def create_idea(session: Session, *, category: str | None = None, brand_slug: str | None = None,
                scores: dict[str, int] | None = None, **fields) -> Idea:
    brand = ensure_brand(session, brand_slug)
    unknown = set(fields) - set(IDEA_FIELDS)
    if unknown:
        raise ValueError(f"Unknown idea fields: {sorted(unknown)}")
    if not fields.get("title"):
        raise ValueError("title is required")
    idea = Idea(brand=brand, category=get_or_create_category(session, brand, category),
                **{k: v or "" for k, v in fields.items()})
    session.add(idea)
    session.flush()
    session.add(workflow.StatusChange(idea=idea, from_status=None, to_status=workflow.IDEA, note="created"))
    if scores:
        set_scores(session, idea, scores)
    return idea


def update_idea(session: Session, idea: Idea, *, category: str | None = None, **fields) -> Idea:
    for key, value in fields.items():
        if key in IDEA_FIELDS:
            setattr(idea, key, value or "")
    if category is not None:
        idea.category = get_or_create_category(session, idea.brand, category)
    idea.updated_at = utcnow()
    return idea


def set_scores(session: Session, idea: Idea, values: dict[str, int], scored_by: str = "human",
               rationales: dict[str, str] | None = None) -> scoring.ScoreResult:
    valid = scoring.criteria()
    rationales = rationales or {}
    existing = {s.criterion: s for s in idea.scores}
    for key, value in values.items():
        if key not in valid:
            raise ValueError(f"Unknown criterion '{key}'")
        if value in (None, ""):
            continue
        value = int(value)
        if key in existing:
            existing[key].value = value
            existing[key].scored_by = scored_by
            existing[key].rationale = rationales.get(key, existing[key].rationale)
        else:
            idea.scores.append(IdeaScore(criterion=key, value=value, scored_by=scored_by,
                                         rationale=rationales.get(key, "")))
    session.flush()
    result = scoring.score_idea(idea)
    # AI suggestions rank the idea but only a human's scores move it to `scored`.
    if result.complete and idea.status == workflow.IDEA and scored_by == "human":
        workflow.transition(session, idea, workflow.SCORED, note=f"score {result.total}")
    return result


def get_idea(session: Session, idea_id: int) -> Idea:
    idea = session.get(Idea, idea_id)
    if idea is None:
        raise LookupError(f"Idea #{idea_id} not found")
    return idea


def list_ideas(session: Session, statuses: list[str] | None = None) -> list[Idea]:
    stmt = select(Idea)
    if statuses:
        stmt = stmt.where(Idea.status.in_(statuses))
    return list(session.scalars(stmt))


def ranked_queue(session: Session, statuses: list[str] | None = None):
    """Ideas ranked by weighted score. Default: ideas still awaiting selection."""
    statuses = statuses or [workflow.IDEA, workflow.SCORED, workflow.PARKED]
    return scoring.rank(list_ideas(session, statuses))
