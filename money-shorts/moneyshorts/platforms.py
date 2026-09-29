"""Multi-platform release: one episode -> a video + publish kit per platform.

Platform rules live in PLATFORMS. An episode can adjust any platform with a
`variants:` block:

  variants:
    tiktok:
      add_scenes:                 # extra scenes (fact-checked like the rest)
        - after: fees             # insert after this scene id
          id: exec-tier
          type: compare
          say: ...
      drop_scenes: [some-id]      # optional
      publish: {title: ..., description: ..., hashtags: [...]}

Platforms whose final scene list is identical share one render (copied, not
re-rendered).

Rules reflect platform guidance as of late 2025 — re-check before relying on
them (see `note` on each platform).
"""
from __future__ import annotations

import copy
import shutil
from dataclasses import dataclass
from pathlib import Path

from .spec import Episode, SpecError, parse_scene


@dataclass(frozen=True)
class Platform:
    key: str
    name: str
    min_s: float
    max_s: float
    title_max: int          # 0 = platform has no separate title field
    caption_max: int
    hashtags_max: int
    extra_tags: tuple[str, ...] = ()
    sources: str = "full"   # full = URLs in caption, names = publisher names only, comment = first comment
    note: str = ""


PLATFORMS: dict[str, Platform] = {
    "youtube": Platform(
        "youtube", "YouTube Shorts", 1, 180, title_max=100, caption_max=5000, hashtags_max=3,
        extra_tags=("shorts",),
        note="Shorts up to 3 min. First 3 hashtags show above the title. Use the 'altered or synthetic "
             "content' toggle if the video could be mistaken for real footage.",
    ),
    "tiktok": Platform(
        "tiktok", "TikTok", 61, 600, title_max=0, caption_max=2200, hashtags_max=5, sources="names",
        note="Caption links aren't clickable, so the caption names the sources; the full list is in publish.md. "
             "Creator Rewards pays only for videos over 1 minute, so this cut must run 61s+. "
             "Label AI-generated content where TikTok's rules require it.",
    ),
    "instagram": Platform(
        "instagram", "Instagram Reels", 1, 180, title_max=0, caption_max=2200, hashtags_max=5,
        sources="comment",
        note="Links in captions aren't clickable; put the source list in the first comment.",
    ),
    "linkedin": Platform(
        "linkedin", "LinkedIn", 3, 600, title_max=0, caption_max=3000, hashtags_max=3,
        note="Upload natively (not as a YouTube link). Open with the hook sentence; sources go in the post.",
    ),
}


def resolve_platforms(arg: str | None) -> list[Platform]:
    if not arg or arg == "all":
        return list(PLATFORMS.values())
    out = []
    for k in arg.split(","):
        k = k.strip().lower()
        if k not in PLATFORMS:
            raise SystemExit(f"unknown platform '{k}' (choose from {', '.join(PLATFORMS)})")
        out.append(PLATFORMS[k])
    return out


def apply_variant(ep: Episode, platform: str) -> Episode:
    """Return a copy of the episode with the platform's variant applied."""
    var = ep.variants.get(platform) or {}
    v = copy.deepcopy(ep)
    drop = set(var.get("drop_scenes") or [])
    unknown = drop - {s.id for s in v.scenes}
    if unknown:
        raise SpecError(f"variant {platform}: drop_scenes names unknown scenes {sorted(unknown)}")
    v.scenes = [s for s in v.scenes if s.id not in drop]
    for i, raw in enumerate(var.get("add_scenes") or []):
        raw = dict(raw)
        after = raw.pop("after", None)
        scene = parse_scene(raw, i, f"variant {platform}")
        ids = [s.id for s in v.scenes]
        if after is None:
            v.scenes.insert(len(v.scenes) - 1, scene)  # before the closing scene
        elif after in ids:
            v.scenes.insert(ids.index(after) + 1, scene)
        else:
            raise SpecError(f"variant {platform}: add_scenes 'after: {after}' is not a scene id")
    v.publish = {**ep.publish, **(var.get("publish") or {})}
    return v


def signature(ep: Episode) -> tuple:
    return tuple((s.id, s.type, s.say, repr(s.visual)) for s in ep.scenes)


# ------------------------------------------------------------ publish copy

def _tags(ep: Episode, p: Platform) -> list[str]:
    tags = [t.lstrip("#") for t in ep.publish.get("hashtags", [])]
    tags = [t for t in tags if t.lower() not in {x.lower() for x in p.extra_tags}]
    tags = list(p.extra_tags) + tags
    return ["#" + t for t in tags[: p.hashtags_max]]


def publish_copy(ep: Episode, p: Platform) -> dict:
    title = ep.publish.get("title", ep.title).strip()
    desc = " ".join(ep.publish.get("description", ep.hook_question).split())
    tags = " ".join(_tags(ep, p))
    src_lines = [f"- {s.publisher}: {s.title} {s.url}" for s in ep.sources.values()]
    sources = "Sources:\n" + "\n".join(src_lines)
    disclosure = "Narration is AI-generated. Figures are from the sources listed."

    names = "Sources: " + ", ".join(dict.fromkeys(s.publisher for s in ep.sources.values())) + "."

    first_comment = None
    if p.key == "linkedin":
        caption = f"{ep.hook_question}\n\n{desc}\n\n{sources}\n\n{tags}"
    elif p.sources == "full":
        caption = f"{desc}\n\n{tags}\n\n{sources}\n\n{disclosure}"
    elif p.sources == "names":
        caption = f"{desc}\n\n{names} {disclosure}\n\n{tags}"
    else:
        caption = f"{desc}\n\n{disclosure} Sources in the first comment.\n\n{tags}"
        first_comment = sources

    problems = []
    if p.title_max and len(title) > p.title_max:
        problems.append(f"title is {len(title)} chars (max {p.title_max})")
    if len(caption) > p.caption_max:
        problems.append(f"caption is {len(caption)} chars (max {p.caption_max})")
    return {"title": title if p.title_max else None, "caption": caption,
            "first_comment": first_comment, "problems": problems}


def write_platform_kit(ep: Episode, p: Platform, copy_: dict, duration: float, video: Path, out: Path):
    lines = [f"# {p.name} — {ep.title}", "",
             f"- **Video:** `{video.name}` ({duration:.1f}s)",
             f"- **Platform note:** {p.note}", ""]
    if copy_["title"]:
        lines += ["## Title", "", "```", copy_["title"], "```", ""]
    lines += ["## Caption" if p.key != "youtube" else "## Description", "", "```", copy_["caption"], "```", ""]
    if copy_["first_comment"]:
        lines += ["## First comment", "", "```", copy_["first_comment"], "```", ""]
    if p.sources == "names":
        lines += ["## Full source list (for replies / bio link)", ""]
        lines += [f"- {s.publisher}: {s.title} — {s.url}" for s in ep.sources.values()] + [""]
    lines += ["## Upload checklist", "",
              "- [ ] Thumbnail / cover frame: `thumbnail.png`",
              "- [ ] AI-content label set if the platform requires it",
              "- [ ] Captions: burned in; also upload `captions.srt` where supported (YouTube)" if p.key == "youtube"
              else "- [ ] Captions are burned in (no upload needed)",
              ""]
    out.write_text("\n".join(lines))


# ------------------------------------------------------------ release

def release(ep: Episode, platforms: list[Platform], out_root: Path, workers: int | None = None,
            renders_dir: Path | None = None) -> list[dict]:
    from .render import build  # heavy imports only when rendering

    out_root.mkdir(parents=True, exist_ok=True)
    rendered: dict[tuple, dict] = {}
    results = []
    for p in platforms:
        v = apply_variant(ep, p.key)
        c = publish_copy(v, p)
        if c["problems"]:
            raise SystemExit(f"{p.name}: " + "; ".join(c["problems"]))
        sig = signature(v)
        pdir = out_root / p.key
        pdir.mkdir(parents=True, exist_ok=True)
        video = pdir / f"{ep.id}.{p.key}.mp4"
        if sig in rendered:
            src = rendered[sig]
            info = src["info"]
            if not (p.min_s <= info["duration"] <= p.max_s):
                raise SystemExit(f"{p.name}: runtime {info['duration']:.1f}s is outside {p.min_s:g}–{p.max_s:g}s. "
                                 f"Add a '{p.key}' variant with add_scenes / drop_scenes.")
            shutil.copy(src["video"], video)
            for f in ("captions.srt", "thumbnail.png", "factcheck.md"):
                shutil.copy(src["dir"] / f, pdir / f)
            shared = src["platform"]
        else:
            info = build(v, pdir, workers=workers, limits=(p.min_s, p.max_s))
            (pdir / "final.mp4").replace(video)
            rendered[sig] = {"info": info, "dir": pdir, "video": video, "platform": p.key}
            shared = None
        # in renders/ keep one file per unique cut; shared platforms point at it
        upload = rendered[sig]["video"] if shared else video
        write_platform_kit(v, p, c, info["duration"], upload, pdir / "publish.md")
        if renders_dir:
            renders_dir.mkdir(parents=True, exist_ok=True)
            if not shared:
                shutil.copy(video, renders_dir / video.name)
            shutil.copy(pdir / "publish.md", renders_dir / f"{ep.id}.{p.key}.publish.md")
        results.append({"platform": p.name, "video": str(video), "duration": info["duration"],
                        "scenes": len(v.scenes), "shared_render_with": shared})
    _write_summary(ep, results, out_root / "release.md")
    return results


def _write_summary(ep: Episode, results: list[dict], path: Path):
    lines = [f"# Release: {ep.title}", "", "| Platform | Length | Scenes | Video | Render |", "|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['platform']} | {r['duration']:.1f}s | {r['scenes']} | `{Path(r['video']).name}` | "
                     f"{'shared with ' + r['shared_render_with'] if r['shared_render_with'] else 'own cut'} |")
    path.write_text("\n".join(lines) + "\n")
