"""Local web UI. Server-rendered forms; no JS build. All logic lives in services."""
from __future__ import annotations

import tempfile
from datetime import date
from functools import wraps
from pathlib import Path

from flask import Flask, Response, abort, flash, g, redirect, render_template, request, send_from_directory, url_for

from .. import ai, config, db, generators, reports, scoring, video, workflow
from ..models import OFFER_TYPES, Category, Idea, Offer
from ..services import ai_assist, ideas, offers, performance, production, publishing, rendering, tracking

MANUAL_TRANSITIONS = [workflow.SELECTED, workflow.SCORED, workflow.PARKED, workflow.REJECTED, workflow.IDEA]


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = config.env("ENGINE_SECRET_KEY", "dev-only-not-secret")

    @app.before_request
    def _open_session():
        g.db = db.new_session()

    @app.teardown_request
    def _close_session(exc):
        s = g.pop("db", None)
        if s is not None:
            if exc is None:
                s.commit()
            else:
                s.rollback()
            s.close()

    @app.template_filter("pct")
    def pct(x):
        return "-" if x is None else f"{100 * x:.2f}%"

    @app.template_filter("money")
    def money(cents):
        return f"${(cents or 0) / 100:,.2f}"

    @app.context_processor
    def _globals():
        return {"brand": config.brand_config(config.default_brand_slug()), "criteria": scoring.criteria(),
                "score_of": scoring.score_idea, "workflow": workflow, "ai_enabled": ai.available()}

    def action(fn):
        """POST handler wrapper: commit on success, flash errors and go back."""
        @wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                result = fn(*args, **kwargs)
                g.db.commit()
                return result
            except (workflow.WorkflowError, ValueError, LookupError, RuntimeError, KeyError, video.VideoError) as e:
                g.db.rollback()
                flash(str(e), "error")
                return redirect(request.referrer or url_for("index"))
        return wrapper

    def form_int(name):
        v = request.form.get(name, "").strip()
        return int(v) if v else None

    def form_date(name):
        v = request.form.get(name, "").strip()
        return date.fromisoformat(v) if v else None

    # --- Pages -----------------------------------------------------------------

    @app.get("/")
    def index():
        return render_template("index.html", report=reports.build_report(g.db),
                               queue=publishing.publish_queue(g.db),
                               in_review=ideas.list_ideas(g.db, [workflow.IN_REVIEW]),
                               due=performance.metrics_due(g.db),
                               top=ideas.ranked_queue(g.db)[:5])

    @app.get("/ideas")
    def idea_list():
        status = request.args.get("status")
        rows = scoring.rank(ideas.list_ideas(g.db, [status] if status else None))
        return render_template("ideas.html", rows=rows, status=status, categories=_categories())

    @app.post("/ideas/ai-suggest")
    @action
    def ideas_ai_suggest():
        created = ai_assist.suggest_ideas(g.db, category=request.form.get("category") or None,
                                          count=form_int("count") or 5,
                                          web_search=request.form.get("web_search") == "on")
        flash(f"Claude suggested {len(created)} idea(s). Review the steps and save scores yourself to accept them.")
        return redirect(url_for("idea_list", status="idea"))

    @app.get("/ideas/new")
    def idea_new():
        return render_template("idea_form.html", idea=None, categories=_categories())

    @app.post("/ideas/new")
    @action
    def idea_create():
        fields = {k: request.form.get(k, "") for k in ideas.IDEA_FIELDS}
        idea = ideas.create_idea(g.db, category=request.form.get("category") or None, **fields)
        flash(f"Idea #{idea.id} created. Score it next.")
        return redirect(url_for("idea_detail", idea_id=idea.id) + "#scores")

    @app.get("/ideas/<int:idea_id>")
    def idea_detail(idea_id):
        idea = ideas.get_idea(g.db, idea_id)
        return render_template(
            "idea.html", idea=idea, score=scoring.score_idea(idea),
            package=production.current_package(idea), approved=publishing.is_approved(idea),
            linked_offers=offers.offers_for_idea(g.db, idea), all_offers=g.db.query(Offer).all(),
            generators=generators.available(),
            clips=rendering.list_clips(idea), clips_dir=rendering.clips_dir(idea),
            music_tracks=rendering.music_tracks(idea.brand.slug), renderable=idea.status in rendering.RENDERABLE,
            manual_transitions=[t for t in MANUAL_TRANSITIONS if workflow.can_transition(idea.status, t)],
        )

    @app.get("/ideas/<int:idea_id>/edit")
    def idea_edit(idea_id):
        return render_template("idea_form.html", idea=ideas.get_idea(g.db, idea_id), categories=_categories())

    @app.post("/ideas/<int:idea_id>/edit")
    @action
    def idea_update(idea_id):
        idea = ideas.get_idea(g.db, idea_id)
        ideas.update_idea(g.db, idea, category=request.form.get("category") or None,
                          **{k: request.form.get(k, "") for k in ideas.IDEA_FIELDS})
        return redirect(url_for("idea_detail", idea_id=idea_id))

    @app.post("/ideas/<int:idea_id>/scores")
    @action
    def idea_scores(idea_id):
        idea = ideas.get_idea(g.db, idea_id)
        values = {k: form_int(f"score_{k}") for k in scoring.criteria()}
        rationales = {k: request.form.get(f"why_{k}", "") for k in scoring.criteria()}
        res = ideas.set_scores(g.db, idea, values, rationales=rationales)
        flash(f"Score: {res.total}" + ("" if res.complete else " (partial)"))
        return redirect(url_for("idea_detail", idea_id=idea_id))

    @app.post("/ideas/<int:idea_id>/ai-score")
    @action
    def idea_ai_score(idea_id):
        res = ai_assist.suggest_scores(g.db, ideas.get_idea(g.db, idea_id))
        flash(f"AI suggested scores (total {res.total}). Adjust and save to confirm.")
        return redirect(url_for("idea_detail", idea_id=idea_id) + "#scores")

    @app.post("/ideas/<int:idea_id>/transition")
    @action
    def idea_transition(idea_id):
        idea = ideas.get_idea(g.db, idea_id)
        target = request.form["to"]
        if target not in MANUAL_TRANSITIONS:
            raise ValueError("That status is set by the workflow, not manually")
        workflow.transition(g.db, idea, target, note=request.form.get("note", ""))
        return redirect(url_for("idea_detail", idea_id=idea_id))

    @app.post("/ideas/<int:idea_id>/script/generate")
    @action
    def script_generate(idea_id):
        idea = ideas.get_idea(g.db, idea_id)
        script, notes = production.generate_script(g.db, idea, request.form.get("generator", "template"))
        flash(f"Script v{script.version} generated ({script.generator}).")
        for n in notes:
            flash(n, "warning")
        return redirect(url_for("idea_detail", idea_id=idea_id) + "#script")

    @app.post("/ideas/<int:idea_id>/script/edit")
    @action
    def script_edit(idea_id):
        idea = ideas.get_idea(g.db, idea_id)
        current = idea.current_script
        sections = []
        for i, sec in enumerate(current.sections):
            sections.append({**sec, **{f: request.form.get(f"{f}_{i}", sec.get(f, ""))
                                       for f in ("voiceover", "on_screen_text", "visual", "seconds")}})
        script = production.edit_script(g.db, idea, sections=sections, cta=request.form.get("cta", ""),
                                        hook_type=request.form.get("hook_type", ""))
        flash(f"Saved script v{script.version}. Rebuild the package to include the changes.")
        return redirect(url_for("idea_detail", idea_id=idea_id) + "#script")

    @app.post("/ideas/<int:idea_id>/package")
    @action
    def package_generate(idea_id):
        idea = ideas.get_idea(g.db, idea_id)
        package = production.generate_package(g.db, idea)
        flash(f"Production package #{package.id} built.")
        return redirect(url_for("idea_detail", idea_id=idea_id) + "#package")

    @app.get("/ideas/<int:idea_id>/package.md")
    def package_md(idea_id):
        package = production.current_package(ideas.get_idea(g.db, idea_id))
        if package is None:
            return Response("No package yet", status=404)
        return Response(production.package_markdown(package), mimetype="text/markdown")

    @app.post("/ideas/<int:idea_id>/clips")
    @action
    def clips_upload(idea_id):
        idea = ideas.get_idea(g.db, idea_id)
        saved = [rendering.save_clip(idea, f.filename, f) for f in request.files.getlist("clips") if f and f.filename]
        flash(f"Saved {len(saved)} clip(s). They're used in file-name order.")
        return redirect(url_for("idea_detail", idea_id=idea_id) + "#video")

    @app.post("/ideas/<int:idea_id>/clips/clear")
    @action
    def clips_clear(idea_id):
        rendering.clear_clips(ideas.get_idea(g.db, idea_id))
        return redirect(url_for("idea_detail", idea_id=idea_id) + "#video")

    @app.post("/ideas/<int:idea_id>/render")
    @action
    def render_video(idea_id):
        idea = ideas.get_idea(g.db, idea_id)
        r = rendering.render_video(g.db, idea, music=request.form.get("music", "auto"))
        flash(f"Rendered a {r.seconds:.0f}s video" + (f" with {r.music}." if r.music else " with no music."))
        for w in r.warnings:
            flash(w, "warning")
        return redirect(url_for("idea_detail", idea_id=idea_id) + "#video")

    @app.get("/media/<path:path>")
    def media(path):
        """Serve rendered videos and covers (only from data/renders)."""
        root = config.PROJECT_ROOT / "data" / "renders"
        if not path.startswith("data/renders/"):
            abort(404)
        return send_from_directory(root, path[len("data/renders/"):])

    @app.post("/ideas/<int:idea_id>/submit")
    @action
    def submit(idea_id):
        publishing.submit_for_review(g.db, ideas.get_idea(g.db, idea_id))
        return redirect(url_for("idea_detail", idea_id=idea_id) + "#review")

    @app.post("/ideas/<int:idea_id>/review")
    @action
    def review(idea_id):
        idea = ideas.get_idea(g.db, idea_id)
        publishing.review(g.db, idea, request.form["decision"], notes=request.form.get("notes", ""))
        return redirect(url_for("idea_detail", idea_id=idea_id))

    @app.post("/ideas/<int:idea_id>/queue")
    @action
    def queue_add(idea_id):
        idea = ideas.get_idea(g.db, idea_id)
        pub = publishing.queue(g.db, idea, request.form["platform"], scheduled_for=form_date("scheduled_for"),
                               tracking_link=request.form.get("tracking_link", ""))
        flash(f"Queued for {pub.platform}.")
        return redirect(url_for("idea_detail", idea_id=idea_id) + "#publications")

    @app.post("/publications/<int:pub_id>/published")
    @action
    def pub_published(pub_id):
        pub = publishing.get_publication(g.db, pub_id)
        publishing.mark_published(g.db, pub, request.form["url"].strip(), form_date("published_at"))
        return redirect(url_for("idea_detail", idea_id=pub.idea.id) + "#publications")

    @app.post("/publications/<int:pub_id>/cancel")
    @action
    def pub_cancel(pub_id):
        pub = publishing.get_publication(g.db, pub_id)
        publishing.cancel(g.db, pub)
        return redirect(request.referrer or url_for("queue_page"))

    @app.post("/publications/<int:pub_id>/metrics")
    @action
    def pub_metrics(pub_id):
        pub = publishing.get_publication(g.db, pub_id)
        fields = performance.METRIC_FIELDS + performance.OPTIONAL_FLOAT_FIELDS
        performance.record_snapshot(g.db, pub, **{k: request.form.get(k) for k in fields})
        flash("Performance snapshot saved.")
        return redirect(url_for("idea_detail", idea_id=pub.idea.id) + "#publications")

    @app.post("/ideas/<int:idea_id>/learnings")
    @action
    def learning_add(idea_id):
        idea = ideas.get_idea(g.db, idea_id)
        performance.add_learning(g.db, request.form["text"], idea=idea, tags=request.form.get("tags", ""))
        return redirect(url_for("idea_detail", idea_id=idea_id) + "#learnings")

    @app.post("/ideas/<int:idea_id>/offers")
    @action
    def offer_link(idea_id):
        idea = ideas.get_idea(g.db, idea_id)
        offer = g.db.get(Offer, int(request.form["offer_id"]))
        if offer is None:
            raise LookupError("Offer not found")
        offers.link_offer(g.db, offer, idea=idea, role=request.form.get("role", "primary"))
        tracking.refresh_for_idea(g.db, idea)
        return redirect(url_for("idea_detail", idea_id=idea_id) + "#offers")

    @app.get("/queue")
    def queue_page():
        return render_template("queue.html", queue=publishing.publish_queue(g.db))

    @app.get("/offers")
    def offer_page():
        return render_template("offers.html", summary=reports.offer_summary(g.db), offer_types=OFFER_TYPES,
                               categories=_categories())

    @app.post("/offers")
    @action
    def offer_create():
        offer = offers.create_offer(g.db, type=request.form["type"], name=request.form["name"],
                                    url=request.form.get("url", ""), program=request.form.get("program", ""),
                                    terms=request.form.get("terms", ""),
                                    link_template=request.form.get("link_template", "").strip())
        if request.form.get("category_id"):
            offers.link_offer(g.db, offer, category_id=int(request.form["category_id"]))
        return redirect(url_for("offer_page"))

    @app.post("/offers/<int:offer_id>/revenue")
    @action
    def revenue_add(offer_id):
        offer = g.db.get(Offer, offer_id)
        if offer is None:
            raise LookupError("Offer not found")
        dollars = request.form.get("revenue", "").strip() or "0"
        offers.record_revenue(g.db, offer, on=form_date("date") or date.today(), clicks=form_int("clicks") or 0,
                              conversions=form_int("conversions") or 0,
                              revenue_cents=round(float(dollars) * 100),
                              publication_id=form_int("publication_id"), notes=request.form.get("notes", ""))
        return redirect(url_for("offer_page"))

    def _uploads(field):
        """Save uploaded files to a temp dir and yield (name, path)."""
        tmp = Path(tempfile.mkdtemp())
        for f in request.files.getlist(field):
            if f and f.filename:
                path = tmp / Path(f.filename).name
                f.save(path)
                yield f.filename, path

    @app.post("/import/metrics")
    @action
    def import_metrics():
        for name, path in _uploads("files"):
            r = performance.import_csv(g.db, path)
            flash(f"{name}: imported {r.imported} snapshot(s), {r.unmatched} row(s) matched no published video.")
            for e in r.errors[:10]:
                flash(e, "warning")
        return redirect(url_for("index"))

    @app.post("/import/revenue")
    @action
    def import_revenue():
        offer = g.db.get(Offer, int(request.form["offer_id"])) if request.form.get("offer_id") else None
        for name, path in _uploads("file"):
            n, errors = tracking.import_revenue_csv(g.db, path, default_offer=offer)
            flash(f"{name}: imported {n} revenue row(s).")
            for e in errors[:10]:
                flash(e, "warning")
        return redirect(url_for("offer_page"))

    @app.get("/report")
    def report_page():
        return render_template("report.html", report=reports.build_report(g.db))

    def _categories():
        brand = ideas.ensure_brand(g.db)
        return g.db.query(Category).filter_by(brand_id=brand.id).order_by(Category.name).all()

    return app
