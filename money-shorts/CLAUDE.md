# Money Shorts — production playbook for Claude

This project turns a topic into a finished, fact-checked vertical video with no
human steps in between. When the user gives a topic (or says "make the next
one"), run the whole pipeline below and hand back the rendered MP4.

Project scope: **business + money + data**. Every video should leave the viewer
thinking "I didn't know that" / "now I get how that works".

## Pipeline

| Step | What Claude does | Output |
|---|---|---|
| 1. Topic | Pick from `ideas.md` or the user's prompt. Sharpen it into one question with one surprising answer. | `hook_question` |
| 2. Research | WebSearch for primary sources first (10-K/10-Q, earnings releases, BLS/BEA/FRED/Census, company pages), then reputable press. | `sources:` |
| 3. Fact check | Every number goes into the `facts:` ledger with its source(s), period and confidence. Two independent sources, or one primary. Record disagreements in `conflicts:`. Derived numbers are `calc:` facts. | `facts:` |
| 4. Data | Compute comparisons (per-minute, per-$100, share-of, inflation-adjusted) as `calc:` facts so the checker re-derives them. | `calc:` facts |
| 5. Story | 6–10 scenes on the arc below. One idea per video. | scene list |
| 6. Script | 110–150 words (~45–58 s at speed 1.15). Numbers as digits in `say:`. | `say:` |
| 7. Visuals | Choose a scene type per beat; pull numbers via `@fact` / `{fact:fmt}`. | `visual:` |
| 8–12. Narration, captions, assembly, edit, render | `python -m moneyshorts build episodes/<id>.yaml` | `out/<id>/final.mp4` |
| 13. Release | `python -m moneyshorts release <file>`. If TikTok's cut is under 61 s, add a `variants.tiktok.add_scenes` beat (one more sourced fact). Never pad with filler or silence. | `renders/<id>.<platform>.*` |
| QA | Look at `out/<id>/storyboard.png` and `thumbnail.png` (Read tool). Fix overlaps / weak beats and rebuild. | |

Commands (run from `money-shorts/`):

```bash
python -m moneyshorts new <id>          # scaffold episodes/<id>.yaml from the template
python -m moneyshorts check <file>      # fact-check gate only (fast)
python -m moneyshorts script <file>     # print script + runtime estimate
python -m moneyshorts preview <file>    # ~1 min half-res render for layout review
python -m moneyshorts build <file>      # final render + publish kit
python -m moneyshorts release <file>    # per-platform cuts + publish kits (YouTube, TikTok, Instagram, LinkedIn)
python -m pytest -q tests               # pipeline tests
```

First run in a fresh container: `scripts/setup.sh` (ffmpeg, Python deps, Kokoro voice model).

## Research standards (non-negotiable)

- Prefer primary sources. Mark them `primary: true`.
- Use the **latest complete period** and say which one (`period:`). Never mix fiscal years in one comparison.
- `confidence: reported` for widely reported but undocumented claims (e.g. internal policies, quotes). Script must hedge ("reportedly", "about").
- `confidence: estimate` for third-party estimates. Script **must** hedge or the build fails.
- Compare like with like. If you compare unlike things (pre-tax fees vs after-tax profit), say "equal to", never "part of", and note it in the fact's `claim`.
- Round in speech, never in the ledger. The checker allows 1% by default; raise `tolerance` only for deliberate phrasing like "over 40 years".
- If a source page can't be fetched (network policy), note that in the source's `note:` and cross-check with a second source.

## Story formula

1. **Hook (0–3 s)** — the biggest or most counter-intuitive number, as a claim, not a greeting. `hook`
2. **Twist** — why the obvious explanation is wrong. `compare` / `bars`
3. **Make it tangible** — per $100, per minute, per customer, per day. `grid` / `counter`
4. **Mechanism** — how it actually works. `statement` / `donut` / `line`
5. **Proof** — one number showing the mechanism works. `counter`
6. **Memorable symbol** — a quote, product or story people repeat. `quote`
7. **Reframe** — one sentence the viewer takes away. `end`

Script rules: short sentences; one number per sentence where possible; no
"in this video"; no greetings; end on the reframe, not a summary.

## Scene types

| type | use for | key visual fields |
|---|---|---|
| hook | opening claim | `lines` (`*` = accent line), `sub` |
| counter | one big number counting up | `value`, `format`, `label`, `sub`, `full` |
| bars | 2–4 values (vertical) or 5+ (horizontal) | `items[{label,value,color,tag}]`, `format`, `callout` |
| compare | two numbers head to head | `top{title,value,sub,color}`, `bottom{...}` |
| donut | parts of a whole | `segments[{label,value}]`, `center`, `center_label` |
| grid | "out of every 100…" | `total`, `lit`, `title`, `lit_label` |
| line | change over time | `points[[label,value],…]`, `format`, `end_label` |
| quote | a real quote | `text` (`*emphasis*`), `by`, `note`, `tag` |
| statement | kinetic text | `text` (`*emphasis*`), `sub` |
| end | reframe + CTA | `text`, `sub`, `cta` |

## Output (in `out/<id>/`, git-ignored)

`final.mp4` (1080×1920, 30 fps, H.264/AAC, −14 LUFS) · `captions.srt` ·
`thumbnail.png` · `storyboard.png` · `factcheck.md` · `publish.md` (title,
description, hashtags, sources, script) · `narration.wav` · `build.json`.

`release` copies unique cuts and every platform's publish kit into `renders/`. Set the episode's `status: rendered`.

## Platform variants

```yaml
variants:
  tiktok:
    add_scenes:
      - after: <scene id>        # omit to insert before the closing scene
        id: extra-beat
        type: counter
        say: ...                 # fact-checked like every other scene
        facts: [...]
        visual: {...}
    drop_scenes: [<scene id>]
    publish: {title: ..., description: ..., hashtags: [...]}
```

Platform rules live in `moneyshorts/platforms.py` (`PLATFORMS`).
