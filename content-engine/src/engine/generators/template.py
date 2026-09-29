"""Deterministic script generator. No API needed.

Builds a well-structured draft from the idea's fields. The better the idea's
`hook`, `problem_solved`, `benefit`, and `solution_steps`, the better the draft.
Always meant to be edited by a human.
"""
from __future__ import annotations

from ..models import Idea
from .base import ScriptDraft, retime


def _sentence(text: str) -> str:
    text = " ".join(text.split())
    if text and text[-1] not in ".!?":
        text += "."
    return text[:1].upper() + text[1:] if text else text


def _overlay(text: str, words: int = 8) -> str:
    """On-screen text: the first clause, if that is short enough; otherwise the
    whole line (a human shortens it). Never cut mid-phrase."""
    text = " ".join(text.split()).rstrip(".")
    for sep in (". ", ": ", ", ", " - "):
        head = text.split(sep)[0]
        if len(head.split()) <= words and head.count('"') % 2 == 0:
            return head
    return text


class TemplateGenerator:
    name = "template"

    def available(self) -> bool:
        return True

    def generate(self, idea: Idea, brand: dict) -> ScriptDraft:
        fmt = {s["key"]: dict(s) for s in brand.get("script_format") or []}
        steps = idea.steps
        benefit = idea.benefit or idea.title
        hook = idea.hook or f"Your phone can do this for you: {benefit.rstrip('.').lower()}."
        cta = brand.get("default_cta", "Follow for more.")
        notes = []
        if not steps:
            notes.append("No solution_steps on the idea: demo section is a placeholder.")

        def sec(key, label, seconds, **content):
            base = fmt.get(key, {"label": label, "seconds": seconds})
            return {"key": key, "label": base.get("label", label), "seconds": base.get("seconds", seconds), **content}

        # Demo length scales with the number of steps (≈3s per step), capped by the format.
        demo_max = int(fmt.get("demo", {}).get("seconds", 18))
        demo_seconds = max(6, min(demo_max, 3 * len(steps) + 3)) if steps else demo_max
        step_lines = [f"{n}. {s}" for n, s in enumerate(steps, 1)]

        sections = [
            sec("hook", "HOOK", 3,
                voiceover=_sentence(hook),
                on_screen_text=_overlay(hook),
                visual="Open on the finished result (show the benefit happening), not on a home screen."),
            sec("problem", "PROBLEM", 4,
                voiceover=_sentence(idea.problem_solved or "Most people still do this by hand"),
                on_screen_text=_overlay(idea.problem_solved or "Still doing this by hand?"),
                visual="Quick shot of the annoying manual way (or skip if the hook already implies it)."),
            {**sec("demo", "DEMONSTRATION", demo_seconds,
                   voiceover=("Here's how. " + " ".join(_sentence(s) for s in steps)) if steps
                   else "[Walk through the setup steps here.]",
                   on_screen_text="\n".join(step_lines) if step_lines else "[Step labels]",
                   visual="Screen recording of each step, one clip per step; zoom/highlight each tap."),
             "seconds": demo_seconds},
            sec("result", "RESULT", 5,
                voiceover=_sentence(f"That's it. {benefit}"),
                on_screen_text=_overlay(benefit),
                visual="Show it working for real, end to end."),
            sec("cta", "CTA", 3,
                voiceover=_sentence(cta),
                on_screen_text=_overlay(cta),
                visual="Hold on the result; text overlay for the CTA."),
        ]
        return ScriptDraft(
            sections=retime(sections), cta=cta,
            hook_type="result_first" if idea.benefit else "did_you_know",
            generator=self.name, notes=notes,
        )
