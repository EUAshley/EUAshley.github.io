from pathlib import Path

import pytest

from moneyshorts.captions import chunk_words, srt, time_words
from moneyshorts.factcheck import check, safe_eval
from moneyshorts.numbers import fill_template, find_numbers, format_value, speakable
from moneyshorts.spec import load_episode

ROOT = Path(__file__).resolve().parent.parent
COSTCO = ROOT / "episodes" / "costco-membership.yaml"


def test_speakable_numbers():
    assert speakable("$297 billion") == "two hundred ninety-seven billion dollars"
    assert speakable("$1.50") == "a dollar fifty"
    assert speakable("the $1.50 hot dog") == "the one dollar fifty hot dog"
    assert speakable("92.3%") == "ninety-two point three percent"
    assert speakable("since 1985") == "since nineteen eighty-five"
    assert speakable("$65 a year") == "sixty-five dollars a year"
    assert speakable("$5.9B") == "five point nine billion dollars"


def test_find_numbers_scales():
    toks = find_numbers("Sold $297 billion, kept 64% and 84.1 million members")
    assert [t.value for t in toks] == [297e9, 64, 84.1e6]
    assert toks[1].candidates() == [64, 0.64]


def test_formats():
    assert format_value(297.2e9, "money0") == "$297B"
    assert format_value(9.226e9, "money1") == "$9.2B"
    assert format_value(0.923, "pct1") == "92.3%"
    assert format_value(1.5, "dollars") == "$1.50"
    assert fill_template("{a:pct} of {b:num}", {"a": 0.64, "b": 84.1e6}) == "64% of 84.1M"


def test_safe_eval_rejects_code():
    assert safe_eval("a / b * 100", {"a": 3, "b": 100}) == 3
    with pytest.raises(ValueError):
        safe_eval("__import__('os')", {})


def test_costco_episode_passes():
    rep = check(load_episode(COSTCO))
    assert rep.ok, rep.errors
    assert len(rep.claims) >= 10


def _mutated(tmp_path, old, new):
    p = tmp_path / "ep.yaml"
    text = COSTCO.read_text()
    assert old in text
    p.write_text(text.replace(old, new, 1))
    return check(load_episode(p))


def test_gate_catches_wrong_spoken_number(tmp_path):
    rep = _mutated(tmp_path, "sold $297 billion", "sold $397 billion")
    assert any(e.startswith("E1") for e in rep.errors)


def test_gate_catches_bad_calc(tmp_path):
    rep = _mutated(tmp_path, "value: 0.6406", "value: 0.70")
    assert any(e.startswith("E3") for e in rep.errors)


def test_gate_catches_hardcoded_visual(tmp_path):
    rep = _mutated(tmp_path, '"*{net_sales:money0}"', '"*$300B"')
    assert any(e.startswith("E5") for e in rep.errors)


def test_gate_requires_hedge(tmp_path):
    # reported facts without a hedge -> warning
    rep = _mutated(tmp_path, "reportedly caps its markup", "caps its markup")
    assert any(w.startswith("W2") for w in rep.warnings)
    # estimates without a hedge -> blocking error
    p = tmp_path / "ep2.yaml"
    text = COSTCO.read_text().replace("reportedly caps its markup", "caps its markup")
    text = text.replace("sources: [acquired_markup, yahoo_kirkland]\n    confidence: reported",
                        "sources: [acquired_markup, yahoo_kirkland]\n    confidence: estimate", 1)
    p.write_text(text)
    assert any(e.startswith("E4") for e in check(load_episode(p)).errors)


def test_caption_timing_is_monotonic():
    words = time_words("Costco sold $297 billion worth of stuff.", 1.0, 4.0)
    assert words[0].start == 1.0 and abs(words[-1].end - 4.0) < 1e-9
    assert all(a.end <= b.start + 1e-9 for a, b in zip(words, words[1:]))
    chunks = chunk_words(words)
    assert all(len(c.words) <= 3 for c in chunks)
    assert "00:00:01,000" in srt(chunks)
