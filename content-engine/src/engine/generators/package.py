"""Builds a production package from a script. Deterministic: everything is
derived from the script, the idea, the brand profile, and linked offers."""
from __future__ import annotations

import re

from ..models import Idea, Offer, Script


def _tag(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def build_package_fields(idea: Idea, script: Script, brand: dict, offers: list[Offer]) -> dict:
    sections = script.sections
    by_key = {s["key"]: s for s in sections}
    steps = idea.steps
    hook_line = by_key.get("hook", {}).get("voiceover") or idea.hook or idea.title

    shot_list = []
    for s in sections:
        if s["key"] == "demo" and steps:
            # One shot per step, splitting the demo time evenly.
            span = (s["end"] - s["start"]) / len(steps)
            for i, step in enumerate(steps):
                a, b = s["start"] + i * span, s["start"] + (i + 1) * span
                shot_list.append({"time": f"{a:.0f}-{b:.0f}s", "section": f"{s['label']} {i + 1}/{len(steps)}",
                                  "visual": f"Screen recording: {step}", "on_screen_text": f"{i + 1}. {step}"})
        else:
            shot_list.append({"time": f"{s['start']}-{s['end']}s", "section": s["label"],
                              "visual": s.get("visual", ""), "on_screen_text": s.get("on_screen_text", "")})
    for n, shot in enumerate(shot_list, 1):
        shot["shot"] = n

    recording_steps = list(brand.get("recording_prep", []))
    if steps:
        recording_steps += [f"Clip {n}: {s}" for n, s in enumerate(steps, 1)]
        recording_steps.append("Final clip: trigger it for real and capture the result on screen.")
    else:
        recording_steps.append("Add solution_steps to the idea to get per-step recording instructions.")

    cat = idea.category.name if idea.category else ""
    tags_cfg = brand.get("hashtags") or {}
    hashtags = list(dict.fromkeys(
        tags_cfg.get("by_category", {}).get(cat, []) + [_tag(t) for t in idea.tool_list] + tags_cfg.get("base", [])
    ))
    hashtags = [h for h in hashtags if h][:8]
    keywords = list(dict.fromkeys([idea.title, cat, *idea.tool_list]))
    keywords = [k for k in keywords if k]

    caption = (brand.get("caption_template") or "{hook}\n\n{steps}\n\n{cta}").format(
        hook=hook_line,
        benefit=idea.benefit,
        steps="\n".join(f"{n}. {s}" for n, s in enumerate(steps, 1)) or "(see video)",
        cta=script.cta,
        title=idea.title,
    ).strip()
    caption += "\n\n" + " ".join(f"#{h}" for h in hashtags)

    required_assets = [f"Screen recording clips ({len(steps) or '?'} steps + result)"]
    required_assets += [f"Access to: {t}" for t in idea.tool_list]
    required_assets += ["Voiceover recording (or on-screen text only)", "Cover frame / thumbnail"]

    monetization = [
        f"{o.type}: {o.name}" + (f" ({o.program})" if o.program else "") + (f" - {o.url}" if o.url else "")
        for o in offers
    ] or ["No offers linked yet. Consider: affiliate for tools used, a Shortcut pack, newsletter signup."]

    # Rough estimate: setup + per-step recording + editing proportional to length.
    est = 15 + 5 * max(1, len(steps)) + script.target_seconds // 2

    return {
        "title": idea.title,
        "opening_hook": hook_line,
        "voiceover": script.voiceover,
        "shot_list": shot_list,
        "recording_steps": recording_steps,
        "on_screen_text": [x["on_screen_text"] for x in shot_list if x["on_screen_text"]],
        "caption": caption,
        "cta": script.cta,
        "hashtags": hashtags,
        "keywords": keywords,
        "cover_text": by_key.get("hook", {}).get("on_screen_text") or idea.title,
        "required_assets": required_assets,
        "monetization_notes": monetization,
        "est_minutes": est,
    }
