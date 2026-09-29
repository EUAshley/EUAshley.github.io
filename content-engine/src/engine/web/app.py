"""Local web UI. Server-rendered forms; no JS build. All logic lives in services."""
from __future__ import annotations

from datetime import date
from functools import wraps

from flask import Flask, Response, flash, g, redirect, render_template, request, url_for

from .. import config, db, generators, reports, scoring, workflow
from ..models import OFFER_TYPES, Category, Idea, Offer
from ..services import ideas, offers, performance, production, publishing

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
                "score_of": scoring.score_idea, "workflow": workflow}

    def action(fn):
        """POST handler wrapper: commit on success, flash errors and go back."""
        @wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                result = fn(*args, **kwargs)
                g.db.commit()
                return result
            except (workflow.WorkflowError, ValueError, LookupError, RuntimeError) as e:
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
                               top=ideas.ranked_queue(g.db)[:5])

    @app.get("/ideas")
    def idea_list():
        status = request.args.get("status")
        rows = scoring.rank(ideas.list_ideas(g.db, [status] if status else None))
        return render_template("ideas.html", rows=rows, status=status)

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
        offers.link_offer(g.db, offer, idea=idea, role=request.form.get("role", "primary"))
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
                                    terms=request.form.get("terms", ""))
        if request.form.get("category_id"):
            offers.link_offer(g.db, offer, category_id=int(request.form["category_id"]))
        return redirect(url_for("offer_page"))

    @app.post("/offers/<int:offer_id>/revenue")
    @action
    def revenue_add(offer_id):
        offer = g.db.get(Offer, offer_id)
        dollars = request.form.get("revenue", "").strip() or "0"
        offers.record_revenue(g.db, offer, on=form_date("date") or date.today(), clicks=form_int("clicks") or 0,
                              conversions=form_int("conversions") or 0,
                              revenue_cents=round(float(dollars) * 100),
                              publication_id=form_int("publication_id"), notes=request.form.get("notes", ""))
        return redirect(url_for("offer_page"))

    @app.get("/report")
    def report_page():
        return render_template("report.html", report=reports.build_report(g.db))

    def _categories():
        brand = ideas.ensure_brand(g.db)
        return g.db.query(Category).filter_by(brand_id=brand.id).order_by(Category.name).all()

    return app
