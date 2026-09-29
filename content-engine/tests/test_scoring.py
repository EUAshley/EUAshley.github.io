from engine import scoring
from engine.services import ideas

ALL_5 = {k: 5 for k in scoring.criteria()}
ALL_1 = {k: 1 for k in scoring.criteria()}


def test_bounds():
    assert scoring.compute(ALL_5).total == 100.0
    assert scoring.compute(ALL_1).total == 0.0
    assert scoring.compute({}).total is None


def test_partial_scores_are_flagged():
    res = scoring.compute({"usefulness": 5})
    assert res.total == 100.0 and not res.complete


def test_weights_matter():
    # usefulness (25) outweighs novelty (10)
    useful = scoring.compute({**ALL_1, "usefulness": 5}).total
    novel = scoring.compute({**ALL_1, "novelty": 5}).total
    assert useful > novel


def test_complete_scores_move_idea_to_scored_and_rank(session):
    low = ideas.create_idea(session, title="Low", scores=ALL_1)
    high = ideas.create_idea(session, title="High", scores=ALL_5)
    unscored = ideas.create_idea(session, title="Unscored")
    assert high.status == "scored" and unscored.status == "idea"
    ranked = [i.title for i, _ in ideas.ranked_queue(session)]
    assert ranked == ["High", "Low", "Unscored"]
