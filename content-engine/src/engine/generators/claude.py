"""Optional Claude-backed script generator.

Enabled only when ANTHROPIC_API_KEY is set and the `anthropic` package is
installed (`pip install -e ".[ai]"`). Produces the same ScriptDraft shape as the
template generator, so everything downstream is identical.
"""
from __future__ import annotations

import json

from .. import config
from ..models import Idea
from .base import ScriptDraft, retime

SECTION_KEYS = ["hook", "problem", "demo", "result", "cta"]

SCHEMA = {
    "type": "object",
    "properties": {
        "hook_type": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "enum": SECTION_KEYS},
                    "seconds": {"type": "integer"},
                    "voiceover": {"type": "string"},
                    "on_screen_text": {"type": "string"},
                    "visual": {"type": "string"},
                },
                "required": ["key", "seconds", "voiceover", "on_screen_text", "visual"],
                "additionalProperties": False,
            },
        },
        "cta": {"type": "string"},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["hook_type", "sections", "cta", "notes"],
    "additionalProperties": False,
}

SYSTEM = """You write scripts for short vertical videos (TikTok, Reels, Shorts) that teach one \
genuinely useful technology trick. Usefulness and clarity beat hype: no clickbait, no filler, \
no claims the demo can't show. Open by showing or stating the benefit, then show exactly how. \
Keep the whole video as short as it can be while still being followable; shorter than the \
default timings is fine. Voiceover should be plain spoken English a viewer can follow while \
watching the screen. On-screen text should be a few words per section. `visual` tells the \
editor what is on screen. Use `notes` for anything the creator must verify (e.g. menu names \
that differ by OS version)."""


class ClaudeGenerator:
    name = "claude"

    def available(self) -> bool:
        if not config.env("ANTHROPIC_API_KEY"):
            return False
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return True

    def _prompt(self, idea: Idea, brand: dict) -> str:
        fmt = "\n".join(f"- {s['key']} ({s['label']}): ~{s['seconds']}s" for s in brand.get("script_format", []))
        steps = "\n".join(f"{n}. {s}" for n, s in enumerate(idea.steps, 1)) or "(not provided; infer carefully and flag in notes)"
        return f"""Brand: {brand.get('name')}
Voice: {brand.get('voice', '').strip()}
Default CTA: {brand.get('default_cta', '')}
Hook types (pick one for hook_type): {', '.join(brand.get('hook_types', []))}

Default structure (sections in this order):
{fmt}

Idea
- Title: {idea.title}
- Category: {idea.category.name if idea.category else ''}
- Problem solved: {idea.problem_solved}
- Benefit: {idea.benefit}
- Audience: {idea.target_audience}
- Suggested hook: {idea.hook}
- Tools/apps: {idea.tools}
- Steps:
{steps}
- Research notes: {idea.research_notes}

Write the script."""

    def generate(self, idea: Idea, brand: dict) -> ScriptDraft:
        import anthropic

        client = anthropic.Anthropic()
        response = client.beta.messages.create(
            model=config.env("ENGINE_CLAUDE_MODEL", "claude-opus-5-5"),
            max_tokens=16000,
            system=SYSTEM,
            messages=[{"role": "user", "content": self._prompt(idea, brand)}],
            output_config={
                "effort": config.env("ENGINE_CLAUDE_EFFORT", "medium"),
                "format": {"type": "json_schema", "schema": SCHEMA},
            },
            # Server-side refusal fallback: reroutes a declined request automatically.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if response.stop_reason == "refusal":
            raise RuntimeError("Claude declined to write this script; use the template generator.")
        if response.stop_reason == "max_tokens":
            raise RuntimeError("Claude's response was truncated; try again.")
        text = next(b.text for b in response.content if b.type == "text")
        data = json.loads(text)

        labels = {s["key"]: s["label"] for s in brand.get("script_format", [])}
        order = {k: i for i, k in enumerate(SECTION_KEYS)}
        sections = sorted(data["sections"], key=lambda s: order.get(s["key"], 99))
        for s in sections:
            s["label"] = labels.get(s["key"], s["key"].upper())
        return ScriptDraft(
            sections=retime(sections),
            cta=data["cta"],
            hook_type=data["hook_type"],
            generator=f"{self.name}:{response.model}",
            notes=data.get("notes", []),
        )
