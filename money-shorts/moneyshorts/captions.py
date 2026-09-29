"""Captions: word timing, chunking, burned-in rendering and SRT export."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .draw import CAPTION_Y, MARGIN, W, draw_text, ease_back, font, prog, rrect, text_w
from .numbers import speakable

MAX_WORDS = 3
MAX_CHARS = 20


@dataclass
class Word:
    text: str
    start: float
    end: float
    lang: str = "en"


@dataclass
class Chunk:
    words: list[Word]

    @property
    def start(self) -> float:
        return self.words[0].start

    @property
    def end(self) -> float:
        return self.words[-1].end

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


def syllables(word: str) -> float:
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 0.5
    groups = re.findall(r"[aeiouy]+", w)
    n = len(groups)
    if w.endswith("e") and n > 1 and not w.endswith(("le", "ee")):
        n -= 1
    return max(1, n)


def word_weight(display_word: str) -> float:
    spoken = speakable(display_word)
    weight = sum(syllables(w) for w in spoken.split()) or 1
    if re.search(r"[,;:]$", display_word):
        weight += 0.9
    elif re.search(r"[.!?]$", display_word):
        weight += 0.6
    return weight


def time_words(sentence: str, start: float, end: float, lang: str = "en") -> list[Word]:
    words = sentence.split()
    weights = [word_weight(w) for w in words]
    total = sum(weights) or 1
    out, t = [], start
    for w, wt in zip(words, weights):
        dur = (end - start) * wt / total
        out.append(Word(w, t, t + dur, lang))
        t += dur
    return out


def chunk_words(words: list[Word]) -> list[Chunk]:
    chunks, cur = [], []
    for w in words:
        lang_change = cur and cur[-1].lang != w.lang
        if cur and (lang_change or len(cur) >= MAX_WORDS or len(" ".join(x.text for x in cur + [w])) > MAX_CHARS):
            chunks.append(Chunk(cur))
            cur = []
        cur.append(w)
        if re.search(r"[.!?,;:]$", w.text):
            chunks.append(Chunk(cur))
            cur = []
    if cur:
        chunks.append(Chunk(cur))
    return chunks


def clean(word: str) -> str:
    return word.strip("\"'").rstrip(",;:")


def draw_caption(d, chunks: list[Chunk], t: float, theme):
    """Burn in the active chunk; the word being spoken is highlighted."""
    active = None
    for c in chunks:
        if c.start <= t < c.end + 0.12:
            active = c
    if active is None:
        return
    f = font(76, "Black")
    words = [clean(w.text).upper() if w.lang == "en" else clean(w.text) for w in active.words]
    space = text_w(" ", f)
    widths = [text_w(w, f) for w in words]
    total = sum(widths) + space * (len(words) - 1)
    if total > W - 2 * MARGIN:
        f = font(int(76 * (W - 2 * MARGIN) / total), "Black")
        widths = [text_w(w, f) for w in words]
        space = text_w(" ", f)
        total = sum(widths) + space * (len(words) - 1)
    pop = ease_back(prog(t, active.start, 0.16))
    x = W / 2 - total / 2
    y = CAPTION_Y
    pad = 26
    rrect(d, (x - pad, y - f.size * 0.72, x + total + pad, y + f.size * 0.72), 24,
          fill=(0, 0, 0), alpha=0.55 * min(1, pop))
    for w, ww, word in zip(active.words, widths, words):
        speaking = w.start <= t < w.end or (w is active.words[-1] and t >= w.start)
        foreign = w.lang != "en"
        col = theme.accent if foreign else (theme.accent2 if speaking else theme.text)
        dy = -6 if speaking else 0
        draw_text(d, (x, y + dy + (1 - pop) * 18), word, f, col, anchor="lm", alpha=min(1, pop * 1.5),
                  stroke=5, stroke_fill=(0, 0, 0))
        if foreign and speaking:
            rrect(d, (x, y + f.size * 0.5, x + ww, y + f.size * 0.5 + 7), 3, fill=theme.accent)
        x += ww + space


def srt(chunks: list[Chunk]) -> str:
    def ts(s: float) -> str:
        ms = int(round(s * 1000))
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        sec, ms = divmod(ms, 1000)
        return f"{h:02}:{m:02}:{sec:02},{ms:03}"
    out = []
    for i, c in enumerate(chunks, 1):
        out.append(f"{i}\n{ts(c.start)} --> {ts(c.end)}\n{' '.join(clean(w.text) for w in c.words)}\n")
    return "\n".join(out)
