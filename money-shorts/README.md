# Money Shorts

Short vertical videos (Shorts / Reels / TikTok) that explain surprising
**business + money + data** facts. It turns one topic into a finished,
fact-checked 1080×1920 MP4 with narration, captions, animated charts and
music, without manual editing.

This is a standalone project. It shares no code with `content-engine/`.

```
TOPIC → RESEARCH → FACT CHECK → DATA → STORY → SCRIPT      (Claude, into episodes/<id>.yaml)
      → VISUALS → NARRATION → CAPTIONS → ASSEMBLY → EDIT → FINAL RENDER   (python -m moneyshorts build)
```

## Quick start

```bash
cd money-shorts
scripts/setup.sh                                        # ffmpeg, deps, Kokoro voice model (~350 MB)
python -m moneyshorts check episodes/costco-membership.yaml
python -m moneyshorts build episodes/costco-membership.yaml
# -> out/costco-membership/final.mp4 (+ captions.srt, thumbnail.png, storyboard.png, publish.md, factcheck.md)
```

To make a new video, open a Claude Code session in this repo and say something like
*"Make a Money Shorts episode: why printer companies sell printers cheap."*
Claude follows [`CLAUDE.md`](CLAUDE.md) end to end: research, fact ledger,
script, visuals, render and QA. Topic ideas are in [`ideas.md`](ideas.md).

## How it works

An **episode file** (`episodes/<id>.yaml`) holds three things:

1. `sources`: every document relied on, with URL and access date.
2. `facts`: the **fact ledger**. Each number has its source(s), period and
   confidence. Derived numbers (`calc: net_income / total_revenue * 100`)
   are recomputed by the checker.
3. `scenes`: narration (`say`), a visual type, and the facts it cites.

The **fact-check gate** (`moneyshorts/factcheck.py`) blocks rendering when:
- a number spoken in the script doesn't match a fact the scene cites (E1)
- a fact has no source (E2)
- a calculation doesn't reproduce (E3)
- an estimate is stated without a hedge word (E4)
- a number is hard-coded on screen instead of pulled from the ledger (E5)

It warns on single-source claims, unhedged "reported" claims, and source conflicts.

**Rendering** (`moneyshorts/render.py`):
- **Narration:** [Kokoro](https://github.com/thewh1teagle/kokoro-onnx), a
  local neural TTS. It needs no API key, and output is cached per sentence.
  Numbers are converted to words before speech ("$1.50" becomes "a dollar
  fifty"), and captions keep the digits.
- **Visuals:** 10 animated scene types drawn with Pillow: hook, counter,
  bars, compare, donut, grid, line, quote, statement and end. Layouts stay
  inside platform safe zones.
- **Captions:** 1–3 word chunks with the spoken word highlighted. Also
  exported as SRT.
- **Audio:** a procedurally generated music bed, so there are no licensing
  issues. It ducks under the voice, adds transition whooshes, and is
  loudness-normalised to about −14 LUFS.
- **Encoding:** frames are rendered in parallel and piped to ffmpeg
  (H.264 High, CRF 18, AAC 192k, faststart). A 60 s video takes about
  1.5 minutes on 4 cores.

## Rendered episodes

| Episode | Video | Length |
|---|---|---|
| How Costco actually makes its money | [`renders/costco-membership.mp4`](renders/costco-membership.mp4) | 58.6 s |

## Known limits

- The voice is synthetic. Disclose AI narration where a platform requires it.
- Caption word timing is estimated from syllables within each sentence.
  Sentence boundaries are exact, and single words can drift by up to about
  0.2 s.
- Visuals are data graphics and kinetic type only. There is no stock footage
  or logos, by design, to avoid rights issues.
- Research runs through web search. Some hosts (sec.gov, investor-relations
  sites) are blocked by this cloud environment's network policy, so figures
  from those pages were checked through search excerpts plus independent
  coverage. The fact ledger records this.
- Uploading to platforms is not automated. `publish.md` holds the title,
  description, hashtags and source list, ready to paste.
