"""Auto-editor: turns raw screen-recording clips + an approved production
package into a finished vertical video (text-only, with music).

Layout (1080x1920 by default): a text band across the top, the screen
recording fitted below it, so on-screen text never covers a tap.

Timeline:
  HOOK     end of the result clip, hook text in the band
  PROBLEM  dimmed first frame, problem text centered
  STEP n   clip n, sped up if long (up to max_speedup), step text in the band
  RESULT   result clip, benefit text in the band
  CTA      frozen last frame, dimmed, CTA text centered

Text is drawn with Pillow onto transparent PNGs and composited by ffmpeg, so
no ffmpeg font support is needed. ffmpeg comes from the system PATH or the
bundled `imageio-ffmpeg` binary.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import config

VIDEO_EXTS = {".mov", ".mp4", ".m4v"}
MUSIC_EXTS = {".mp3", ".m4a", ".aac", ".wav"}

DEFAULTS = {
    "width": 1080, "height": 1920, "fps": 30,
    "text_band": 340, "bottom_margin": 110,
    "background": "#101014", "text_color": "#FFFFFF", "box_color": [0, 0, 0, 170],
    "font": None,
    "step_seconds": {"min": 2.5, "max": 5.0},
    "result_seconds": {"min": 3.0, "max": 6.0},
    "max_speedup": 3.0,
    "words_per_second": 3.2,
    "music_dir": "assets/music", "music_volume": 0.8,
}

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",   # macOS
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:/Windows/Fonts/arialbd.ttf",                        # Windows
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Linux
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


class VideoError(RuntimeError):
    pass


def settings(brand: dict) -> dict:
    cfg = {**DEFAULTS, **(brand.get("video") or {})}
    for key in ("step_seconds", "result_seconds"):
        cfg[key] = {**DEFAULTS[key], **(cfg.get(key) or {})}
    return cfg


# --- ffmpeg helpers -----------------------------------------------------------

def ffmpeg_exe() -> str:
    exe = config.env("ENGINE_FFMPEG") or shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
    except ImportError as e:
        raise VideoError("ffmpeg not found. Install it (e.g. `brew install ffmpeg`) or `pip install imageio-ffmpeg`.") from e
    return imageio_ffmpeg.get_ffmpeg_exe()


def _run(args: list[str]) -> str:
    proc = subprocess.run([ffmpeg_exe(), "-hide_banner", "-y", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise VideoError("ffmpeg failed:\n" + proc.stderr[-2000:])
    return proc.stderr


def probe_duration(path: Path) -> float:
    proc = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr)
    if not m:
        raise VideoError(f"Can't read duration of {path.name}")
    h, mnt, s = m.groups()
    return int(h) * 3600 + int(mnt) * 60 + float(s)


def extract_frame(clip: Path, out: Path, *, from_end: bool = False) -> Path:
    if from_end:
        _run(["-sseof", "-0.25", "-i", str(clip), "-frames:v", "1", "-update", "1", str(out)])
    else:
        _run(["-i", str(clip), "-frames:v", "1", str(out)])
    return out


# --- Text overlays ------------------------------------------------------------------

def _font(cfg: dict, size: int):
    from PIL import ImageFont

    for path in [cfg.get("font"), *FONT_CANDIDATES]:
        if path and Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def _wrap(text: str, font, max_width: int) -> list[str]:
    lines = []
    for para in text.splitlines() or [""]:
        line = ""
        for word in para.split():
            trial = f"{line} {word}".strip()
            if font.getlength(trial) <= max_width or not line:
                line = trial
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return [l for l in lines if l] or [""]


def text_overlay(out: Path, text: str, cfg: dict, *, position: str = "band", size: int = 64) -> Path:
    """Transparent full-frame PNG with `text` in a rounded box, either in the
    top band or centered in the frame. Shrinks the font until it fits."""
    from PIL import Image, ImageDraw

    W, H, band = cfg["width"], cfg["height"], cfg["text_band"]
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    text = " ".join(text.split()) if "\n" not in text else text
    if text.strip():
        pad, margin = 28, 50
        max_h = band - 30 if position == "band" else H * 0.6
        while True:
            font = _font(cfg, size)
            lines = _wrap(text, font, W - 2 * margin - 2 * pad)
            line_h = int(size * 1.22)
            if line_h * len(lines) + 2 * pad <= max_h or size <= 34:
                break
            size -= 3
        box_w = max(font.getlength(l) for l in lines) + 2 * pad
        box_h = line_h * len(lines) + 2 * pad
        x0 = (W - box_w) / 2
        y0 = max(15, (band - box_h) / 2) if position == "band" else (H - box_h) / 2
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([x0, y0, x0 + box_w, y0 + box_h], radius=28, fill=tuple(cfg["box_color"]))
        for i, line in enumerate(lines):
            lx = (W - font.getlength(line)) / 2
            draw.text((lx, y0 + pad + i * line_h), line, font=font, fill=cfg["text_color"])
    img.save(out)
    return out


# --- Planning (pure, testable without ffmpeg) -------------------------------------------

@dataclass
class Segment:
    kind: str  # hook | problem | step | result | cta
    text: str
    position: str  # band | center
    source: Path  # clip or (for stills) the clip to take a frame from
    still: str | None = None  # None (moving clip) | "first" | "last"
    start: float = 0.0
    src_seconds: float = 0.0
    speed: float = 1.0
    seconds: float = 0.0  # output duration


@dataclass
class Plan:
    segments: list[Segment]
    warnings: list[str] = field(default_factory=list)

    @property
    def seconds(self) -> float:
        return round(sum(s.seconds for s in self.segments), 2)


def read_seconds(text: str, cfg: dict) -> float:
    return round(1.0 + len(text.split()) / cfg["words_per_second"], 2)


def _fit(clip_seconds: float, text: str, bounds: dict, cfg: dict) -> tuple[float, float]:
    """(speed, output seconds) for a moving clip: long clips are sped up (to
    at most max_speedup), short ones are held on their last frame so the
    text can be read."""
    target = max(bounds["min"], read_seconds(text, cfg))
    target = max(target, min(clip_seconds, bounds["max"]))
    speed = min(max(clip_seconds / target, 1.0), cfg["max_speedup"])
    return round(speed, 3), round(max(clip_seconds / speed, target), 2)


def plan_video(texts: dict, steps: list[str], clips: list[tuple[Path, float]], cfg: dict) -> Plan:
    """texts: {hook, problem, result, cta}; steps: one on-screen line per step;
    clips: (path, seconds) in recording order: one per step, then the result."""
    warnings = []
    if not clips:
        raise VideoError("No clips found. Record one clip per step plus one of the result.")
    n = len(steps)
    if n and len(clips) < n:
        raise VideoError(f"Expected {n} step clip(s) + 1 result clip, found {len(clips)}.")
    if n and len(clips) == n:
        warnings.append("No separate result clip; reusing the last step clip for the hook and result.")
        step_clips, result = clips, clips[-1]
    else:
        step_clips, result = clips[:-1], clips[-1]
        if n and len(step_clips) > n:
            warnings.append(f"{len(step_clips) - n} extra clip(s) shown without step text.")
        if len(clips) == 1:
            step_clips = []
    step_texts = steps + [""] * (len(step_clips) - n)

    segs = []
    hook_secs = max(3.0, read_seconds(texts["hook"], cfg))
    r_path, r_len = result
    segs.append(Segment("hook", texts["hook"], "band", r_path, start=max(0.0, r_len - hook_secs - 0.3),
                        src_seconds=min(hook_secs, r_len), seconds=hook_secs))
    if texts.get("problem"):
        first = step_clips[0][0] if step_clips else r_path
        segs.append(Segment("problem", texts["problem"], "center", first, still="first",
                            seconds=max(3.0, read_seconds(texts["problem"], cfg))))
    for (path, length), text in zip(step_clips, step_texts):
        speed, secs = _fit(length, text, cfg["step_seconds"], cfg)
        segs.append(Segment("step", text, "band", path, src_seconds=length, speed=speed, seconds=secs))
    speed, secs = _fit(r_len, texts["result"], cfg["result_seconds"], cfg)
    segs.append(Segment("result", texts["result"], "band", r_path, src_seconds=r_len, speed=speed, seconds=secs))
    segs.append(Segment("cta", texts["cta"], "center", r_path, still="last",
                        seconds=max(2.5, read_seconds(texts["cta"], cfg))))
    plan = Plan(segs, warnings)
    if plan.seconds > 60:
        warnings.append(f"Video is {plan.seconds:.0f}s; consider fewer steps or shorter text.")
    return plan


# --- Rendering -------------------------------------------------------------------------

def _layout_filter(cfg: dict) -> str:
    W, H, band, bottom = cfg["width"], cfg["height"], cfg["text_band"], cfg["bottom_margin"]
    vh = H - band - bottom
    bg = cfg["background"].replace("#", "0x")
    return (f"scale=w={W}:h={vh}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:{band}+({vh}-ih)/2:color={bg},setsar=1")


def _encode_args(cfg: dict, seconds: float) -> list[str]:
    return ["-t", f"{seconds:.3f}", "-r", str(cfg["fps"]), "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "20", "-pix_fmt", "yuv420p", "-an"]


def _render_segment(seg: Segment, out: Path, tmp: Path, cfg: dict, idx: int) -> Path:
    size = 76 if seg.kind in ("hook", "cta") else 64
    overlay = text_overlay(tmp / f"text{idx}.png", seg.text, cfg, position=seg.position, size=size)
    layout = _layout_filter(cfg)
    if seg.still:
        frame = extract_frame(seg.source, tmp / f"frame{idx}.png", from_end=seg.still == "last")
        _run(["-loop", "1", "-t", f"{seg.seconds:.3f}", "-i", str(frame), "-loop", "1", "-i", str(overlay),
              "-filter_complex",
              f"[0:v]{layout},boxblur=18:2,eq=brightness=-0.28,fps={cfg['fps']}[b];[b][1:v]overlay=0:0,format=yuv420p[v]",
              "-map", "[v]", *_encode_args(cfg, seg.seconds), str(out)])
    else:
        moving = seg.src_seconds / seg.speed
        hold = max(0.0, seg.seconds - moving)
        _run(["-i", str(seg.source), "-loop", "1", "-i", str(overlay), "-filter_complex",
              f"[0:v]trim=start={seg.start:.3f}:duration={seg.src_seconds:.3f},"
              f"setpts=(PTS-STARTPTS)/{seg.speed},{layout},fps={cfg['fps']},"
              f"tpad=stop_mode=clone:stop_duration={hold + 0.1:.3f}[b];"
              f"[b][1:v]overlay=0:0,format=yuv420p[v]",
              "-map", "[v]", *_encode_args(cfg, seg.seconds), str(out)])
    return out


def render(plan: Plan, out: Path, cfg: dict, *, music: Path | None = None, cover_text: str = "") -> dict:
    """Render the plan to `out` (.mp4) plus a cover image next to it."""
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        parts = [_render_segment(seg, tmp / f"seg{i:02d}.mp4", tmp, cfg, i) for i, seg in enumerate(plan.segments)]
        listing = tmp / "list.txt"
        listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts))
        silent = tmp / "video.mp4"
        _run(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(silent)])
        total = plan.seconds
        if music:
            fade = min(1.5, total / 4)
            audio = ["-stream_loop", "-1", "-i", str(music), "-filter_complex",
                     f"[1:a]volume={cfg['music_volume']},afade=t=in:d=0.5,afade=t=out:st={total - fade:.2f}:d={fade:.2f}[a]",
                     "-map", "0:v", "-map", "[a]"]
        else:  # silent track: some platforms reject videos with no audio stream
            audio = ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-map", "0:v", "-map", "1:a"]
        _run(["-i", str(silent), *audio, "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
              "-t", f"{total:.3f}", "-movflags", "+faststart", str(out)])

        cover = _cover(plan, out.with_suffix(".jpg"), tmp, cfg, cover_text)
    return {"path": out, "cover": cover, "seconds": total}


def _cover(plan: Plan, out: Path, tmp: Path, cfg: dict, text: str) -> Path:
    """Cover image: the result clip's last frame (no overlays), fitted to the
    layout, slightly dimmed, with the cover text large and centered."""
    from PIL import Image, ImageEnhance

    W, H, band, bottom = cfg["width"], cfg["height"], cfg["text_band"], cfg["bottom_margin"]
    result = next(s for s in plan.segments if s.kind == "result")
    frame = Image.open(extract_frame(result.source, tmp / "cover_frame.png", from_end=True)).convert("RGB")
    frame.thumbnail((W, H - band - bottom))
    base = Image.new("RGB", (W, H), cfg["background"])
    base.paste(frame, ((W - frame.width) // 2, band + (H - band - bottom - frame.height) // 2))
    base = ImageEnhance.Brightness(base).enhance(0.75).convert("RGBA")
    overlay = Image.open(text_overlay(tmp / "cover_text.png", text, cfg, position="center", size=104))
    Image.alpha_composite(base, overlay).convert("RGB").save(out, quality=90)
    return out


def list_media(folder: Path, exts: set[str]) -> list[Path]:
    if not folder.exists():
        return []
    return sorted((p for p in folder.iterdir() if p.suffix.lower() in exts and not p.name.startswith(".")),
                  key=lambda p: p.name.lower())
