"""Procedural sound: royalty-free music bed + transition whooshes + ducked mix.

Everything is synthesized with numpy, so there are no licensing questions.
"""
from __future__ import annotations

import numpy as np

from .tts import SR

# A minor-ish progression (Am - F - C - G), root frequencies in Hz
PROGRESSION = [
    [220.00, 261.63, 329.63],
    [174.61, 220.00, 261.63],
    [261.63, 329.63, 392.00],
    [196.00, 246.94, 293.66],
]


def _lowpass(x: np.ndarray, alpha: float) -> np.ndarray:
    # one-pole low-pass, vectorised via cumulative filter approximation
    y = np.empty_like(x)
    acc = 0.0
    for i in range(0, len(x), 256):  # block-wise for speed
        blk = x[i:i + 256]
        out = np.empty_like(blk)
        for j, s in enumerate(blk):
            acc += alpha * (s - acc)
            out[j] = acc
        y[i:i + 256] = out
    return y


def music_bed(duration: float, bpm: float = 96, seed: int = 7) -> np.ndarray:
    n = int(duration * SR) + SR
    t = np.arange(n) / SR
    beat = 60 / bpm
    bar = beat * 4
    out = np.zeros(n, dtype=np.float32)
    rng = np.random.default_rng(seed)

    # pad: detuned sines per chord, crossfaded per bar
    for k in range(int(duration / bar) + 2):
        chord = PROGRESSION[k % len(PROGRESSION)]
        a, b = int(k * bar * SR), int((k + 1) * bar * SR + 0.3 * SR)
        if a >= n:
            break
        b = min(b, n)
        tt = t[a:b] - k * bar
        env = np.minimum(1, tt / 0.4) * np.minimum(1, np.maximum(0, (bar + 0.3 - tt) / 0.5))
        seg = np.zeros(b - a, dtype=np.float32)
        for f in chord:
            for det in (-0.7, 0.0, 0.7):
                seg += np.sin(2 * np.pi * (f / 2 + det) * tt).astype(np.float32)
        seg += 0.8 * np.sin(2 * np.pi * chord[0] / 4 * tt)  # sub
        out[a:b] += 0.05 * env * seg

        # arpeggio plucks on 8th notes
        for s in range(8):
            st = k * bar + s * beat / 2
            ia = int(st * SR)
            if ia >= n:
                break
            f = chord[s % 3] * (2 if s % 4 == 3 else 1)
            L = min(int(0.45 * SR), n - ia)
            pt = np.arange(L) / SR
            pl = np.sin(2 * np.pi * f * pt) * np.exp(-pt * 9)
            out[ia:ia + L] += 0.06 * pl.astype(np.float32)

    # soft kick on beats 1 and 3, hat on offbeats
    for i in range(int(duration / beat) + 1):
        ia = int(i * beat * SR)
        if ia >= n:
            break
        if i % 2 == 0:
            L = min(int(0.25 * SR), n - ia)
            pt = np.arange(L) / SR
            kick = np.sin(2 * np.pi * (55 + 90 * np.exp(-pt * 30)) * pt) * np.exp(-pt * 14)
            out[ia:ia + L] += 0.22 * kick.astype(np.float32)
        ih = int((i + 0.5) * beat * SR)
        L = min(int(0.05 * SR), n - ih)
        if L > 0:
            hat = rng.standard_normal(L) * np.exp(-np.arange(L) / SR * 90)
            hat = np.diff(hat, prepend=0)  # crude high-pass
            out[ih:ih + L] += 0.025 * hat.astype(np.float32)
    return out[: int(duration * SR)]


def whoosh(length: float = 0.35, seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    L = int(length * SR)
    noise = rng.standard_normal(L).astype(np.float32)
    x = np.linspace(0, 1, L)
    env = np.sin(np.pi * x) ** 2
    # sweep: blend low-passed and raw noise over time
    lp = _lowpass(noise, 0.05)
    sig = lp * (1 - x) + np.diff(noise, prepend=0) * 0.25 * x
    return (0.35 * env * sig).astype(np.float32)


def envelope(x: np.ndarray, win: float = 0.12) -> np.ndarray:
    k = max(1, int(win * SR))
    e = np.sqrt(np.convolve(x.astype(np.float64) ** 2, np.ones(k) / k, mode="same"))
    return e.astype(np.float32)


def mix(voice: np.ndarray, cuts: list[float], music: bool = True, music_gain_db: float = -20,
        duck_db: float = -9) -> np.ndarray:
    n = len(voice)
    out = voice.copy() * 1.0
    if music:
        bed = music_bed(n / SR)
        bed = bed[:n] if len(bed) >= n else np.pad(bed, (0, n - len(bed)))
        env = envelope(voice)
        talking = np.clip(env / (env.max() * 0.15 + 1e-9), 0, 1)
        duck = 10 ** ((music_gain_db + duck_db * talking) / 20)
        fade = np.minimum(1, np.minimum(np.arange(n) / (0.3 * SR), (n - np.arange(n)) / (1.2 * SR)))
        peak = np.abs(bed).max() or 1
        out += (bed / peak) * duck * fade
    w = whoosh()
    for i, c in enumerate(cuts):
        a = int(max(0, c - 0.18) * SR)
        b = min(n, a + len(w))
        if b > a:
            out[a:b] += w[: b - a] * 0.5
    peak = np.abs(out).max() or 1
    return (out / peak * 0.89).astype(np.float32)  # ~ -1 dBFS peak
