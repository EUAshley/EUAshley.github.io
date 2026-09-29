"""Animated scene renderers.

Each renderer draws one frame of a scene onto a transparent RGBA layer.
Signature: render(img, d, t, dur, v, ctx) where
  img/d  - the RGBA layer and its ImageDraw
  t      - seconds since the scene started, dur - scene length
  v      - the scene's visual config with "@fact" refs already resolved
  ctx    - SceneCtx (theme + fact values for "{fact:fmt}" templates)
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from PIL import Image, ImageDraw

from .draw import (
    STAGE, W, Theme, clamp, draw_text, ease_back, ease_in_out, ease_out, fit_font, fit_wrapped,
    font, glow, lerp, mix, prog, rrect, split_emphasis, text_w,
)
from .numbers import fill_template, format_value

X0, Y0, X1, Y1 = STAGE
SW, SH = X1 - X0, Y1 - Y0
CX = W // 2


@dataclass
class SceneCtx:
    theme: Theme
    values: dict[str, float]

    def txt(self, s) -> str:
        return fill_template(str(s), self.values) if s is not None else ""


# ------------------------------------------------------------ helpers

_FMT_RE = re.compile(r"^(-?\$?)([\d,]+)(?:\.(\d+))?([KMBT%]?)$")
_SUFFIX = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12, "": 1, "%": 0.01}


def counting(v: float, final: float, fmt: str | None) -> str:
    """Format an in-progress count using the final value's unit and precision."""
    final_s = format_value(final, fmt)
    m = _FMT_RE.match(final_s)
    if not m:
        return format_value(v, fmt)
    prefix, _, dec, suf = m.groups()
    d = len(dec or "")
    return f"{prefix}{v / _SUFFIX[suf]:,.{d}f}{suf}"


def palette(ctx: SceneCtx, i: int, color: str | None = None):
    if color:
        return ctx.theme.color(color)
    order = ["accent", "accent2", "muted", "bad", "text"]
    return ctx.theme.color(order[i % len(order)])


def draw_emph_lines(d, lines_tokens, f, y, ctx, reveal: float = 1.0, line_h: int | None = None,
                    base_color=None, emph_color=None, anchor_center=True):
    """Draw pre-wrapped lines of (word, emph) tokens with a word-by-word reveal."""
    base_color = base_color or ctx.theme.text
    emph_color = emph_color or ctx.theme.accent
    line_h = line_h or int(f.size * 1.14)
    total = sum(len(l) for l in lines_tokens) or 1
    k = 0
    space = text_w(" ", f)
    for li, toks in enumerate(lines_tokens):
        widths = [text_w(w, f) for w, _ in toks]
        lw = sum(widths) + space * (len(toks) - 1)
        x = CX - lw / 2 if anchor_center else X0
        for (word, emph), ww in zip(toks, widths):
            a = clamp(reveal * total - k) if reveal < 1 else 1.0
            dy = (1 - ease_out(a)) * 24
            draw_text(d, (x, y + li * line_h + dy), word, f, emph_color if emph else base_color, alpha=a)
            x += ww + space
            k += 1


def wrap_tokens(tokens, f, max_w):
    lines, cur, cur_w = [], [], 0
    space = text_w(" ", f)
    for tok in tokens:
        w = text_w(tok[0], f)
        if cur and cur_w + space + w > max_w:
            lines.append(cur)
            cur, cur_w = [tok], w
        else:
            cur_w = cur_w + (space if cur else 0) + w
            cur.append(tok)
    if cur:
        lines.append(cur)
    return lines


def fit_tokens(tokens, max_w, max_h, size, weight="Black", min_size=40, gap=1.14):
    while True:
        f = font(size, weight)
        lines = wrap_tokens(tokens, f, max_w)
        if (len(lines) * size * gap <= max_h and all(
                sum(text_w(w, f) for w, _ in l) + text_w(" ", f) * (len(l) - 1) <= max_w for l in lines)) \
                or size <= min_size:
            return f, lines
        size -= 4


# ------------------------------------------------------------ scenes

def hook(img, d, t, dur, v, ctx):
    """Big stacked headline. lines: [..] (use *word* or a leading '*' for accent), sub: str"""
    lines = [ctx.txt(l) for l in v.get("lines", [])]
    n = max(1, len(lines))
    max_line_h = min(250, int(SH * 0.78 / n))
    sizes, fonts = [], []
    for l in lines:
        f = fit_font(l.replace("*", ""), SW, max_line_h, "Display")
        fonts.append(f)
        sizes.append(f.size)
    total_h = sum(int(s * 1.02) for s in sizes)
    sub = ctx.txt(v.get("sub", ""))
    y = Y0 + (SH - total_h - (110 if sub else 0)) / 2
    for i, (l, f) in enumerate(zip(lines, fonts)):
        p = prog(t, 0.08 + i * 0.16, 0.42)
        s = ease_back(p)
        if p <= 0:
            y += int(f.size * 1.02)
            continue
        emph = l.startswith("*") or "*" in l
        clean = l.replace("*", "")
        size = max(10, int(f.size * lerp(0.6, 1.0, s)))
        ff = font(size, "Display")
        col = ctx.theme.accent if emph else ctx.theme.text
        if emph and p >= 1:
            wob = 1 + 0.015 * math.sin(t * 5)
            ff = font(int(f.size * wob), "Display")
        draw_text(d, (CX, y + f.size * 0.5), clean, ff, col, anchor="mm", alpha=clamp(p * 2.5))
        y += int(f.size * 1.02)
    if sub:
        a = prog(t, 0.2 + n * 0.16, 0.4)
        fs = fit_font(sub, SW, 54, "SemiBold")
        draw_text(d, (CX, y + 60 + (1 - ease_out(a)) * 20), sub, fs, ctx.theme.muted, anchor="mm", alpha=a)


def counter(img, d, t, dur, v, ctx):
    """Big number counting up. value, format, label, sub, full (bool), count_time"""
    final = float(v["value"])
    fmt = v.get("format", "money")
    start = float(v.get("from", 0))
    ct = float(v.get("count_time", min(1.6, dur * 0.55)))
    p = ease_out(prog(t, 0.15, ct))
    cur = lerp(start, final, p)
    label = ctx.txt(v.get("label", ""))
    sub = ctx.txt(v.get("sub", ""))
    color = ctx.theme.color(v.get("color"), "accent")

    cy = Y0 + SH * 0.46
    if label:
        fl = fit_font(label.upper(), SW, 64, "ExtraBold")
        draw_text(d, (CX, cy - 250), label.upper(), fl, ctx.theme.text, anchor="mm", alpha=prog(t, 0, 0.3))
    big = counting(cur, final, fmt)
    fb = fit_font(counting(final, final, fmt), SW, 300, "Display")
    pulse = 1 + 0.06 * math.sin(math.pi * prog(t, 0.15 + ct, 0.35))
    fb2 = font(int(fb.size * pulse), "Display")
    if p >= 0.999:
        bw = text_w(big, fb2)
        glow(img, (CX - bw / 2, cy - fb.size * 0.3, CX + bw / 2, cy + fb.size * 0.3), color, 60, 0.35)
    draw_text(d, (CX, cy), big, fb2, color, anchor="mm", alpha=prog(t, 0, 0.2))
    # underline sweep
    lw = ease_in_out(prog(t, 0.2, ct)) * min(SW, text_w(counting(final, final, fmt), fb) + 40)
    rrect(d, (CX - lw / 2, cy + fb.size * 0.52, CX + lw / 2, cy + fb.size * 0.52 + 10), 5, fill=color)
    if v.get("full"):
        full = f"${cur:,.0f}" if fmt.startswith("money") else f"{cur:,.0f}"
        ff = fit_font(f"${final:,.0f}", SW, 58, "SemiBold")
        draw_text(d, (CX, cy + fb.size * 0.52 + 80), full, ff, ctx.theme.muted, anchor="mm", alpha=prog(t, 0.1, 0.3))
    if sub:
        a = prog(t, 0.2 + ct * 0.6, 0.4)
        f, lines, size = fit_wrapped(sub, SW, 200, 56, "SemiBold")
        yy = cy + fb.size * 0.52 + (170 if v.get("full") else 110)
        for i, l in enumerate(lines):
            draw_text(d, (CX, yy + i * size * 1.15), l, f, ctx.theme.text, anchor="mm", alpha=a)


def bars(img, d, t, dur, v, ctx):
    """Bar comparison. items: [{label, value, color, tag}], format, title, callout, orient"""
    items = v.get("items", [])
    fmt = v.get("format", "money")
    title = ctx.txt(v.get("title", ""))
    orient = v.get("orient", "vertical" if len(items) <= 4 else "horizontal")
    mx = max(float(i["value"]) for i in items) or 1
    top = Y0
    if title:
        f, lines, size = fit_wrapped(title, SW, 170, 66, "ExtraBold")
        for i, l in enumerate(lines):
            draw_text(d, (CX, top + 40 + i * size * 1.1), l, f, ctx.theme.text, anchor="mm", alpha=prog(t, 0, 0.3))
        top += 60 + len(lines) * size * 1.1
    n = len(items)
    callout_h = 130 if v.get("callout") else 0
    if orient == "vertical":
        base = Y1 - 110 - callout_h
        max_h = base - top - 130
        slot = SW / n
        bw = min(260, slot * 0.62)
        for i, it in enumerate(items):
            p = ease_out(prog(t, 0.25 + i * 0.35, 0.9))
            val = float(it["value"])
            h = max(8, max_h * val / mx) * p
            cx = X0 + slot * (i + 0.5)
            col = palette(ctx, i, it.get("color"))
            rrect(d, (cx - bw / 2, base - h, cx + bw / 2, base), 18, fill=col, alpha=clamp(p * 3))
            vs = counting(val * p, val, it.get("format", fmt))
            fv = fit_font(counting(val, val, it.get("format", fmt)), slot - 16, 84, "Display")
            draw_text(d, (cx, base - h - 18), vs, fv, col, anchor="md", alpha=clamp(p * 3))
            fl = fit_font(ctx.txt(it.get("label", "")), slot - 10, 46, "Bold")
            draw_text(d, (cx, base + 26), ctx.txt(it.get("label", "")), fl, ctx.theme.text, anchor="ma",
                      alpha=clamp(p * 3))
            if it.get("tag"):
                ft = fit_font(ctx.txt(it["tag"]), slot - 10, 36, "SemiBold")
                draw_text(d, (cx, base + 82), ctx.txt(it["tag"]), ft, ctx.theme.muted, anchor="ma",
                          alpha=clamp(p * 3))
    else:
        row = min(130, (Y1 - top - 20 - callout_h) / n)
        lab_w = 300
        max_w = SW - lab_w - 20
        for i, it in enumerate(items):
            p = ease_out(prog(t, 0.2 + i * 0.18, 0.8))
            val = float(it["value"])
            y = top + i * row + row * 0.5
            col = palette(ctx, i, it.get("color"))
            fl = fit_font(ctx.txt(it.get("label", "")), lab_w - 10, 42, "Bold")
            draw_text(d, (X0 + lab_w - 16, y), ctx.txt(it.get("label", "")), fl, ctx.theme.text, anchor="rm",
                      alpha=clamp(p * 3))
            w_ = max(8, max_w * val / mx) * p
            rrect(d, (X0 + lab_w, y - row * 0.32, X0 + lab_w + w_, y + row * 0.32), 12, fill=col, alpha=clamp(p * 3))
            vs = counting(val * p, val, it.get("format", fmt))
            fv = font(int(row * 0.36), "ExtraBold")
            inside = w_ > text_w(vs, fv) + 40
            draw_text(d, (X0 + lab_w + (w_ - 16 if inside else w_ + 14), y), vs, fv,
                      ctx.theme.bg_top if inside else col, anchor="rm" if inside else "lm", alpha=clamp(p * 3))
    callout = ctx.txt(v.get("callout", ""))
    if callout:
        a = ease_back(prog(t, 0.6 + n * 0.35, 0.45))
        f = fit_font(callout, SW - 80, 60, "Black")
        cw = text_w(callout, f) + 64
        yb = Y1 - 10
        rrect(d, (CX - cw / 2, yb - 86, CX + cw / 2, yb), 43, fill=ctx.theme.accent2, alpha=clamp(a))
        draw_text(d, (CX, yb - 43), callout, f, ctx.theme.bg_top, anchor="mm", alpha=clamp(a))


def donut(img, d, t, dur, v, ctx):
    """Donut breakdown. segments: [{label, value, color}], center, center_label, legend_format"""
    segs = v.get("segments", [])
    total = sum(float(s["value"]) for s in segs) or 1
    r_out, r_in = 330, 205
    cy = Y0 + 20 + r_out
    box = (CX - r_out, cy - r_out, CX + r_out, cy + r_out)
    p = ease_in_out(prog(t, 0.2, 1.1))
    # track
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.ellipse(box, fill=(*ctx.theme.panel, 255))
    ang = -90.0
    for i, s in enumerate(segs):
        sweep = 360 * float(s["value"]) / total * p
        if sweep > 0.2:
            ld.pieslice(box, ang, ang + sweep, fill=(*palette(ctx, i, s.get("color")), 255))
        ang += sweep
    # ImageDraw writes pixels without blending, so this punches a transparent hole
    ld.ellipse((CX - r_in, cy - r_in, CX + r_in, cy + r_in), fill=(0, 0, 0, 0))
    a_in = prog(t, 0, 0.3)
    if a_in < 1:
        layer.putalpha(layer.getchannel("A").point(lambda x: int(x * a_in)))
    img.alpha_composite(layer)
    center = ctx.txt(v.get("center", ""))
    if center:
        cp = ease_back(prog(t, 0.9, 0.5))
        fc = fit_font(center, r_in * 1.6, int(170 * max(0.3, cp)), "Display")
        draw_text(d, (CX, cy - 18), center, fc, palette(ctx, 0, segs[0].get("color") if segs else None),
                  anchor="mm", alpha=clamp(cp * 2))
        cl = ctx.txt(v.get("center_label", ""))
        if cl:
            fcl = fit_font(cl.upper(), r_in * 1.5, 38, "Bold")
            draw_text(d, (CX, cy + 78), cl.upper(), fcl, ctx.theme.muted, anchor="mm", alpha=clamp(cp * 2))
    # legend
    ly = cy + r_out + 70
    lf = v.get("legend_format", "money")
    for i, s in enumerate(segs):
        a = prog(t, 0.5 + i * 0.2, 0.4)
        col = palette(ctx, i, s.get("color"))
        y = ly + i * 92
        rrect(d, (X0 + 20, y - 20, X0 + 60, y + 20), 10, fill=col, alpha=a)
        lab = ctx.txt(s.get("label", ""))
        val = format_value(float(s["value"]), lf) if lf else ""
        fl = fit_font(lab, SW - 360, 48, "Bold")
        draw_text(d, (X0 + 84, y), lab, fl, ctx.theme.text, anchor="lm", alpha=a)
        if val:
            draw_text(d, (X1 - 10, y), val, font(52, "ExtraBold"), col, anchor="rm", alpha=a)


def grid(img, d, t, dur, v, ctx):
    """Unit grid (e.g. 100 dollar coins, N lit). total, lit, cols, title, icon, lit_label"""
    total = int(v.get("total", 100))
    lit = float(v["lit"])
    cols = int(v.get("cols", 10))
    rows = math.ceil(total / cols)
    title = ctx.txt(v.get("title", ""))
    top = Y0
    if title:
        f, lines, size = fit_wrapped(title, SW, 130, 58, "ExtraBold")
        for i, l in enumerate(lines):
            draw_text(d, (CX, top + 30 + i * size * 1.1), l, f, ctx.theme.text, anchor="mm", alpha=prog(t, 0, 0.3))
        top += 30 + len(lines) * size * 1.1
    has_label = bool(v.get("lit_label"))
    cell = min(SW / cols, (Y1 + 40 - top - (120 if has_label else 0)) / rows)
    gw = cell * cols
    gx = CX - gw / 2
    r = cell * 0.42
    icon = v.get("icon", "$")
    fi = font(int(r * 1.15), "Black")
    fill_start = 0.25 + 0.7
    for k in range(total):
        rr, cc = divmod(k, cols)
        ap = prog(t, 0.1 + (rr + cc) * 0.03, 0.25)
        if ap <= 0:
            continue
        x = gx + cc * cell + cell / 2
        y = top + rr * cell + cell / 2
        rad = r * ease_back(ap)
        amount = clamp(lit - k)
        if amount < 0.1:  # ignore slivers so the grid reads as whole units
            amount = 0.0
        lp = ease_out(prog(t, fill_start + k * 0.06, 0.3)) * amount
        base = ctx.theme.panel
        d.ellipse((x - rad, y - rad, x + rad, y + rad), fill=(*base, 255))
        if lp > 0:
            if amount >= 1:
                rad2 = rad * (1 + 0.12 * math.sin(math.pi * prog(t, fill_start + k * 0.06, 0.3)))
                d.ellipse((x - rad2, y - rad2, x + rad2, y + rad2), fill=(*ctx.theme.accent, int(255 * lp)))
            else:
                d.pieslice((x - rad, y - rad, x + rad, y + rad), -90, -90 + 360 * lp, fill=(*ctx.theme.accent, 255))
        col = ctx.theme.bg_top if (amount >= 1 and lp > 0.5) else ctx.theme.muted
        draw_text(d, (x, y + 2), icon, fi, col, anchor="mm", alpha=ap)
    lab = ctx.txt(v.get("lit_label", ""))
    if lab:
        a = ease_back(prog(t, fill_start + lit * 0.06 + 0.3, 0.45))
        f = fit_font(lab, SW - 60, 64, "Black")
        cw = text_w(lab, f) + 70
        yb = top + rows * cell + 16
        rrect(d, (CX - cw / 2, yb, CX + cw / 2, yb + 96), 48, fill=ctx.theme.accent, alpha=clamp(a))
        draw_text(d, (CX, yb + 48), lab, f, ctx.theme.bg_top, anchor="mm", alpha=clamp(a))


def line(img, d, t, dur, v, ctx):
    """Line chart over time. points: [[label, value], ...], format, title, end_label"""
    pts = [(str(p[0]), float(p[1])) for p in v.get("points", [])]
    fmt = v.get("format", "money")
    title = ctx.txt(v.get("title", ""))
    top = Y0
    if title:
        f, lines, size = fit_wrapped(title, SW, 170, 62, "ExtraBold")
        for i, l in enumerate(lines):
            draw_text(d, (CX, top + 36 + i * size * 1.1), l, f, ctx.theme.text, anchor="mm", alpha=prog(t, 0, 0.3))
        top += 60 + len(lines) * size * 1.1
    px0, px1 = X0 + 20, X1 - 60
    py0, py1 = top + 120, Y1 - 120
    vals = [p[1] for p in pts]
    lo = min(0.0, min(vals))
    hi = max(vals) * 1.05 or 1
    for g in range(5):
        gy = py1 - (py1 - py0) * g / 4
        d.line([(px0, gy), (px1, gy)], fill=(*ctx.theme.grid, 255), width=2)
    n = len(pts)
    xy = [(px0 + (px1 - px0) * i / max(1, n - 1), py1 - (py1 - py0) * (val - lo) / (hi - lo))
          for i, (_, val) in enumerate(pts)]
    p = ease_in_out(prog(t, 0.2, max(1.2, dur * 0.55)))
    upto = p * (n - 1)
    k = int(upto)
    shown = xy[:k + 1]
    if k < n - 1:
        fr = upto - k
        (ax, ay), (bx, by) = xy[k], xy[k + 1]
        shown.append((lerp(ax, bx, fr), lerp(ay, by, fr)))
    col = ctx.theme.color(v.get("color"), "accent")
    if len(shown) > 1:
        area = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(area).polygon(shown + [(shown[-1][0], py1), (shown[0][0], py1)], fill=(*col, 50))
        img.alpha_composite(area)
        d.line(shown, fill=(*col, 255), width=10, joint="curve")
    hx, hy = shown[-1]
    d.ellipse((hx - 16, hy - 16, hx + 16, hy + 16), fill=(*col, 255))
    cur_val = lerp(pts[min(k, n - 1)][1], pts[min(k + 1, n - 1)][1], upto - k) if n > 1 else vals[0]
    fv = font(72, "Display")
    lab = counting(cur_val, vals[-1], fmt)
    draw_text(d, (min(hx, px1 - text_w(lab, fv) / 2), hy - 36), lab, fv, col, anchor="md")
    fx = font(40, "Bold")
    draw_text(d, (px0, py1 + 30), pts[0][0], fx, ctx.theme.muted, anchor="la")
    draw_text(d, (px1, py1 + 30), pts[-1][0], fx, ctx.theme.muted, anchor="ra", alpha=prog(t, 0.2 + max(1.2, dur * 0.55), 0.3))
    el = ctx.txt(v.get("end_label", ""))
    if el:
        a = prog(t, 0.3 + max(1.2, dur * 0.55), 0.4)
        f = fit_font(el, SW, 54, "Bold")
        draw_text(d, (CX, Y1 - 20), el, f, ctx.theme.text, anchor="md", alpha=a)


def quote(img, d, t, dur, v, ctx):
    """Pull quote. text (*emphasis*), by, note, tag (price-tag chip)"""
    tokens = split_emphasis(ctx.txt(v.get("text", "")))
    tag = ctx.txt(v.get("tag", ""))
    top = Y0 + (190 if tag else 60)
    if tag:
        a = ease_back(prog(t, 0.05, 0.45))
        f = font(int(120 * max(0.2, a)), "Display")
        tw = text_w(tag, f) + 130
        tx = CX - tw / 2
        rrect(d, (tx, Y0, tx + tw, Y0 + 160), 26, fill=ctx.theme.accent2, alpha=clamp(a))
        d.ellipse((tx + 22, Y0 + 68, tx + 46, Y0 + 92), fill=(*ctx.theme.bg_top, int(255 * clamp(a))))
        draw_text(d, (tx + 70 + (tw - 90) / 2, Y0 + 82), tag, f, ctx.theme.bg_top, anchor="mm", alpha=clamp(a))
    draw_text(d, (X0 - 6, top - 10), "“", font(260, "Black"), ctx.theme.accent, alpha=prog(t, 0.1, 0.3))
    f, lines = fit_tokens(tokens, SW, Y1 - top - 330, 92, "Black")
    reveal = prog(t, 0.25, max(0.8, min(dur * 0.55, 2.4)))
    draw_emph_lines(d, lines, f, top + 170, ctx, reveal=reveal if reveal < 1 else 1.0)
    yb = top + 170 + len(lines) * f.size * 1.14 + 40
    by = ctx.txt(v.get("by", ""))
    if by:
        a = prog(t, 0.6, 0.4)
        rrect(d, (CX - 40, yb, CX + 40, yb + 8), 4, fill=ctx.theme.accent, alpha=a)
        fb = fit_font("— " + by, SW, 48, "Bold")
        draw_text(d, (CX, yb + 40), "— " + by, fb, ctx.theme.text, anchor="ma", alpha=a)
        note = ctx.txt(v.get("note", ""))
        if note:
            fn = fit_font(note, SW, 38, "Medium")
            draw_text(d, (CX, yb + 110), note, fn, ctx.theme.muted, anchor="ma", alpha=a)


def compare(img, d, t, dur, v, ctx):
    """Two stacked cards with VS. top/bottom: {title, value, sub, color}"""
    cards = [v.get("top", {}), v.get("bottom", {})]
    ch = (SH - 120) / 2
    for i, c in enumerate(cards):
        p = ease_out(prog(t, 0.1 + i * 0.45, 0.5))
        y0 = Y0 + i * (ch + 120) + (1 - p) * 60
        col = palette(ctx, i, c.get("color"))
        rrect(d, (X0, y0, X1, y0 + ch), 36, fill=ctx.theme.panel, alpha=p)
        rrect(d, (X0, y0, X0 + 14, y0 + ch), 7, fill=col, alpha=p)
        ft = fit_font(ctx.txt(c.get("title", "")).upper(), SW - 100, 50, "ExtraBold")
        draw_text(d, (CX, y0 + 70), ctx.txt(c.get("title", "")).upper(), ft, ctx.theme.muted, anchor="mm", alpha=p)
        val = ctx.txt(c.get("value", ""))
        fv = fit_font(val, SW - 100, 190, "Display")
        draw_text(d, (CX, y0 + ch * 0.52), val, fv, col, anchor="mm", alpha=p)
        sub = ctx.txt(c.get("sub", ""))
        if sub:
            f, lines, size = fit_wrapped(sub, SW - 100, 110, 44, "SemiBold")
            for k, l in enumerate(lines):
                draw_text(d, (CX, y0 + ch - 70 - (len(lines) - 1 - k) * size * 1.12), l, f, ctx.theme.text,
                          anchor="mm", alpha=p)
    a = ease_back(prog(t, 0.45, 0.4))
    vy = Y0 + ch + 60
    r = 62 * a
    if r > 1:
        d.ellipse((CX - r, vy - r, CX + r, vy + r), fill=(*ctx.theme.accent2, 255))
        draw_text(d, (CX, vy + 2), "VS", font(max(10, int(56 * a)), "Black"), ctx.theme.bg_top, anchor="mm")


def statement(img, d, t, dur, v, ctx):
    """Kinetic text. text (*emphasis*), sub"""
    tokens = split_emphasis(ctx.txt(v.get("text", "")))
    sub = ctx.txt(v.get("sub", ""))
    area = SH - int(v.get("bottom_pad", 0))
    f, lines = fit_tokens(tokens, SW, area - (200 if sub else 60), int(v.get("size", 118)), "Black")
    block_h = len(lines) * f.size * 1.14
    fs, sl, ssize = fit_wrapped(sub, SW, 150, 52, "SemiBold") if sub else (None, [], 0)
    sub_h = (40 + len(sl) * ssize * 1.15) if sub else 0
    y = Y0 + (area - block_h - sub_h) / 2
    reveal = prog(t, 0.05, float(v.get("reveal", min(1.4, dur * 0.5))))
    draw_emph_lines(d, lines, f, y, ctx, reveal=reveal if reveal < 1 else 1.0)
    if sub:
        a = prog(t, 0.4, 0.4)
        for i, l in enumerate(sl):
            draw_text(d, (CX, y + block_h + 40 + ssize * 0.6 + i * ssize * 1.15), l, fs, ctx.theme.muted,
                      anchor="mm", alpha=a)


def end(img, d, t, dur, v, ctx):
    """Closing card. text (*emphasis*), sub, cta"""
    statement(img, d, t, dur, {"text": v.get("text", ""), "sub": v.get("sub", ""), "size": 104,
                                  "bottom_pad": 150}, ctx)
    cta = ctx.txt(v.get("cta", "Follow for more money math"))
    a = ease_back(prog(t, 0.8, 0.5))
    f = font(46, "ExtraBold")
    cw = text_w(cta, f) + 80
    yb = Y1 - 40
    rrect(d, (CX - cw / 2, yb - 100, CX + cw / 2, yb), 50, outline=ctx.theme.accent, width=5, alpha=clamp(a))
    draw_text(d, (CX, yb - 50), cta, f, ctx.theme.accent, anchor="mm", alpha=clamp(a))


# ------------------------------------------------------------ language scenes

def mark(v, key, default: float) -> float:
    """Resolve a timing field: an int = start of that narration sentence (0-based), a float = seconds."""
    val = v.get(key)
    marks = v.get("_marks") or []
    if isinstance(val, bool) or val is None:
        return default
    if isinstance(val, int):
        return marks[val] if -len(marks) <= val < len(marks) else default
    return float(val)


def chip(d, ctx, text, cx, y, alpha, color=None, size=40):
    f = font(size, "ExtraBold")
    w = text_w(text, f) + 56
    col = color or ctx.theme.accent
    rrect(d, (cx - w / 2, y, cx + w / 2, y + size * 1.9), size, fill=col, alpha=alpha)
    draw_text(d, (cx, y + size * 0.95), text, f, ctx.theme.bg_top, anchor="mm", alpha=alpha)


def phrase(img, d, t, dur, v, ctx):
    """Foreign phrase card. label, text (*key word*), meaning, gloss; meaning_at = sentence index/seconds"""
    label = ctx.txt(v.get("label", ""))
    tokens = split_emphasis(ctx.txt(v.get("text", "")))
    meaning = ctx.txt(v.get("meaning", ""))
    gloss = ctx.txt(v.get("gloss", ""))
    f, lines = fit_tokens(tokens, SW, 380, int(v.get("size", 128)), "Black")
    block = len(lines) * f.size * 1.14
    fm, ml, msize = fit_wrapped(meaning, SW, 150, 62, "SemiBold") if meaning else (None, [], 0)
    fg, gl, gsize = fit_wrapped(gloss, SW - 80, 150, 40, "Medium") if gloss else (None, [], 0)
    total = (110 if label else 0) + block + (60 + len(ml) * msize * 1.15 if meaning else 0) \
        + (70 + len(gl) * gsize * 1.2 + 50 if gloss else 0)
    y = Y0 + max(0, (SH - total) / 2)
    if label:
        chip(d, ctx, label.upper(), CX, y, ease_out(prog(t, 0, 0.3)))
        y += 110
    reveal = prog(t, 0.1, max(0.5, min(1.0, dur * 0.3)))
    draw_emph_lines(d, lines, f, y, ctx, reveal=reveal if reveal < 1 else 1.0,
                    base_color=ctx.theme.text, emph_color=ctx.theme.accent)
    y += block + 30
    t_m = mark(v, "meaning_at", 0.9)
    a = ease_out(prog(t, t_m, 0.35))
    if meaning:
        rrect(d, (CX - 50 * a, y, CX + 50 * a, y + 6), 3, fill=ctx.theme.muted, alpha=a)
        y += 30
        for i, l in enumerate(ml):
            draw_text(d, (CX, y + msize * 0.6 + i * msize * 1.15 + (1 - a) * 20), l, fm, ctx.theme.text,
                      anchor="mm", alpha=a)
        y += len(ml) * msize * 1.15
    if gloss:
        ag = ease_out(prog(t, t_m + 0.4, 0.35))
        y += 40
        h = len(gl) * gsize * 1.2 + 40
        rrect(d, (X0 + 10, y, X1 - 10, y + h), 24, fill=ctx.theme.panel, alpha=ag)
        for i, l in enumerate(gl):
            draw_text(d, (CX, y + 20 + gsize * 0.6 + i * gsize * 1.2), l, fg, ctx.theme.muted, anchor="mm", alpha=ag)


def list_(img, d, t, dur, v, ctx):
    """Vocab / rule list. title, items [{text, meaning}]; items appear at narration sentences from sync_from"""
    items = v.get("items", [])
    title = ctx.txt(v.get("title", ""))
    n = max(1, len(items))
    gap = 22
    title_h = 0
    if title:
        f, lines, size = fit_wrapped(title, SW, 130, 60, "ExtraBold")
        title_h = 40 + len(lines) * size * 1.1
    row = min(230, (SH - title_h - gap * (n - 1)) / n)
    block = title_h + row * n + gap * (n - 1)
    top = Y0 + max(0, (SH - block) / 2 - 40)  # centre title + rows
    if title:
        for i, l in enumerate(lines):
            draw_text(d, (CX, top + 30 + i * size * 1.1), l, f, ctx.theme.text, anchor="mm", alpha=prog(t, 0, 0.3))
        top += title_h
    sync = v.get("sync_from", 0)
    marks = v.get("_marks") or []
    starts = []
    for i in range(n):
        at = items[i].get("at") if i < len(items) else None
        k = at if isinstance(at, int) else (sync + i if isinstance(sync, int) else None)
        starts.append(marks[k] if k is not None and k < len(marks) else 0.3 + 0.5 * i)
    current = max([i for i, st in enumerate(starts) if t >= st] or [-1])
    for i, it in enumerate(items):
        a = ease_out(prog(t, starts[i], 0.35))
        if a <= 0:
            continue
        y0 = top + i * (row + gap) + (1 - a) * 30
        active = i == current
        rrect(d, (X0, y0, X1, y0 + row), 28, fill=ctx.theme.panel, alpha=a)
        if active:
            rrect(d, (X0, y0, X1, y0 + row), 28, outline=ctx.theme.accent, width=5, alpha=a)
        tokens = split_emphasis(ctx.txt(it.get("text", "")))
        ft, tl = fit_tokens(tokens, SW - 80, row * 0.5, int(row * 0.36), "Black", min_size=30)
        draw_emph_lines(d, tl[:1], ft, y0 + row * 0.16, ctx, base_color=ctx.theme.accent,
                        emph_color=ctx.theme.accent2)
        mean = ctx.txt(it.get("meaning", ""))
        if mean:
            fm = fit_font(mean, SW - 80, int(row * 0.2), "SemiBold")
            draw_text(d, (CX, y0 + row * 0.74), mean, fm, ctx.theme.text if active else ctx.theme.muted,
                      anchor="mm", alpha=a)


def _check(d, cx, cy, s, color):
    d.line([(cx - s * 0.5, cy), (cx - s * 0.15, cy + s * 0.35), (cx + s * 0.55, cy - s * 0.4)],
           fill=(*color, 255), width=max(4, int(s * 0.18)), joint="curve")


def quiz(img, d, t, dur, v, ctx):
    """Quiz. prompt, question (use ___ for the blank), options [..], answer (index), meaning,
    reveal (sentence index/seconds, default: last sentence), countdown (seconds before reveal)"""
    prompt = ctx.txt(v.get("prompt", ""))
    question = ctx.txt(v.get("question", ""))
    options = [ctx.txt(o) for o in v.get("options", [])]
    ans = int(v.get("answer", 0))
    t_rev = mark(v, "reveal", -1.0)
    if t_rev < 0:
        marks = v.get("_marks") or []
        t_rev = marks[-1] if marks else dur * 0.6
    cd = float(v.get("countdown", 2.0))
    revealed = t >= t_rev
    ra = ease_back(prog(t, t_rev, 0.4))

    chip(d, ctx, v.get("label", "QUICK QUIZ"), CX, Y0, ease_out(prog(t, 0, 0.3)), color=ctx.theme.accent2)
    y = Y0 + 130
    if prompt:
        fp, pl, psize = fit_wrapped(prompt, SW, 140, 56, "SemiBold")
        for i, l in enumerate(pl):
            draw_text(d, (CX, y + psize * 0.6 + i * psize * 1.15), l, fp, ctx.theme.muted, anchor="mm",
                      alpha=prog(t, 0.1, 0.3))
        y += len(pl) * psize * 1.15 + 40
    # question with blank / answer
    shown = question.replace("___", options[ans] if revealed else "___") if options else question
    tokens = [(w, "___" in w or (revealed and options and w.strip(".,!?") == options[ans]))
              for w in shown.split()]
    fq, ql = fit_tokens(tokens, SW, 300, 112, "Black")
    draw_emph_lines(d, ql, fq, y, ctx, reveal=1.0, base_color=ctx.theme.text,
                    emph_color=ctx.theme.accent if revealed else ctx.theme.accent2)
    y += len(ql) * fq.size * 1.14 + 60
    # options
    n = max(1, len(options))
    ow = (SW - 40 * (n - 1)) / n
    oh = 150
    for i, o in enumerate(options):
        a = ease_back(prog(t, 0.35 + i * 0.12, 0.4))
        x0 = X0 + i * (ow + 40)
        right = i == ans
        if revealed and right:
            fill, txt_col = ctx.theme.accent, ctx.theme.bg_top
        else:
            fill, txt_col = ctx.theme.panel, ctx.theme.text
        alpha = clamp(a) * (0.45 if revealed and not right else 1.0)
        pop = 1 + 0.06 * math.sin(math.pi * clamp(ra)) if (revealed and right) else 1
        cx = x0 + ow / 2
        w2, h2 = ow * pop / 2, oh * pop / 2
        rrect(d, (cx - w2, y + oh / 2 - h2, cx + w2, y + oh / 2 + h2), 36, fill=fill, alpha=alpha)
        if not (revealed and right):
            rrect(d, (cx - w2, y + oh / 2 - h2, cx + w2, y + oh / 2 + h2), 36, outline=ctx.theme.muted, width=3,
                  alpha=alpha)
        fo = fit_font(o, ow - 60, 76, "Black")
        draw_text(d, (cx, y + oh / 2), o, fo, txt_col, anchor="mm", alpha=alpha)
        if revealed and right:
            _check(d, cx + w2 - 46, y + 40, 40, ctx.theme.bg_top)
        if revealed and not right:
            d.line([(cx - w2 + 30, y + oh / 2), (cx + w2 - 30, y + oh / 2)], fill=(*ctx.theme.bad, int(255 * alpha)),
                   width=6)
    y += oh + 70
    # countdown ring before the reveal, meaning after
    if not revealed and t >= t_rev - cd:
        frac = clamp((t_rev - t) / cd)
        r = 70
        d.ellipse((CX - r, y, CX + r, y + 2 * r), outline=(*ctx.theme.panel, 255), width=12)
        d.arc((CX - r, y, CX + r, y + 2 * r), -90, -90 + 360 * frac, fill=(*ctx.theme.accent2, 255), width=12)
        secs = str(int(math.ceil((t_rev - t) - 1e-6)))
        draw_text(d, (CX, y + r), secs, font(64, "Black"), ctx.theme.text, anchor="mm")
    meaning = ctx.txt(v.get("meaning", ""))
    if revealed and meaning:
        fm, ml, msize = fit_wrapped(meaning, SW, 150, 54, "SemiBold")
        for i, l in enumerate(ml):
            draw_text(d, (CX, y + 30 + msize * 0.6 + i * msize * 1.15), l, fm, ctx.theme.text, anchor="mm",
                      alpha=clamp(ra))


RENDERERS = {
    "hook": hook, "counter": counter, "bars": bars, "donut": donut, "grid": grid, "line": line,
    "quote": quote, "compare": compare, "statement": statement, "end": end,
    "phrase": phrase, "list": list_, "quiz": quiz,
}
