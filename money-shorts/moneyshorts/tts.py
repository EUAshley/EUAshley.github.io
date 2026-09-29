"""Narration: Kokoro neural TTS (runs locally, no API key), cached per sentence.

Each scene's script is split into sentences; each sentence is synthesized
separately so we know exactly when it starts and ends. That gives captions
accurate sentence boundaries, and words are timed within a sentence by their
spoken syllable weight.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from .numbers import speakable

SR = 24000
MODEL_DIR = Path(os.environ.get("MONEYSHORTS_MODELS", Path(__file__).resolve().parent.parent / "models"))
CACHE = Path(__file__).resolve().parent.parent / ".cache" / "tts"
SENTENCE_GAP = 0.16

_kokoro = None


def _engine():
    global _kokoro
    if _kokoro is None:
        from kokoro_onnx import Kokoro
        model = MODEL_DIR / "kokoro-v1.0.onnx"
        voices = MODEL_DIR / "voices-v1.0.bin"
        if not model.exists():
            raise FileNotFoundError(f"Kokoro model not found in {MODEL_DIR}. Run scripts/setup.sh")
        _kokoro = Kokoro(str(model), str(voices))
    return _kokoro


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z$\d\"'<¿¡])", text.strip())
    return [p.strip() for p in parts if p.strip()]


def trim(audio: np.ndarray, thresh: float = 0.012, pad: float = 0.03) -> np.ndarray:
    idx = np.where(np.abs(audio) > thresh)[0]
    if len(idx) == 0:
        return audio
    a = max(0, idx[0] - int(pad * SR))
    b = min(len(audio), idx[-1] + int(pad * SR * 2))
    return audio[a:b]


def synth(text: str, voice: str, speed: float, lang: str = "en-us") -> np.ndarray:
    spoken = speakable(text) if lang.startswith("en") else text.strip()
    key = hashlib.sha1(f"{voice}|{speed}|{lang}|{spoken}".encode()).hexdigest()[:16]
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{key}.wav"
    if path.exists():
        audio, _ = sf.read(path, dtype="float32")
        return audio
    samples, sr = _engine().create(spoken, voice=voice, speed=speed, lang=lang)
    assert sr == SR, sr
    audio = trim(np.asarray(samples, dtype=np.float32))
    sf.write(path, audio, SR)
    return audio


@dataclass
class Run:
    """A same-language stretch of a sentence, with exact audio timing."""
    text: str   # display text (digits kept), used for captions
    lang: str
    start: float
    end: float


@dataclass
class Sentence:
    text: str
    start: float
    end: float
    runs: list[Run]


@dataclass
class SceneAudio:
    audio: np.ndarray
    sentences: list[Sentence]

    @property
    def duration(self) -> float:
        return len(self.audio) / SR


KOKORO_LANG = {"en": "en-us", "es": "es", "fr": "fr-fr", "it": "it", "pt": "pt-br", "hi": "hi", "ja": "ja"}
RUN_GAP = 0.08


def narrate(text: str, voice: str = "af_heart", speed: float = 1.05, alt: dict | None = None) -> SceneAudio:
    """Synthesize a scene. `alt` maps language code -> {name, speed} for <xx>...</xx> runs."""
    from .lang import PAUSE_RE, segments

    alt = alt or {}
    chunks, sents, t = [], [], 0.0
    first = True
    pieces = PAUSE_RE.split(text)  # [text, secs, text, secs, ...]
    for i, piece in enumerate(pieces):
        if i % 2 == 1:
            sil = float(piece)
            chunks.append(np.zeros(int(sil * SR), dtype=np.float32))
            t += sil
            continue
        for s in split_sentences(piece):
            if not first:
                chunks.append(np.zeros(int(SENTENCE_GAP * SR), dtype=np.float32))
                t += SENTENCE_GAP
            first = False
            s_start, runs = t, []
            for j, seg in enumerate(segments(s)):
                if j:
                    chunks.append(np.zeros(int(RUN_GAP * SR), dtype=np.float32))
                    t += RUN_GAP
                if seg.lang == "en":
                    v, sp = voice, speed
                else:
                    if seg.lang not in alt:
                        raise ValueError(f"no voice configured for <{seg.lang}> (add voice.alt.{seg.lang})")
                    v, sp = alt[seg.lang]["name"], float(alt[seg.lang].get("speed", 1.0))
                a = synth(seg.text, v, sp, KOKORO_LANG.get(seg.lang, seg.lang))
                chunks.append(a)
                runs.append(Run(seg.text, seg.lang, t, t + len(a) / SR))
                t += len(a) / SR
            sents.append(Sentence(" ".join(r.text for r in runs), s_start, t, runs))
    return SceneAudio(np.concatenate(chunks) if chunks else np.zeros(1, np.float32), sents)
