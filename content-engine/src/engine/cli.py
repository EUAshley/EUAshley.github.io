"""Command-line interface.  Run `engine --help`."""
from __future__ import annotations

from pathlib import Path

import click

from . import config, db, reports, scoring
from .services import ideas, performance, production


@click.group()
def cli():
    """Daily Benefit Shorts content engine."""


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

    db.create_all()
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
@click.argument("csv_path", type=click.Path(exists=True, path_type=Path))
def import_cmd(csv_path):
    """Import performance snapshots from CSV (columns: publication_id or url, views, saves, ...)."""
    with db.session_scope() as s:
        n, errors = performance.import_csv(s, csv_path)
    click.echo(f"Imported {n} snapshot(s).")
    for e in errors:
        click.echo(f"  skipped {e}", err=True)


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
