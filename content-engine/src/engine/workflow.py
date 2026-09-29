"""Status workflow for a content item (Idea).

    idea -> scored -> selected -> scripted -> packaged -> in_review
         -> approved -> queued -> published -> measured

    in_review -> changes_requested -> scripted | packaged (loop back)
    most states -> parked | rejected;  parked -> idea | scored

The one hard rule: nothing reaches `queued` without an approval record for the
current production package (enforced in services.publishing).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .models import Idea, StatusChange

IDEA = "idea"
SCORED = "scored"
SELECTED = "selected"
SCRIPTED = "scripted"
PACKAGED = "packaged"
IN_REVIEW = "in_review"
CHANGES_REQUESTED = "changes_requested"
APPROVED = "approved"
QUEUED = "queued"
PUBLISHED = "published"
MEASURED = "measured"
PARKED = "parked"
REJECTED = "rejected"

PIPELINE = [IDEA, SCORED, SELECTED, SCRIPTED, PACKAGED, IN_REVIEW, APPROVED, QUEUED, PUBLISHED, MEASURED]
ALL_STATUSES = PIPELINE + [CHANGES_REQUESTED, PARKED, REJECTED]

TRANSITIONS: dict[str, set[str]] = {
    IDEA: {SCORED, PARKED, REJECTED},
    SCORED: {SELECTED, PARKED, REJECTED},
    SELECTED: {SCRIPTED, SCORED, PARKED, REJECTED},
    SCRIPTED: {PACKAGED, SCRIPTED, PARKED, REJECTED},
    PACKAGED: {IN_REVIEW, SCRIPTED, PACKAGED, PARKED, REJECTED},
    IN_REVIEW: {APPROVED, CHANGES_REQUESTED, REJECTED},
    CHANGES_REQUESTED: {SCRIPTED, PACKAGED, PARKED, REJECTED},
    APPROVED: {QUEUED, SCRIPTED, PARKED},
    QUEUED: {PUBLISHED, APPROVED},
    PUBLISHED: {MEASURED},
    MEASURED: set(),
    PARKED: {IDEA, SCORED},
    REJECTED: {IDEA},
}

# States where editing the script/package is allowed.
EDITABLE = {SELECTED, SCRIPTED, PACKAGED, CHANGES_REQUESTED, APPROVED}


class WorkflowError(ValueError):
    pass


def can_transition(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, set())


def transition(session: Session, idea: Idea, target: str, note: str = "") -> Idea:
    if target not in ALL_STATUSES:
        raise WorkflowError(f"Unknown status '{target}'")
    if not can_transition(idea.status, target):
        raise WorkflowError(f"Cannot move idea #{idea.id} from '{idea.status}' to '{target}'")
    session.add(StatusChange(idea=idea, from_status=idea.status, to_status=target, note=note))
    idea.status = target
    return idea


def advance_to(session: Session, idea: Idea, target: str, note: str = "") -> Idea:
    """Transition only if not already there (for idempotent automatic moves)."""
    if idea.status != target:
        transition(session, idea, target, note)
    return idea
