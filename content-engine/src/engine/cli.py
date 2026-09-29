"""Command-line interface.  Run `engine --help`."""
from __future__ import annotations

from pathlib import Path

import click

from . import config, db, reports, scoring
from .services import ideas, performance, production


@click.group()
@click.pass_context
def cli(ctx):
    """Daily Benefit Shorts content engine."""
    if ctx.invoked_subcommand != "demo":
        db.create_all()  # creates tables and adds new columns to existing databases


def _ai_errors(fn):
    """Show AI failures (no key, refusal, truncation) as a clean CLI error."""
    from functools import wraps

    from . import ai

    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (ai.AIUnavailable, RuntimeError) as e:
            raise click.ClickException(str(e))
    return wrapper


@cli.command("init")
def init_cmd():
    """Create database tables (safe to re-run) and the brand's categories."""
    db.create_all()
    with db.session_scope() as s:
        brand = ideas.ensure_brand(s)
        click.echo(f"Database ready at {config.db_url()} (brand: {brand.name})")


@cli.command("seed")
@click.option("--file", "path", type=click.Path(exists=True, path_type=Path), default=None)
def seed_cmd(path):
    """Load example ideas (and offers) from a YAML file."""
    from .demo import load_seed

    with db.session_scope() as s:
        created = load_seed(s, path)
        click.echo(f"Added {len(created)} ideas.")


@cli.command("ideas")
@click.option("--all", "show_all", is_flag=True, help="Include ideas past selection.")
def ideas_cmd(show_all):
    """Ranked idea queue."""
    with db.session_scope() as s:
        rows = scoring.rank(ideas.list_ideas(s)) if show_all else ideas.ranked_queue(s)
        for idea, res in rows:
            total = "  -  " if res.total is None else f"{res.total:5.1f}"
            flag = "" if res.complete else " (partial)"
            cat = idea.category.name if idea.category else ""
            click.echo(f"{total}{flag:<10} #{idea.id:<4} {idea.status:<18} {cat:<22} {idea.title}")


@cli.command("export-package")
@click.argument("idea_id", type=int)
@click.option("--out", type=click.Path(path_type=Path), default=None, help="Write to file instead of stdout.")
def export_cmd(idea_id, out):
    """Export an idea's current production package as Markdown."""
    with db.session_scope() as s:
        package = production.current_package(ideas.get_idea(s, idea_id))
        if package is None:
            raise click.ClickException("No production package yet")
        text = production.package_markdown(package)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
        click.echo(f"Wrote {out}")
    else:
        click.echo(text)


@cli.command("import-metrics")
@click.argument("csv_paths", nargs=-1, type=click.Path(exists=True, path_type=Path))
def import_cmd(csv_paths):
    """Import analytics exports. With no arguments, imports every CSV in
    data/inbox/ and moves it to data/inbox/processed/."""
    with db.session_scope() as s:
        if csv_paths:
            results = {p.name: performance.import_csv(s, p) for p in csv_paths}
        else:
            results = performance.import_inbox(s)
            if not results:
                click.echo(f"No CSV files in {performance.inbox_dir()}")
    for name, r in results.items():
        click.echo(f"{name}: imported {r.imported}, unmatched rows {r.unmatched}")
        for e in r.errors:
            click.echo(f"  {e}", err=True)


@cli.command("import-revenue")
@click.argument("csv_path", type=click.Path(exists=True, path_type=Path))
@click.option("--offer", "offer_ref", default=None, help="Offer id or name, if the report has no offer column.")
def import_revenue_cmd(csv_path, offer_ref):
    """Import an affiliate/revenue report; rows are attributed to videos by tracking code."""
    from .services import tracking

    with db.session_scope() as s:
        offer = tracking.find_offer(s, offer_ref) if offer_ref else None
        if offer_ref and offer is None:
            raise click.ClickException(f"No offer '{offer_ref}'")
        n, errors = tracking.import_revenue_csv(s, csv_path, default_offer=offer)
    click.echo(f"Imported {n} revenue row(s).")
    for e in errors:
        click.echo(f"  {e}", err=True)


@cli.command("due")
def due_cmd():
    """Published videos that need a metrics snapshot (day 1 / 7 / 30)."""
    with db.session_scope() as s:
        due = performance.metrics_due(s)
        for d in due:
            p = d["publication"]
            click.echo(f"day {d['checkpoint']:>2} snapshot due  #{p.idea.id} {p.platform:<16} {p.idea.title}  {p.url}")
        if not due:
            click.echo("No snapshots due.")


@cli.command("ai-ideas")
@click.option("--category", default=None, help="Limit to one category.")
@click.option("--count", default=5, show_default=True)
@click.option("--no-web", is_flag=True, help="Skip web search (faster, cheaper, less current).")
@_ai_errors
def ai_ideas_cmd(category, count, no_web):
    """Research new ideas with Claude, informed by performance and learnings."""
    from .services import ai_assist

    with db.session_scope() as s:
        created = ai_assist.suggest_ideas(s, category=category, count=count, web_search=not no_web)
        for idea in created:
            res = scoring.score_idea(idea)
            click.echo(f"#{idea.id:<4} {res.total or '-':>5} (AI)  {idea.title}")
    click.echo("Review them in the UI; save scores yourself to move them to 'scored'.")


@cli.command("ai-score")
@click.argument("idea_id", type=int)
@_ai_errors
def ai_score_cmd(idea_id):
    """Suggest scores for an idea (fills only criteria you haven't scored)."""
    from .services import ai_assist

    with db.session_scope() as s:
        res = ai_assist.suggest_scores(s, ideas.get_idea(s, idea_id))
        for key, b in res.breakdown.items():
            click.echo(f"  {b['label']:<24} {b['value']}")
        click.echo(f"Total: {res.total}")


@cli.command("daily")
def daily_cmd():
    """Routine run: import the inbox, list snapshots due, print the report."""
    ctx = click.get_current_context()
    ctx.invoke(import_cmd, csv_paths=())
    click.echo("")
    ctx.invoke(due_cmd)
    click.echo("")
    ctx.invoke(report_cmd)


@cli.command("report")
def report_cmd():
    """Print the what's-working report."""
    with db.session_scope() as s:
        click.echo(reports.format_text(reports.build_report(s)))


@cli.command("web")
@click.option("--port", default=5000)
@click.option("--host", default="127.0.0.1")
@click.option("--debug", is_flag=True)
def web_cmd(port, host, debug):
    """Run the local web UI."""
    from .web.app import create_app

    db.create_all()
    create_app().run(host=host, port=port, debug=debug)


@cli.command("demo")
def demo_cmd():
    """Run one idea through the whole pipeline in a throwaway database (data/demo.db)."""
    from .demo import load_seed, run_pipeline

    demo_path = config.PROJECT_ROOT / "data" / "demo.db"
    demo_path.unlink(missing_ok=True)
    db.init_engine(f"sqlite:///{demo_path}")
    db.create_all()
    with db.session_scope() as s:
        seeded = load_seed(s)
        run_pipeline(s, seeded[0], log=click.echo)
        click.echo("\n" + reports.format_text(reports.build_report(s)))
    click.echo(f"\nDemo database: {demo_path}  (browse it: ENGINE_DB_URL=sqlite:///data/demo.db engine web)")


def main():
    cli()


if __name__ == "__main__":
    main()
