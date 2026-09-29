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


# ------------------------------------------------------------ platforms

from moneyshorts.platforms import PLATFORMS, apply_variant, publish_copy, signature  # noqa: E402


def test_variants_fact_check_and_fit_caption_limits():
    ep = load_episode(COSTCO)
    for key, p in PLATFORMS.items():
        v = apply_variant(ep, key)
        assert check(v).ok, (key, check(v).errors)
        assert publish_copy(v, p)["problems"] == [], key


def test_tiktok_variant_inserts_scene_and_others_share_render():
    ep = load_episode(COSTCO)
    tt = apply_variant(ep, "tiktok")
    ids = [s.id for s in tt.scenes]
    assert ids[ids.index("fees") + 1] == "exec-tier"
    assert len(tt.scenes) == len(ep.scenes) + 1
    assert signature(apply_variant(ep, "youtube")) == signature(apply_variant(ep, "instagram")) == signature(ep)
    assert signature(tt) != signature(ep)
    assert [s.id for s in ep.scenes] == [s.id for s in load_episode(COSTCO).scenes]  # original untouched


def test_platform_captions():
    ep = load_episode(COSTCO)
    yt = publish_copy(apply_variant(ep, "youtube"), PLATFORMS["youtube"])
    tag_line = yt["caption"].split("\n\n")[1]
    assert tag_line.split() == ["#shorts", "#costco", "#business"]  # YouTube: max 3, #shorts first
    assert "https://" in yt["caption"]
    ig = publish_copy(apply_variant(ep, "instagram"), PLATFORMS["instagram"])
    assert "https://" not in ig["caption"] and "https://" in ig["first_comment"]


def test_bad_variant_anchor_is_rejected(tmp_path):
    p = tmp_path / "ep.yaml"
    p.write_text(COSTCO.read_text().replace("      - after: fees", "      - after: nope"))
    with pytest.raises(Exception):
        apply_variant(load_episode(p), "tiktok")


# ------------------------------------------------------------ language episodes

from moneyshorts.captions import Word  # noqa: E402
from moneyshorts.lang import normalize, segments, strip_markup  # noqa: E402
from moneyshorts.tts import split_sentences  # noqa: E402

SPANISH = ROOT / "episodes" / "spanish-ser-estar.yaml"


def test_markup_parsing():
    say = "<es>Estoy aburrido</es> means I'm bored. Which verb? [pause 2.2] <es>El café está frío</es>."
    assert strip_markup(say) == "Estoy aburrido means I'm bored. Which verb? El café está frío."
    sents = split_sentences(say.split("[pause")[0])
    assert sents == ["<es>Estoy aburrido</es> means I'm bored.", "Which verb?"]
    segs = segments("But <es>soy aburrido</es>?")
    assert [(s.text, s.lang) for s in segs] == [("But", "en"), ("soy aburrido?", "es")]
    assert normalize("¿Está listo?") == "está listo" != normalize("Esta listo")  # accents matter


def test_spanish_episode_and_tiktok_variant_pass():
    ep = load_episode(SPANISH)
    rep = check(ep)
    assert rep.ok, rep.errors
    assert all(c["fact"].startswith("glossary:") for c in rep.claims)
    assert check(apply_variant(ep, "tiktok")).ok


def test_gate_rejects_unvetted_foreign_phrase(tmp_path):
    p = tmp_path / "ep.yaml"
    p.write_text(SPANISH.read_text().replace("<es>Está muerto</es>.", "<es>Es muerto</es>."))
    errs = check(load_episode(p)).errors
    assert any(e.startswith("E6") and "Es muerto" in e for e in errs)


def test_pause_digits_are_not_claims():
    ep = load_episode(SPANISH)
    quiz = next(s for s in ep.scenes if s.type == "quiz")
    assert "[pause" in quiz.say and check(ep).ok


def test_foreign_words_get_their_own_caption_chunks():
    words = [Word("Estoy", 0, .3, "es"), Word("aburrido", .3, .8, "es"), Word("means", .9, 1.1),
             Word("I'm", 1.1, 1.3), Word("bored.", 1.3, 1.6)]
    assert [c.text for c in chunk_words(words)] == ["Estoy aburrido", "means I'm bored."]
