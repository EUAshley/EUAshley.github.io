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
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z$\d\"'])", text.strip())
    return [p.strip() for p in parts if p.strip()]


def trim(audio: np.ndarray, thresh: float = 0.012, pad: float = 0.03) -> np.ndarray:
    idx = np.where(np.abs(audio) > thresh)[0]
    if len(idx) == 0:
        return audio
    a = max(0, idx[0] - int(pad * SR))
    b = min(len(audio), idx[-1] + int(pad * SR * 2))
    return audio[a:b]


def synth(text: str, voice: str, speed: float, lang: str = "en-us") -> np.ndarray:
    spoken = speakable(text)
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
class Sentence:
    text: str   # display text (digits), used for captions
    start: float
    end: float


@dataclass
class SceneAudio:
    audio: np.ndarray
    sentences: list[Sentence]

    @property
    def duration(self) -> float:
        return len(self.audio) / SR


def narrate(text: str, voice: str = "af_heart", speed: float = 1.05) -> SceneAudio:
    chunks, sents, t = [], [], 0.0
    gap = np.zeros(int(SENTENCE_GAP * SR), dtype=np.float32)
    for i, s in enumerate(split_sentences(text)):
        if i:
            chunks.append(gap)
            t += SENTENCE_GAP
        a = synth(s, voice, speed)
        chunks.append(a)
        sents.append(Sentence(s, t, t + len(a) / SR))
        t += len(a) / SR
    return SceneAudio(np.concatenate(chunks) if chunks else np.zeros(1, np.float32), sents)
