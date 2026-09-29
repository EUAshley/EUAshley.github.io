"""Clips in, finished video out.

Workflow: after the package is built (status `packaged`, or
`changes_requested`), record the clips listed in the package, drop them into
data/clips/idea-<id>/ (or upload in the UI), and render. The render becomes
part of what you review: approval covers the package *and* its video, and a
video can't be re-rendered once approved without going back through review.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from .. import config, video, workflow
from ..models import Idea, Render
from .production import current_package

RENDERABLE = {workflow.PACKAGED, workflow.CHANGES_REQUESTED}


def clips_dir(idea: Idea) -> Path:
    return config.PROJECT_ROOT / "data" / "clips" / f"idea-{idea.id}"


def list_clips(idea: Idea) -> list[Path]:
    return video.list_media(clips_dir(idea), video.VIDEO_EXTS)


def save_clip(idea: Idea, filename: str, data) -> Path:
    """Save an uploaded clip, keeping its original name (recording order)."""
    name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name)
    if Path(name).suffix.lower() not in video.VIDEO_EXTS:
        raise ValueError(f"{filename}: not a video file ({', '.join(sorted(video.VIDEO_EXTS))})")
    folder = clips_dir(idea)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    data.save(path) if hasattr(data, "save") else path.write_bytes(data)
    return path


def clear_clips(idea: Idea) -> None:
    shutil.rmtree(clips_dir(idea), ignore_errors=True)


def music_dir(brand_slug: str) -> Path:
    cfg = video.settings(config.brand_config(brand_slug))
    path = Path(cfg["music_dir"])
    return path if path.is_absolute() else config.PROJECT_ROOT / path


def music_tracks(brand_slug: str) -> list[Path]:
    return video.list_media(music_dir(brand_slug), video.MUSIC_EXTS)


def _pick_music(idea: Idea, choice: str | None) -> Path | None:
    """choice: None/"auto" rotates through the music folder; "none" = silent;
    otherwise a file name in the music folder."""
    tracks = music_tracks(idea.brand.slug)
    if choice == "none" or not tracks:
        return None
    if choice in (None, "", "auto"):
        return tracks[idea.id % len(tracks)]
    for t in tracks:
        if t.name == choice:
            return t
    raise ValueError(f"No music track named '{choice}' in {music_dir(idea.brand.slug)}")


def texts_for(idea: Idea) -> tuple[dict, list[str]]:
    package = current_package(idea)
    by_key = {s["key"]: s for s in package.script.sections}

    def txt(key):
        return (by_key.get(key) or {}).get("on_screen_text", "").strip()

    texts = {"hook": txt("hook") or package.opening_hook, "problem": txt("problem"),
             "result": txt("result") or idea.benefit, "cta": txt("cta") or package.cta}
    steps = [s["on_screen_text"] for s in package.shot_list if s.get("key") == "demo"]
    if not steps:  # packages built before shots carried a key
        steps = [f"{n}. {s}" for n, s in enumerate(idea.steps, 1)]
    return texts, steps


def plan_for(idea: Idea) -> video.Plan:
    cfg = video.settings(config.brand_config(idea.brand.slug))
    clips = [(p, video.probe_duration(p)) for p in list_clips(idea)]
    texts, steps = texts_for(idea)
    return video.plan_video(texts, steps, clips, cfg)


def render_video(session: Session, idea: Idea, music: str | None = "auto") -> Render:
    package = current_package(idea)
    if package is None:
        raise workflow.WorkflowError("Build a production package first")
    if idea.status not in RENDERABLE:
        raise workflow.WorkflowError(
            f"Videos are rendered before review (status packaged or changes_requested); idea is '{idea.status}'")
    cfg = video.settings(config.brand_config(idea.brand.slug))
    plan = plan_for(idea)
    track = _pick_music(idea, music)
    out = config.PROJECT_ROOT / "data" / "renders" / f"idea-{idea.id}" / f"v{package.script.version}-p{package.id}.mp4"
    result = video.render(plan, out, cfg, music=track, cover_text=package.cover_text)
    out.with_name(out.stem + "-caption.txt").write_text(package.caption)
    render = Render(package=package, path=str(out.relative_to(config.PROJECT_ROOT)),
                    cover_path=str(result["cover"].relative_to(config.PROJECT_ROOT)),
                    seconds=result["seconds"], clip_count=len(list_clips(idea)),
                    music=track.name if track else "", warnings=plan.warnings)
    session.add(render)
    session.flush()
    return render
