"""Timeline assembly and final render (frames -> ffmpeg)."""
from __future__ import annotations

import json
import multiprocessing as mp
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw

from . import audio as audiomod
from .captions import Chunk, Word, chunk_words, draw_caption, srt, time_words
from .draw import (
    FPS, H, KICKER_Y, SOURCE_Y, W, Theme, draw_text, ease_out, fit_font, font, frame_bg, prog, rrect,
)
from .factcheck import check, report_markdown, resolve_visual
from .scenes import RENDERERS, SceneCtx
from .spec import Episode
from .tts import SR, narrate

LEAD_OUT = 0.6  # extra time on the last scene


@dataclass
class TimedScene:
    type: str
    visual: dict
    source_note: str
    start: float
    dur: float


@dataclass
class Timeline:
    scenes: list[TimedScene]
    chunks: list[Chunk]
    duration: float
    voice: np.ndarray


def build_timeline(ep: Episode) -> Timeline:
    voice = ep.voice.get("name", "af_heart")
    speed = float(ep.voice.get("speed", 1.05))
    parts, scenes, words = [], [], []
    t = 0.0
    for i, sc in enumerate(ep.scenes):
        na = narrate(sc.say, voice, speed)
        hold = sc.hold + (LEAD_OUT if i == len(ep.scenes) - 1 else 0)
        dur = na.duration + hold
        min_dur = float(sc.visual.get("min_duration", 0))
        if dur < min_dur:
            hold += min_dur - dur
            dur = min_dur
        for s in na.sentences:
            words += time_words(s.text, t + s.start, t + s.end)
        parts += [na.audio, np.zeros(int(hold * SR), np.float32)]
        scenes.append(TimedScene(sc.type, resolve_visual(sc.visual, ep), sc.source_note, t, dur))
        t += dur
    audio = np.concatenate(parts)
    total = len(audio) / SR
    return Timeline(scenes, chunk_words(words), total, audio)


# ------------------------------------------------------------ frames

_G: dict = {}


def _init(ep_values, theme_hex, kicker, timeline_meta, chunks):
    _G.update(values=ep_values, theme=Theme(theme_hex), kicker=kicker, scenes=timeline_meta,
              chunks=[Chunk([Word(*w) for w in c]) for c in chunks])


def _scene_at(t: float):
    for i, s in enumerate(_G["scenes"]):
        if s["start"] <= t < s["start"] + s["dur"]:
            return i, s
    return len(_G["scenes"]) - 1, _G["scenes"][-1]


def render_frame(fi: int) -> bytes:
    t = fi / FPS
    theme: Theme = _G["theme"]
    total = _G["scenes"][-1]["start"] + _G["scenes"][-1]["dur"]
    frame = frame_bg(theme, t)
    idx, s = _scene_at(t)
    lt = t - s["start"]

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer, "RGBA")
    ctx = SceneCtx(theme, _G["values"])
    RENDERERS[s["type"]](layer, ld, lt, s["dur"], s["visual"], ctx)

    # scene transition: slide-up + fade in, quick fade out
    a_in = ease_out(prog(lt, 0, 0.22)) if idx > 0 else 1.0
    a_out = 1 - prog(lt, s["dur"] - 0.12, 0.12) if idx < len(_G["scenes"]) - 1 else 1.0
    alpha = min(a_in, a_out)
    if alpha < 1:
        layer.putalpha(layer.getchannel("A").point(lambda x: int(x * alpha)))
    dy = int((1 - a_in) * 50)
    frame.alpha_composite(layer, (0, dy) if dy >= 0 else (0, 0))

    d = ImageDraw.Draw(frame, "RGBA")
    # top: kicker + progress bar
    if _G["kicker"]:
        fk = fit_font(_G["kicker"].upper(), W - 300, 38, "ExtraBold")
        draw_text(d, (W // 2, KICKER_Y), _G["kicker"].upper(), fk, theme.muted, anchor="mm")
    rrect(d, (84, KICKER_Y + 42, W - 84, KICKER_Y + 50), 4, fill=theme.panel)
    rrect(d, (84, KICKER_Y + 42, 84 + (W - 168) * min(1, t / total), KICKER_Y + 50), 4, fill=theme.accent)
    # captions
    draw_caption(d, _G["chunks"], t, theme)
    # source footnote (credibility, stays out of the bottom UI zone)
    if s.get("source_note"):
        fs = fit_font("Source: " + s["source_note"], W - 200, 30, "Medium")
        draw_text(d, (W // 2, SOURCE_Y), "Source: " + s["source_note"], fs, theme.muted, anchor="mm",
                  alpha=0.9 * prog(lt, 0.2, 0.3))
    return frame.convert("RGB").tobytes()


# ------------------------------------------------------------ build

def build(ep: Episode, out_dir: Path, workers: int | None = None, preview: bool = False,
          force: bool = False) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    rep = check(ep)
    (out_dir / "factcheck.md").write_text(report_markdown(ep, rep))
    if not rep.ok and not force:
        raise SystemExit("Fact-check FAILED — see " + str(out_dir / "factcheck.md") + "\n" + "\n".join(rep.errors))

    tl = build_timeline(ep)
    cuts = [s.start for s in tl.scenes[1:]]
    mixed = audiomod.mix(tl.voice, cuts, music=ep.style.get("music", True))
    wav = out_dir / "audio.wav"
    sf.write(wav, mixed, SR)
    sf.write(out_dir / "narration.wav", tl.voice, SR)
    (out_dir / "captions.srt").write_text(srt(tl.chunks))

    theme_hex = dict(Theme(ep.style.get("theme")).hex)
    meta = [dict(type=s.type, visual=s.visual, source_note=s.source_note, start=s.start, dur=s.dur)
            for s in tl.scenes]
    chunks = [[(w.text, w.start, w.end) for w in c.words] for c in tl.chunks]
    values = {k: f.value for k, f in ep.facts.items()}
    initargs = (values, theme_hex, ep.style.get("kicker", ""), meta, chunks)

    n_frames = int(np.ceil(tl.duration * FPS))
    scale = "540:960" if preview else f"{W}:{H}"
    out_mp4 = out_dir / ("preview.mp4" if preview else "final.mp4")
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-i", str(wav),
        "-vf", f"scale={scale}:flags=lanczos,format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast" if preview else "medium", "-crf", "28" if preview else "18",
        "-profile:v", "high", "-c:a", "aac", "-b:a", "192k",
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", "48000",
        "-movflags", "+faststart", "-shortest", str(out_mp4),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    step = 2 if preview else 1  # preview renders every other frame and doubles it
    workers = workers or max(1, mp.cpu_count())
    with mp.get_context("fork").Pool(workers, initializer=_init, initargs=initargs) as pool:
        for i, buf in enumerate(pool.imap(render_frame, range(0, n_frames, step), chunksize=8)):
            for _ in range(min(step, n_frames - i * step)):
                proc.stdin.write(buf)
    proc.stdin.close()
    if proc.wait() != 0:
        raise SystemExit("ffmpeg failed")

    # thumbnail: the hook scene, fully built
    _init(*initargs)
    hook_t = meta[0]["start"] + min(meta[0]["dur"] - 0.2, 1.6)
    thumb = Image.frombytes("RGB", (W, H), render_frame(int(hook_t * FPS)))
    thumb.save(out_dir / "thumbnail.png")
    _contact_sheet(initargs, meta, out_dir / "storyboard.png")

    write_publish_kit(ep, tl, out_dir)
    info = {"duration": round(tl.duration, 2), "frames": n_frames, "scenes": len(meta),
            "video": str(out_mp4), "factcheck": "PASS" if rep.ok else "FAIL (forced)"}
    (out_dir / "build.json").write_text(json.dumps(info, indent=2))
    wav.unlink(missing_ok=True)
    return info


def _contact_sheet(initargs, meta, path: Path):
    _init(*initargs)
    thumbs = []
    for s in meta:
        t = s["start"] + max(0.1, s["dur"] * 0.8)
        im = Image.frombytes("RGB", (W, H), render_frame(int(t * FPS))).resize((270, 480))
        thumbs.append(im)
    cols = min(5, len(thumbs))
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 280 + 10, rows * 490 + 10), (20, 20, 20))
    for i, im in enumerate(thumbs):
        r, c = divmod(i, cols)
        sheet.paste(im, (10 + c * 280, 10 + r * 490))
    sheet.save(path)


def write_publish_kit(ep: Episode, tl: Timeline, out_dir: Path):
    pub = ep.publish
    lines = [f"# {pub.get('title', ep.title)}", ""]
    lines += ["## Caption / description", "", pub.get("description", ep.hook_question).strip(), ""]
    tags = pub.get("hashtags", [])
    if tags:
        lines += [" ".join("#" + t.lstrip("#") for t in tags), ""]
    lines += ["## Sources", ""]
    for s in ep.sources.values():
        lines.append(f"- {s.publisher}: {s.title} — {s.url}")
    lines += ["", "## Script", ""]
    for sc in ep.scenes:
        lines.append(f"**[{sc.id}]** {sc.say}")
    lines += ["", f"_Runtime: {tl.duration:.1f}s · {len(ep.scenes)} scenes · voice {ep.voice.get('name', 'af_heart')} "
              "(AI narration; disclose as synthetic voice where the platform requires it)._", ""]
    (out_dir / "publish.md").write_text("\n".join(lines))


def ffprobe(path: Path) -> dict:
    if not shutil.which("ffprobe"):
        return {}
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "format=duration:stream=codec_name,width,height,r_frame_rate",
                          "-of", "json", str(path)], capture_output=True, text=True)
    return json.loads(out.stdout or "{}")
