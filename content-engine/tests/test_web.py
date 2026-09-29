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


def test_automation_features_via_web(client, monkeypatch):
    import io

    from engine import ai

    fake_scores = {k: {"value": 3, "rationale": "ok"} for k in scoring.criteria()}
    monkeypatch.setattr(ai, "available", lambda: True)
    monkeypatch.setattr(ai, "structured", lambda *a, **k: ({"ideas": [{
        "title": "Silence work apps at 6pm", "category": "Automations", "problem_solved": "p", "benefit": "b",
        "target_audience": "a", "hook": "h", "solution_steps": ["one", "two"], "tools": ["Focus"],
        "research_notes": "n", "scores": fake_scores}]} if "ideas" in a[2]["properties"] else fake_scores, "m"))

    assert "Research new ideas with Claude" in client.get("/ideas").get_data(as_text=True)
    ok(client.post("/ideas/ai-suggest", data={"count": "1", "web_search": "on"}))
    page = client.get("/ideas/1").get_data(as_text=True)
    assert "Silence work apps at 6pm" in page and ">AI<" in page

    # Take it to published with a tracked affiliate offer
    ok(client.post("/offers", data={"type": "affiliate", "name": "Stand", "url": "https://amzn.to/x",
                                    "link_template": "https://amazon.com/dp/B0?tag=me-20&ascsubtag={code}"}))
    ok(client.post("/ideas/1/offers", data={"offer_id": "1"}))
    ok(client.post("/ideas/1/scores", data={f"score_{k}": 4 for k in scoring.criteria()}))
    for path, data in [("/ideas/1/transition", {"to": "selected"}), ("/ideas/1/script/generate", {}),
                       ("/ideas/1/package", {}), ("/ideas/1/submit", {}),
                       ("/ideas/1/review", {"decision": "approved"}),
                       ("/ideas/1/queue", {"platform": "tiktok"})]:
        ok(client.post(path, data=data))
    assert "ascsubtag=dbs1tt1" in client.get("/queue").get_data(as_text=True)
    ok(client.post("/publications/1/published", data={"url": "https://www.tiktok.com/@me/video/123",
                                                      "published_at": "2026-09-01"}))
    import re
    assert re.search(r"day (7|30) snapshot", client.get("/").get_data(as_text=True))  # published weeks ago

    csv_bytes = b"Video link,Video views,Favorites\nhttps://tiktok.com/@me/video/123,2.5K,120\n"
    resp = client.post("/import/metrics", data={"files": (io.BytesIO(csv_bytes), "tiktok.csv")},
                       content_type="multipart/form-data", follow_redirects=True)
    assert "imported 1 snapshot" in resp.get_data(as_text=True)
    rev = b"Date,Tracking ID,Clicks,Items Ordered,Ad Fees\n2026-09-20,dbs1tt1,10,1,$3.25\n"
    resp = client.post("/import/revenue", data={"file": (io.BytesIO(rev), "amazon.csv")},
                       content_type="multipart/form-data", follow_redirects=True)
    assert "imported 1 revenue" in resp.get_data(as_text=True)
    report = client.get("/report").get_data(as_text=True)
    assert "$3.25" in report and "4.80%" in report  # 120 saves / 2,500 views
