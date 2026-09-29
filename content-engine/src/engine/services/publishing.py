"""Human approval gate and publish queue.

Nothing is posted to any platform automatically. "Publishing" here means the
owner posted it by hand and records the URL. When platform integrations arrive,
they will only ever act on publications that passed `queue()`, which requires an
approval of the exact package being published.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import workflow
from ..models import Approval, Idea, Publication
from . import tracking
from .production import current_package

DECISIONS = {
    "approved": workflow.APPROVED,
    "changes_requested": workflow.CHANGES_REQUESTED,
    "rejected": workflow.REJECTED,
}


def submit_for_review(session: Session, idea: Idea) -> Idea:
    if current_package(idea) is None:
        raise workflow.WorkflowError("Build a production package before submitting for review")
    return workflow.transition(session, idea, workflow.IN_REVIEW, note="submitted for review")


def review(session: Session, idea: Idea, decision: str, notes: str = "", reviewer: str = "owner") -> Approval:
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {list(DECISIONS)}")
    if idea.status != workflow.IN_REVIEW:
        raise workflow.WorkflowError(f"Idea #{idea.id} is not in review (status '{idea.status}')")
    package = current_package(idea)
    approval = Approval(package=package, decision=decision, notes=notes, reviewer=reviewer)
    session.add(approval)
    session.flush()
    workflow.transition(session, idea, DECISIONS[decision], note=f"{decision}: {notes}".strip(": "))
    return approval


def is_approved(idea: Idea) -> bool:
    package = current_package(idea)
    return bool(package and package.latest_approval and package.latest_approval.decision == "approved")


def queue(session: Session, idea: Idea, platform: str, scheduled_for: date | None = None,
          tracking_link: str = "") -> Publication:
    """Add an approved package to the publish queue for one platform."""
    if not is_approved(idea):
        raise workflow.WorkflowError("The current production package has not been approved")
    if idea.status not in {workflow.APPROVED, workflow.QUEUED, workflow.PUBLISHED, workflow.MEASURED}:
        raise workflow.WorkflowError(f"Cannot queue while idea is '{idea.status}'")
    pub = Publication(package=current_package(idea), platform=platform, scheduled_for=scheduled_for,
                      tracking_link=tracking_link)
    session.add(pub)
    session.flush()
    tracking.assign(session, pub)
    if idea.status == workflow.APPROVED:
        workflow.transition(session, idea, workflow.QUEUED, note=f"queued for {platform}")
    return pub


def mark_published(session: Session, pub: Publication, url: str, published_at: date | None = None) -> Publication:
    if pub.status != "queued":
        raise workflow.WorkflowError(f"Publication #{pub.id} is '{pub.status}', not queued")
    pub.status = "published"
    pub.url = url
    pub.published_at = published_at or date.today()
    idea = pub.idea
    if idea.status == workflow.QUEUED:
        workflow.transition(session, idea, workflow.PUBLISHED, note=f"published on {pub.platform}")
    return pub


def cancel(session: Session, pub: Publication) -> Publication:
    if pub.status != "queued":
        raise workflow.WorkflowError("Only queued publications can be cancelled")
    pub.status = "cancelled"
    idea = pub.idea
    still_queued = [p for p in pub.package.publications if p.status == "queued"]
    if idea.status == workflow.QUEUED and not still_queued:
        workflow.transition(session, idea, workflow.APPROVED, note="removed from queue")
    return pub


def publish_queue(session: Session) -> list[Publication]:
    stmt = select(Publication).where(Publication.status == "queued").order_by(
        Publication.scheduled_for.is_(None), Publication.scheduled_for, Publication.id)
    return list(session.scalars(stmt))


def get_publication(session: Session, pub_id: int) -> Publication:
    pub = session.get(Publication, pub_id)
    if pub is None:
        raise LookupError(f"Publication #{pub_id} not found")
    return pub
