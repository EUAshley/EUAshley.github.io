"""Drawing primitives: theme, fonts, easing, text layout."""
from __future__ import annotations

import math
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "assets" / "fonts"

W, H = 1080, 1920
FPS = 30

# Layout (safe zones for Shorts / Reels / TikTok: top UI ~200px, bottom UI ~420px, right rail ~140px)
MARGIN = 84
KICKER_Y = 190
STAGE = (MARGIN, 290, W - MARGIN, 1230)  # main visual box
CAPTION_Y = 1340
SOURCE_Y = 1492


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


DEFAULT_THEME = {
    "bg_top": "#0A0E13",
    "bg_bottom": "#121B26",
    "grid": "#1A2633",
    "text": "#F4F6F8",
    "muted": "#8795A4",
    "accent": "#2EE59D",   # money green
    "accent2": "#FFC247",  # amber
    "bad": "#FF5A5F",
    "panel": "#16212D",
}


class Theme:
    def __init__(self, overrides: dict | None = None):
        d = dict(DEFAULT_THEME)
        d.update(overrides or {})
        self.hex = d
        for k, v in d.items():
            setattr(self, k, hex_rgb(v))

    def color(self, name_or_hex: str | None, default: str = "accent"):
        if not name_or_hex:
            name_or_hex = default
        if name_or_hex.startswith("#"):
            return hex_rgb(name_or_hex)
        return getattr(self, name_or_hex)


# ------------------------------------------------------------ fonts

@lru_cache(maxsize=256)
def font(size: int, weight: str = "Bold") -> ImageFont.FreeTypeFont:
    """weight: Inter weight name (Regular..Black) or 'Display' for Anton."""
    size = max(8, int(size))
    if weight == "Display":
        return ImageFont.truetype(str(FONTS / "Anton-Regular.ttf"), size)
    f = ImageFont.truetype(str(FONTS / "Inter.ttf"), size)
    f.set_variation_by_name(weight)
    return f


def text_w(txt: str, f: ImageFont.FreeTypeFont) -> int:
    l, _, r, _ = f.getbbox(txt)
    return r - l


def fit_font(txt: str, max_w: int, size: int, weight: str = "Bold", min_size: int = 20) -> ImageFont.FreeTypeFont:
    while size > min_size and text_w(txt, font(size, weight)) > max_w:
        size -= 2
    return font(size, weight)


def wrap(txt: str, f: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    lines, cur = [], ""
    for word in txt.split():
        trial = (cur + " " + word).strip()
        if cur and text_w(trial, f) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def fit_wrapped(txt: str, max_w: int, max_h: int, size: int, weight: str = "Bold",
                line_gap: float = 1.12, min_size: int = 28):
    while True:
        f = font(size, weight)
        lines = wrap(txt, f, max_w)
        h = int(len(lines) * size * line_gap)
        if (h <= max_h and all(text_w(l, f) <= max_w for l in lines)) or size <= min_size:
            return f, lines, size
        size -= 4


def draw_text(d: ImageDraw.ImageDraw, xy, txt, f, fill, anchor="la", alpha: float = 1.0,
              stroke: int = 0, stroke_fill=(0, 0, 0)):
    if alpha <= 0:
        return
    fill = (*fill[:3], int(255 * min(1.0, alpha)))
    sf = (*stroke_fill[:3], int(255 * min(1.0, alpha)))
    d.text(xy, txt, font=f, fill=fill, anchor=anchor, stroke_width=stroke, stroke_fill=sf)


# ------------------------------------------------------------ easing

def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


def prog(t: float, start: float, dur: float) -> float:
    return clamp((t - start) / dur) if dur > 0 else float(t >= start)


def ease_out(x: float) -> float:
    return 1 - (1 - clamp(x)) ** 3


def ease_in_out(x: float) -> float:
    x = clamp(x)
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def ease_back(x: float, s: float = 1.6) -> float:
    x = clamp(x) - 1
    return 1 + x * x * ((s + 1) * x + s)


def lerp(a: float, b: float, x: float) -> float:
    return a + (b - a) * x


def mix(c1, c2, x: float):
    return tuple(int(lerp(a, b, clamp(x))) for a, b in zip(c1, c2))


# ------------------------------------------------------------ shapes

def rrect(d: ImageDraw.ImageDraw, box, r, fill=None, outline=None, width=1, alpha: float = 1.0):
    x0, y0, x1, y1 = box
    if x1 <= x0 or y1 <= y0:
        return
    r = int(min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    a = int(255 * clamp(alpha))
    d.rounded_rectangle(box, r, fill=(*fill[:3], a) if fill else None,
                        outline=(*outline[:3], a) if outline else None, width=width)


def glow(img: Image.Image, box, color, radius: int = 40, strength: float = 0.55):
    """Soft colored glow behind a box (drawn onto img in place)."""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    x0, y0, x1, y1 = box
    ld.rounded_rectangle((x0, y0, x1, y1), 30, fill=(*color[:3], int(255 * strength)))
    layer = layer.filter(ImageFilter.GaussianBlur(radius))
    img.alpha_composite(layer)


@lru_cache(maxsize=8)
def background(theme_key: tuple) -> Image.Image:
    theme = Theme(dict(theme_key))
    img = Image.new("RGBA", (W, H + 240), (0, 0, 0, 255))
    d = ImageDraw.Draw(img)
    for y in range(H + 240):
        d.line([(0, y), (W, y)], fill=(*mix(theme.bg_top, theme.bg_bottom, y / (H + 240)), 255))
    step = 120
    for x in range(0, W + 1, step):
        d.line([(x, 0), (x, H + 240)], fill=(*theme.grid, 255), width=1)
    for y in range(0, H + 240, step):
        d.line([(0, y), (W, y)], fill=(*theme.grid, 255), width=1)
    # vignette
    vig = Image.new("L", (W, H + 240), 0)
    vd = ImageDraw.Draw(vig)
    vd.ellipse((-300, -200, W + 300, H + 440), fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(220))
    dark = Image.new("RGBA", img.size, (*theme.bg_top, 255))
    return Image.composite(img, dark, vig)


def frame_bg(theme: Theme, t: float) -> Image.Image:
    bg = background(tuple(sorted(theme.hex.items())))
    off = int((t * 14) % 120)  # slow drift
    return bg.crop((0, off, W, off + H)).copy()


def split_emphasis(txt: str) -> list[tuple[str, bool]]:
    """'Costco *makes* money' -> [('Costco', False), ('makes', True), ('money', False)]"""
    out = []
    for tok in txt.split():
        emph = tok.startswith("*") or tok.endswith("*") or tok.rstrip(".,!?").endswith("*")
        clean = re.sub(r"\*", "", tok)
        out.append((clean, emph))
    return out


def sine_wobble(t: float, amp: float = 1.0, freq: float = 0.5) -> float:
    return amp * math.sin(2 * math.pi * freq * t)
