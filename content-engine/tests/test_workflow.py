import pytest

from engine import scoring, workflow
from engine.services import ideas, production, publishing

SCORES = {k: 4 for k in scoring.criteria()}


def _packaged(session):
    idea = ideas.create_idea(session, title="Photos to PDF", category="iPhone Features", scores=SCORES,
                             solution_steps="Select photos\nTap Print\nPinch out")
    workflow.transition(session, idea, workflow.SELECTED)
    production.generate_script(session, idea)
    production.generate_package(session, idea)
    return idea


def test_illegal_transition_rejected(session):
    idea = ideas.create_idea(session, title="x")
    with pytest.raises(workflow.WorkflowError):
        workflow.transition(session, idea, workflow.PUBLISHED)


def test_cannot_queue_without_approval(session):
    idea = _packaged(session)
    with pytest.raises(workflow.WorkflowError):
        publishing.queue(session, idea, "tiktok")
    publishing.submit_for_review(session, idea)
    with pytest.raises(workflow.WorkflowError):
        publishing.queue(session, idea, "tiktok")


def test_changes_requested_loop_requires_fresh_approval(session):
    idea = _packaged(session)
    publishing.submit_for_review(session, idea)
    publishing.review(session, idea, "changes_requested", notes="shorter hook")
    assert idea.status == workflow.CHANGES_REQUESTED

    script = idea.current_script
    sections = [dict(s) for s in script.sections]
    sections[0]["voiceover"] = "Photos to PDF. No app."
    production.edit_script(session, idea, sections=sections, cta=script.cta, hook_type="result_first")
    assert idea.current_script.version == 2
    production.generate_package(session, idea)
    # New package has no approval yet
    assert not publishing.is_approved(idea)
    publishing.submit_for_review(session, idea)
    publishing.review(session, idea, "approved")
    assert publishing.queue(session, idea, "youtube_shorts").platform == "youtube_shorts"


def test_approving_then_editing_script_revokes_approval(session):
    idea = _packaged(session)
    publishing.submit_for_review(session, idea)
    publishing.review(session, idea, "approved")
    production.generate_script(session, idea)  # allowed from approved; moves back to scripted
    assert idea.status == workflow.SCRIPTED
    assert not publishing.is_approved(idea)


def test_no_script_changes_once_queued(session):
    idea = _packaged(session)
    publishing.submit_for_review(session, idea)
    publishing.review(session, idea, "approved")
    publishing.queue(session, idea, "tiktok")
    with pytest.raises(workflow.WorkflowError):
        production.generate_script(session, idea)


def test_cancel_last_queued_returns_to_approved(session):
    idea = _packaged(session)
    publishing.submit_for_review(session, idea)
    publishing.review(session, idea, "approved")
    pub = publishing.queue(session, idea, "tiktok")
    publishing.cancel(session, pub)
    assert idea.status == workflow.APPROVED
