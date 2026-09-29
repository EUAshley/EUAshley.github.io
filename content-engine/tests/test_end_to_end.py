"""The MVP milestone: one idea through IDEA -> SCORE -> SCRIPT -> PACKAGE ->
APPROVAL -> PUBLISH QUEUE -> PERFORMANCE RECORD."""
from engine import reports
from engine.demo import load_seed, run_pipeline
from engine.services import offers, performance, production, publishing


def test_one_idea_through_the_whole_system(session, tmp_path):
    seeded = load_seed(session)
    idea = run_pipeline(session, seeded[0], log=lambda *_: None)

    assert idea.status == "measured"
    statuses = [h.to_status for h in idea.history]
    assert statuses == ["idea", "scored", "selected", "scripted", "packaged", "in_review",
                        "approved", "queued", "published", "measured"]

    package = production.current_package(idea)
    assert package.shot_list and package.caption and package.hashtags and package.recording_steps
    assert any("Shortcut Pack" in m for m in package.monetization_notes)  # category-linked offer
    assert package.latest_approval.decision == "approved"
    md = production.package_markdown(package)
    assert "## Shot list" in md and idea.title in md

    pub = package.publications[0]
    assert pub.status == "published" and pub.latest_snapshot.views == 12400

    # Second snapshot via CSV, plus revenue attributed to the video.
    csv_file = tmp_path / "metrics.csv"
    csv_file.write_text(f"url,views,saves,shares,link_clicks\n{pub.url},20000,900,150,40\nhttps://nope,1,1,1,1\n")
    result = performance.import_csv(session, csv_file)
    assert result.imported == 1 and result.unmatched == 1 and not result.errors
    offer = offers.offers_for_idea(session, idea)[0]
    from datetime import date
    offers.record_revenue(session, offer, on=date.today(), clicks=40, conversions=3, revenue_cents=897,
                          publication_id=pub.id)

    rep = reports.build_report(session)
    assert rep["n_measured"] == 1
    cat = rep["by_category"][0]
    assert cat["group"] == "iPhone Shortcuts" and cat["views"] == 20000  # latest snapshot wins
    assert cat["revenue_cents"] == 897
    assert rep["recommendations"][0]["verdict"] == "needs more data"
    assert "BY CATEGORY" in reports.format_text(rep)


def test_queue_is_listed(session):
    seeded = load_seed(session)
    idea = seeded[1]
    from engine import workflow
    workflow.transition(session, idea, workflow.SELECTED)
    production.generate_script(session, idea)
    production.generate_package(session, idea)
    publishing.submit_for_review(session, idea)
    publishing.review(session, idea, "approved")
    publishing.queue(session, idea, "tiktok")
    publishing.queue(session, idea, "instagram_reels")
    assert [p.platform for p in publishing.publish_queue(session)] == ["tiktok", "instagram_reels"]
