"""Narration markup for multi-language scripts.

In a scene's `say:` text:
  <es>Estoy aburrido</es>   spoken by the Spanish voice (voice.alt.es), shown in captions in the accent colour
  [pause 1.5]               1.5 s of silence (e.g. thinking time in a quiz)

Any language code works (<fr>...</fr>) as long as `voice.alt.<code>` is configured.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

TAG_RE = re.compile(r"<(?P<lang>[a-z]{2})>(?P<text>.*?)</(?P=lang)>", re.DOTALL)
PAUSE_RE = re.compile(r"\[pause\s+(?P<sec>\d+(?:\.\d+)?)\]")


@dataclass
class Segment:
    text: str
    lang: str  # "en" = narrator's default language


def strip_markup(text: str) -> str:
    """Plain display text: tags removed (content kept), pauses removed."""
    text = PAUSE_RE.sub(" ", text)
    text = TAG_RE.sub(lambda m: m.group("text"), text)
    return re.sub(r"\s+", " ", text).strip()


def foreign_phrases(text: str) -> list[tuple[str, str]]:
    return [(m.group("lang"), m.group("text").strip()) for m in TAG_RE.finditer(text)]


def segments(sentence: str) -> list[Segment]:
    """Split one sentence into language runs. Punctuation-only runs attach to the previous run."""
    out: list[Segment] = []
    pos = 0
    for m in TAG_RE.finditer(sentence):
        if m.start() > pos:
            out.append(Segment(sentence[pos:m.start()], "en"))
        out.append(Segment(m.group("text"), m.group("lang")))
        pos = m.end()
    if pos < len(sentence):
        out.append(Segment(sentence[pos:], "en"))
    merged: list[Segment] = []
    for s in out:
        if not re.search(r"\w", s.text):
            if merged:
                merged[-1].text += s.text.rstrip()
            continue
        merged.append(Segment(s.text.strip(), s.lang))
    return merged


def normalize(phrase: str) -> str:
    """Glossary key: lowercase, no punctuation (accents kept — they change meaning)."""
    phrase = unicodedata.normalize("NFC", phrase.lower())
    phrase = re.sub(r"[^\w\s]", "", phrase)
    return re.sub(r"\s+", " ", phrase).strip()
