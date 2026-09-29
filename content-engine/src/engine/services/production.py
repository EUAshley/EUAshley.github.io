"""Script and production-package generation."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import config, generators, workflow
from ..generators.base import retime
from ..generators.package import build_package_fields
from ..models import Idea, ProductionPackage, Script
from . import offers as offer_service


def _brand(idea: Idea) -> dict:
    return config.brand_config(idea.brand.slug)


def _save_script(session: Session, idea: Idea, *, sections, cta, hook_type, generator, note) -> Script:
    if idea.status not in workflow.EDITABLE:
        raise workflow.WorkflowError(
            f"Idea #{idea.id} is '{idea.status}'; scripts can only change while "
            f"{sorted(workflow.EDITABLE)}"
        )
    for s in idea.scripts:
        s.is_current = False
    version = max((s.version for s in idea.scripts), default=0) + 1
    script = Script(idea=idea, version=version, is_current=True, sections=sections, cta=cta,
                    hook_type=hook_type, generator=generator,
                    target_seconds=max((s["end"] for s in sections), default=0))
    session.add(script)
    session.flush()
    workflow.advance_to(session, idea, workflow.SCRIPTED, note=note)
    return script


def generate_script(session: Session, idea: Idea, generator: str = "template") -> tuple[Script, list[str]]:
    draft = generators.get(generator).generate(idea, _brand(idea))
    script = _save_script(session, idea, sections=draft.sections, cta=draft.cta, hook_type=draft.hook_type,
                          generator=draft.generator, note=f"script generated ({draft.generator})")
    return script, draft.notes


def edit_script(session: Session, idea: Idea, *, sections: list[dict], cta: str, hook_type: str) -> Script:
    """Save a human-edited script as a new version. `sections` items need key/label/seconds + text."""
    clean = [
        {
            "key": s["key"], "label": s.get("label", s["key"].upper()),
            "seconds": int(s.get("seconds") or 1),
            "voiceover": s.get("voiceover", "").strip(),
            "on_screen_text": s.get("on_screen_text", "").strip(),
            "visual": s.get("visual", "").strip(),
        }
        for s in sections
    ]
    return _save_script(session, idea, sections=retime(clean), cta=cta.strip(), hook_type=hook_type,
                        generator="manual", note="script edited")


def generate_package(session: Session, idea: Idea) -> ProductionPackage:
    script = idea.current_script
    if script is None:
        raise workflow.WorkflowError("Generate a script first")
    if idea.status not in {workflow.SCRIPTED, workflow.PACKAGED, workflow.CHANGES_REQUESTED}:
        raise workflow.WorkflowError(f"Cannot build a package while idea is '{idea.status}'")
    fields = build_package_fields(idea, script, _brand(idea), offer_service.offers_for_idea(session, idea))
    package = ProductionPackage(script=script, **fields)
    session.add(package)
    session.flush()
    workflow.advance_to(session, idea, workflow.PACKAGED, note=f"package #{package.id} built")
    return package


def current_package(idea: Idea) -> ProductionPackage | None:
    script = idea.current_script
    return script.current_package if script else None


def package_markdown(package: ProductionPackage) -> str:
    """Export a package as a Markdown brief for filming/editing."""
    s = package.script
    idea = s.idea
    lines = [
        f"# {package.title}",
        f"Idea #{idea.id} · script v{s.version} ({s.generator}) · hook type: {s.hook_type or '-'} · "
        f"~{s.target_seconds}s · est. {package.est_minutes} min to produce",
        "", "## Opening hook", package.opening_hook,
        "", "## Script",
    ]
    for sec in s.sections:
        lines += [f"**{sec['label']}** ({sec['start']}–{sec['end']}s)",
                  f"- Voiceover: {sec.get('voiceover', '')}",
                  f"- On screen: {sec.get('on_screen_text', '')}",
                  f"- Visual: {sec.get('visual', '')}", ""]
    lines += ["## Shot list"] + [f"{x['shot']}. [{x['time']}] {x['section']}: {x['visual']}" for x in package.shot_list]
    lines += ["", "## Screen-recording instructions"] + [f"- {x}" for x in package.recording_steps]
    lines += ["", "## On-screen text"] + [f"- {x}" for x in package.on_screen_text]
    lines += ["", "## Caption", "```", package.caption, "```"]
    lines += ["", "## CTA", package.cta]
    lines += ["", "## Hashtags / keywords", " ".join(f"#{h}" for h in package.hashtags), ", ".join(package.keywords)]
    lines += ["", "## Cover text", package.cover_text]
    lines += ["", "## Required assets"] + [f"- {x}" for x in package.required_assets]
    lines += ["", "## Monetization"] + [f"- {x}" for x in package.monetization_notes]
    return "\n".join(lines) + "\n"
