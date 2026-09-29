"""Drive the full pipeline through the web UI's HTTP endpoints."""
import pytest

from engine import scoring
from engine.web.app import create_app


@pytest.fixture
def client(session):
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def ok(resp):
    assert resp.status_code in (200, 302), resp.status_code
    return resp


def test_full_pipeline_via_web(client):
    ok(client.post("/ideas/new", data={
        "title": "Back Tap screenshot", "category": "iPhone Features",
        "hook": "Tap the back of your iPhone twice. Screenshot.",
        "problem_solved": "Two-button screenshots are awkward one-handed",
        "benefit": "Double-tap the back of your phone to take a screenshot",
        "solution_steps": "Open Settings > Accessibility\nTouch > Back Tap\nDouble Tap > Screenshot",
        "tools": "Settings",
    }))
    ok(client.post("/ideas/1/scores", data={f"score_{k}": 4 for k in scoring.criteria()}))
    ok(client.post("/ideas/1/transition", data={"to": "selected"}))
    ok(client.post("/ideas/1/script/generate", data={"generator": "template"}))

    # Human edit of the script creates v2
    page = client.get("/ideas/1").get_data(as_text=True)
    assert "v1" in page
    ok(client.post("/ideas/1/script/edit", data={"voiceover_0": "Screenshot without buttons.", "cta": "Follow for more",
                                                 "hook_type": "result_first"}))
    ok(client.post("/ideas/1/package"))

    # Queueing before approval is refused
    client.post("/ideas/1/submit")
    resp = client.post("/ideas/1/queue", data={"platform": "tiktok"}, follow_redirects=True)
    assert "has not been approved" in resp.get_data(as_text=True)

    ok(client.post("/ideas/1/review", data={"decision": "approved", "notes": "good"}))
    ok(client.post("/ideas/1/queue", data={"platform": "tiktok", "scheduled_for": "2026-10-01"}))
    assert "Back Tap screenshot" in client.get("/queue").get_data(as_text=True)
    ok(client.post("/publications/1/published", data={"url": "https://tiktok.com/@x/video/1"}))
    ok(client.post("/publications/1/metrics", data={"views": "5,000", "saves": "250", "shares": "40"}))
    ok(client.post("/ideas/1/learnings", data={"text": "Short hook worked"}))

    ok(client.post("/offers", data={"type": "affiliate", "name": "Phone grip", "category_id": ""}))
    ok(client.post("/offers/1/revenue", data={"clicks": "10", "conversions": "1", "revenue": "4.50",
                                              "publication_id": "1"}))

    page = client.get("/ideas/1").get_data(as_text=True)
    assert "measured" in page and "Screenshot without buttons." in page and "Short hook worked" in page
    md = client.get("/ideas/1/package.md").get_data(as_text=True)
    assert "Screenshot without buttons." in md

    report = client.get("/report").get_data(as_text=True)
    assert "iPhone Features" in report and "5.00%" in report and "$4.50" in report
    for path in ("/", "/ideas", "/ideas?status=measured", "/offers", "/ideas/new", "/ideas/1/edit"):
        assert client.get(path).status_code == 200
