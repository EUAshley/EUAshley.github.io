"""Phase 2 automation: tracking links, revenue attribution, analytics import,
metrics-due reminders, AI suggestions (with Claude mocked), and migrations."""
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, inspect, text

from engine import ai, db, reports, scoring, workflow
from engine.demo import load_seed
from engine.services import ai_assist, ideas, offers, performance, production, publishing, tracking

SCORES = {k: 4 for k in scoring.criteria()}


def _approved_idea(session, **fields):
    idea = ideas.create_idea(session, title=fields.pop("title", "Photos to PDF"), category="iPhone Features",
                             scores=SCORES, solution_steps="Select photos\nTap Print\nPinch out", **fields)
    workflow.transition(session, idea, workflow.SELECTED)
    production.generate_script(session, idea)
    production.generate_package(session, idea)
    publishing.submit_for_review(session, idea)
    publishing.review(session, idea, "approved")
    return idea


def _published(session, idea, platform, url):
    pub = publishing.queue(session, idea, platform)
    publishing.mark_published(session, pub, url, published_at=date.today() - timedelta(days=8))
    return pub


# --- Tracking links & revenue ----------------------------------------------------

def test_queue_assigns_code_and_links(session):
    idea = _approved_idea(session)
    utm = offers.create_offer(session, type="affiliate", name="PDF app", url="https://example.com/app?ref=1")
    amazon = offers.create_offer(session, type="affiliate", name="Phone stand", url="https://amzn.to/x",
                                 link_template="https://amazon.com/dp/B0?tag=me-20&ascsubtag={code}")
    offers.link_offer(session, utm, idea=idea)
    offers.link_offer(session, amazon, idea=idea)
    pub = publishing.queue(session, idea, "tiktok")
    assert pub.tracking_code == f"dbs{idea.id}tt{pub.id}"
    links = {l["offer"]: l["url"] for l in pub.tracking_links}
    assert links["PDF app"] == f"https://example.com/app?ref=1&utm_source=tiktok&utm_medium=shortform&utm_campaign={pub.tracking_code}"
    assert links["Phone stand"].endswith(f"ascsubtag={pub.tracking_code}")


def test_link_template_requires_code(session):
    with pytest.raises(ValueError):
        offers.create_offer(session, type="affiliate", name="x", link_template="https://x.com/?tag=me")


def test_linking_offer_later_refreshes_links(session):
    idea = _approved_idea(session)
    pub = publishing.queue(session, idea, "tiktok")
    assert pub.tracking_links == []
    offer = offers.create_offer(session, type="affiliate", name="Late", url="https://late.example")
    offers.link_offer(session, offer, idea=idea)
    tracking.refresh_for_idea(session, idea)
    assert pub.tracking_links[0]["offer"] == "Late"


def test_revenue_report_attributed_by_code(session, tmp_path):
    idea = _approved_idea(session)
    offer = offers.create_offer(session, type="affiliate", name="Phone stand", url="https://amzn.to/x",
                                link_template="https://amazon.com/dp/B0?tag=me-20&ascsubtag={code}")
    offers.link_offer(session, offer, idea=idea)
    pub = _published(session, idea, "tiktok", "https://www.tiktok.com/@me/video/7300000000000000001")
    performance.record_snapshot(session, pub, views=1000, saves=50)
    report = tmp_path / "amazon.csv"
    report.write_text("Date,Tracking ID,Clicks,Items Ordered,Ad Fees\n"
                      f"09/28/2026,{pub.tracking_code},30,2,\"$5.10\"\n"
                      "09/28/2026,zzz-unknown,4,1,$1.00\n")
    n, errors = tracking.import_revenue_csv(session, report)  # single linked offer is inferred for the known code
    assert n == 1 and "can't tell which offer" in errors[0]
    n, errors = tracking.import_revenue_csv(session, report, default_offer=offer)
    assert n == 2 and "unknown tracking code" in errors[0]
    rows = reports.publication_rows(session)
    assert rows[0]["revenue_cents"] == 1020  # both imports of the attributed row


# --- Analytics import --------------------------------------------------------------

def test_platform_export_matched_by_url_and_video_id(session, tmp_path):
    idea = _approved_idea(session)
    yt = _published(session, idea, "youtube_shorts", "https://youtube.com/shorts/AbC123xyz_0")
    tt = _published(session, idea, "tiktok", "https://www.tiktok.com/@me/video/7300000000000000001?lang=en")
    export = tmp_path / "yt.csv"
    export.write_text(
        "Content,Video title,Views,Average view duration,Average percentage viewed (%),Subscribers,Shares\n"
        "Total,,15000,,,,\n"
        "AbC123xyz_0,Photos to PDF,\"12,345\",0:00:14,71.5,33,120\n")
    tiktok = tmp_path / "tt.csv"
    tiktok.write_text("Video link,Video views,Favorites,Likes,Comments,Shares,New followers,captured_at\n"
                      "https://tiktok.com/@me/video/7300000000000000001,1.2K,85,300,12,9,4,2026-09-29\n")
    r1 = performance.import_csv(session, export)
    r2 = performance.import_csv(session, tiktok)
    assert (r1.imported, r1.unmatched, r2.imported) == (1, 1, 1)
    s = yt.latest_snapshot
    assert (s.views, s.avg_watch_seconds, s.retention_pct, s.follows, s.shares) == (12345, 14.0, 71.5, 33, 120)
    s = tt.latest_snapshot
    assert (s.views, s.saves, s.follows, s.captured_at) == (1200, 85, 4, datetime(2026, 9, 29))


def test_captured_at_column_no_longer_crashes(session, tmp_path):
    idea = _approved_idea(session)
    pub = _published(session, idea, "tiktok", "https://www.tiktok.com/@me/video/1")
    f = tmp_path / "m.csv"
    f.write_text(f"publication_id,captured_at,views\n{pub.id},2026-10-01,500\n")
    assert performance.import_csv(session, f).imported == 1


def test_inbox_imports_and_moves_files(session, tmp_path):
    idea = _approved_idea(session)
    pub = _published(session, idea, "tiktok", "https://www.tiktok.com/@me/video/42")
    (tmp_path / "export.csv").write_text(f"url,views\n{pub.url},10\n")
    results = performance.import_inbox(session, tmp_path)
    assert results["export.csv"].imported == 1
    assert not list(tmp_path.glob("*.csv")) and len(list((tmp_path / "processed").glob("*.csv"))) == 1


def test_metrics_due(session):
    idea = _approved_idea(session)
    pub = _published(session, idea, "tiktok", "https://www.tiktok.com/@me/video/9")  # published 8 days ago
    due = performance.metrics_due(session)
    assert [(d["publication"].id, d["checkpoint"]) for d in due] == [(pub.id, 7)]
    performance.record_snapshot(session, pub, views=100)  # captured now: covers the day-7 checkpoint
    assert performance.metrics_due(session) == []


# --- AI suggestions (Claude mocked) ---------------------------------------------------

def _fake_scores(v=4):
    return {k: {"value": v, "rationale": f"{k} looks solid"} for k in scoring.criteria()}


def test_ai_ideas_land_as_suggestions(session, monkeypatch):
    calls = {}

    def fake(system, prompt, schema, web_search=False, **_):
        calls.update(prompt=prompt, web_search=web_search, schema=schema)
        return {"ideas": [{
            "title": "Focus mode that silences work apps at 6pm", "category": "Automations",
            "problem_solved": "Work pings at dinner", "benefit": "Evenings without work notifications",
            "target_audience": "Remote workers", "hook": "Your phone can clock out for you.",
            "solution_steps": ["Settings > Focus > +", "Add a schedule for 6pm"], "tools": ["Focus"],
            "research_notes": "Verified on iOS 18", "scores": _fake_scores(5)}]}, "claude-opus-5-5"

    monkeypatch.setattr(ai, "structured", fake)
    load_seed(session)
    [idea] = ai_assist.suggest_ideas(session, count=1)
    assert calls["web_search"] and "Turn photos into a PDF without any app" in calls["prompt"]  # dedupe context
    assert "Automations" in calls["schema"]["properties"]["ideas"]["items"]["properties"]["category"]["enum"]
    assert idea.status == "idea" and idea.source.startswith("ai:claude")
    assert idea.steps == ["Settings > Focus > +", "Add a schedule for 6pm"]
    assert all(s.scored_by == "ai" for s in idea.scores) and scoring.score_idea(idea).total == 100.0
    # Human confirms the scores -> becomes `scored`
    ideas.set_scores(session, idea, {s.criterion: s.value for s in idea.scores})
    assert idea.status == "scored"


def test_ai_scores_do_not_overwrite_human(session, monkeypatch):
    monkeypatch.setattr(ai, "structured", lambda *a, **k: (_fake_scores(1), "m"))
    idea = ideas.create_idea(session, title="x", scores={"usefulness": 5})
    ai_assist.suggest_scores(session, idea)
    by = {s.criterion: (s.value, s.scored_by) for s in idea.scores}
    assert by["usefulness"] == (5, "human") and by["novelty"] == (1, "ai")
    assert idea.status == "idea"  # AI alone never promotes


def test_ai_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ai.AIUnavailable):
        ai.structured("s", "p", {})


# --- Migration ------------------------------------------------------------------------

def test_existing_database_gets_new_columns(tmp_path):
    url = f"sqlite:///{tmp_path}/old.db"
    old = create_engine(url)
    with old.begin() as c:  # a pre-Phase-2 publications/offers table
        c.execute(text("CREATE TABLE offers (id INTEGER PRIMARY KEY, type VARCHAR(40), name VARCHAR(200))"))
    db.init_engine(url)
    db.create_all()
    cols = {c["name"] for c in inspect(db.engine()).get_columns("offers")}
    assert {"link_template", "url", "active"} <= cols
