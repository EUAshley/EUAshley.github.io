"""Walks one idea through the whole pipeline. Used by `engine demo` (against a
throwaway database) and by the end-to-end test."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from . import config
from .models import Category, Idea
from .services import ideas, offers, performance, production, publishing


def load_seed(session: Session, path: Path | None = None) -> list[Idea]:
    path = path or config.PROJECT_ROOT / "seeds" / "example_ideas.yaml"
    data = yaml.safe_load(path.read_text())
    created = [ideas.create_idea(session, **item) for item in data.get("ideas", [])]
    for spec in data.get("offers", []):
        spec = dict(spec)
        cat_name = spec.pop("link_category", None)
        offer = offers.create_offer(session, **spec)
        if cat_name:
            cat = session.query(Category).filter_by(name=cat_name).first()
            if cat:
                offers.link_offer(session, offer, category_id=cat.id)
    return created


def run_pipeline(session: Session, idea: Idea, log=print) -> Idea:
    from .workflow import SELECTED, transition

    log(f"1. IDEA       #{idea.id} {idea.title}  [{idea.status}]")
    ranked = ideas.ranked_queue(session)
    log(f"2. SCORE      {next(r.total for i, r in ranked if i.id == idea.id)} / 100 "
        f"(rank {[i.id for i, _ in ranked].index(idea.id) + 1} of {len(ranked)})")
    transition(session, idea, SELECTED, note="picked from ranked queue")
    log(f"3. SELECT     [{idea.status}]")
    script, notes = production.generate_script(session, idea, "template")
    log(f"4. SCRIPT     v{script.version}, {script.target_seconds}s, hook type {script.hook_type}  [{idea.status}]")
    package = production.generate_package(session, idea)
    log(f"5. PACKAGE    #{package.id}: {len(package.shot_list)} shots, est. {package.est_minutes} min  [{idea.status}]")
    publishing.submit_for_review(session, idea)
    publishing.review(session, idea, "approved", notes="demo approval")
    log(f"6. APPROVAL   approved  [{idea.status}]")
    pub = publishing.queue(session, idea, "tiktok", scheduled_for=date.today())
    log(f"7. QUEUE      publication #{pub.id} on {pub.platform}  [{idea.status}]")
    publishing.mark_published(session, pub, url="https://www.tiktok.com/@example/video/0000000000")
    log(f"8. PUBLISHED  {pub.url}  [{idea.status}]")
    performance.record_snapshot(session, pub, views=12400, likes=830, comments=41, shares=96,
                                saves=512, follows=37, link_clicks=18, avg_watch_seconds=11.2)
    performance.add_learning(session, "Result-first hook held attention; saves were high relative to views.",
                             idea=idea, publication_id=pub.id, tags="hook,saves")
    log(f"9. MEASURED   12,400 views, 512 saves  [{idea.status}]")
    return idea
