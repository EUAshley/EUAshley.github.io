# Content Engine: Daily Benefit Shorts

A one-person system for producing short-form videos and learning what works:

```
IDEA → SCORE → SELECT → SCRIPT → PRODUCTION PACKAGE → HUMAN APPROVAL
     → PUBLISH QUEUE → PERFORMANCE DATA → LEARNINGS → (better) IDEAS
```

Phase 1 (the MVP) plus the first Phase 2 automations. It runs locally and works with no external
APIs; AI features switch on when you add an Anthropic API key. Nothing is ever posted to a platform
automatically: you post by hand and record the URL.

## Setup

Requires Python 3.10+.

```bash
cd content-engine
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # add ,ai for the optional Claude generator: ".[ai,dev]"
cp .env.example .env             # optional; defaults work without it
engine init                      # creates data/engine.db
engine seed                      # optional: 5 example ideas + 1 example offer
engine web                       # http://127.0.0.1:5000
```

See it work first: `engine demo` runs one idea through every stage in a throwaway
database (`data/demo.db`) and prints the report. To browse that database, run
`ENGINE_DB_URL=sqlite:///data/demo.db engine web`.

## Daily operation

| Step | Where | What you do |
|---|---|---|
| 1. Capture | **+ New idea** | Title, hook, problem, benefit, **solution steps (one per line)**, tools. Steps drive the demo, shot list, and recording plan. |
| 2. Score | Idea page → Score | Rate 7 criteria 1–5. Once every criterion has a score, the idea becomes `scored` and joins the ranked queue. |
| 3. Select | **Ideas** (ranked) → idea → *Select for production* | You decide. The system only ranks. |
| 4. Script | Idea page → *Generate script* | Template draft (or Claude, if configured). Edit inline; each save is a new version. |
| 5. Package | *Build production package* | Shot list, recording steps, on-screen text, caption, hashtags, cover text, assets, monetization notes, time estimate. *Download as Markdown* gives you a filming brief. |
| 6. Record & render | Idea page → **Video** | Record the clips the brief lists (one per step, then the result), upload them, click **Render video**. You get a finished text-only vertical video with music, a cover image, and the caption. |
| 7. Approve | *Submit for review* → Approve / Request changes / Reject | **The gate.** You watch the video and approve. Only an approved package can be queued. Editing the script after approval revokes it. |
| 8. Queue | *Add to publish queue* (per platform, optional date) | **Publish queue** page lists what's ready to post. |
| 9. Publish | Download the video + cover from the queue, post it with the caption and tracking link, then *Mark published* with the URL | |
| 10. Measure | *Add snapshot* (views, saves, shares, …), repeat on day 1 / 7 / 30 | Or bulk: `engine import-metrics file.csv` |
| 11. Learn | *Learnings* on the idea; **Report** page | Which categories, hook types, and platforms perform; which offers earn. |

Useful CLI commands: `engine ideas` (ranked queue), `engine report`, `engine export-package <id> --out exports/x.md`.

## Auto-editor: clips in, finished video out

Videos are **text-only with music** (no voiceover). You record the screen; the editor does the rest.

1. Follow the package's **Screen-recording instructions**: one clip per step, then a clip of the
   result, in order. Don't trim; long clips are sped up (up to 3×) and short ones are held so the
   text can be read.
2. AirDrop the clips to your computer and upload them on the idea page (Video section), or copy them
   into `data/clips/idea-<id>/`. Clips are used in **file-name order**; iPhone recordings are named by
   time, so recording order just works.
3. Click **Render video** (or `engine render <id>`). About 30 seconds later you have:
   - `data/renders/idea-<id>/v<script>-p<package>.mp4`: 1080×1920, 30 fps, H.264 + AAC, ready for TikTok, Reels, and Shorts
   - a `.jpg` cover with the cover text, and a `-caption.txt` with the caption + hashtags
4. Watch it on the idea page, then submit for review. Rendering is only allowed before review, so
   what you approve is exactly what gets posted.

**Timeline:** hook (the result, with the hook text) → problem (text over a dimmed frame) → one segment
per step (clip + numbered step text) → result (benefit text) → CTA (text over the frozen last frame).
Text sits in a band at the top, so it never covers a tap. Timing comes from reading speed, so every
card stays on screen long enough to read.

**Music:** put royalty-free tracks you have the rights to use in `assets/music/` (not committed).
Tracks rotate automatically, or pick one per video. Choose **none** to add a trending sound in the
TikTok/Instagram app instead; the video then gets a silent audio track.

**Look and feel:** the `video:` section of `config/brands/<brand>.yaml` sets size, colors, font,
text-band height, reading speed, speed-up limits, and music volume.

ffmpeg is bundled (via `imageio-ffmpeg`); a system ffmpeg is used if installed. `engine clips <id>`
shows the folder and what's expected.

## Automation (Phase 2)

### One routine: `engine daily`

Drop analytics exports into `data/inbox/`, then run `engine daily`. It imports every CSV (then moves it
to `data/inbox/processed/`), lists videos that need a metrics snapshot, and prints the report. The
dashboard shows the same "Metrics due" list and has an upload box for exports.

### Analytics exports (TikTok, Instagram, YouTube Studio)

`engine import-metrics` (inbox) or `engine import-metrics file1.csv file2.csv`, or upload on the dashboard.
- Rows are matched to your posts by `publication_id`, by URL, or by the **video ID** extracted from the
  URL you recorded when publishing, so exports that only list video IDs still match.
- Headers are recognized from `config/metrics_import.yaml` ("Video views", "Favorites", "Average view
  duration", "New followers", …). If a platform renames a column, add the new name there.
- Understands `1.2K`, `12,345`, `71.5%`, and `0:00:14`. Totals rows and other people's videos are
  counted as "unmatched" and ignored.
- Snapshot checkpoints (default day 1 / 7 / 30) are set in the same file.

### Per-video tracking links and revenue attribution

When a package is queued, the publication gets a short **tracking code** (e.g. `dbs12tt31`) and a
tracking link for every offer linked to the idea or its category:
- If the offer has a **link template** with `{code}` (most affiliate programs have a sub-ID field,
  e.g. Amazon's `ascsubtag`), the code goes there:
  `https://www.amazon.com/dp/B0…?tag=you-20&ascsubtag={code}`
- Otherwise the offer URL gets `utm_source=<platform>&utm_medium=shortform&utm_campaign=<code>`.

Links show on the publish queue and the idea page; put them in the caption or your link-in-bio.
Linking a new offer later refreshes the links. Then import the program's report with
`engine import-revenue report.csv [--offer "Name"]` (or upload on **Offers**). Rows are attributed
to the video by the code column ("Tracking ID", "SubID", "ascsubtag", "utm_campaign", …), and revenue
flows into the report per video, category, and hook type.

### AI research and scoring (optional)

With `ANTHROPIC_API_KEY` set:
- **Research new ideas**: the **Ideas** page, or `engine ai-ideas [--category "AI Tools"] [--count 5] [--no-web]`.
  Claude sees your best and worst performers, your learnings, and every existing idea (to avoid
  repeats), and returns ideas with concrete steps, tools, a hook, and suggested scores. With web
  search on (the default), it checks the steps against current OS/app versions and lists things
  to verify, with sources, in research notes.
- **Suggest scores**: a button on each idea, or `engine ai-score <id>`. It only fills criteria you haven't scored.
- AI output is always a suggestion. AI ideas are tagged **AI** and rank in the queue, but an idea
  becomes `scored` only when you save its scores, and only you can select it for production.
- Cost control: `ENGINE_CLAUDE_EFFORT=low|medium|high` and `--no-web`.

## Configuration (no code changes needed)

- `config/scoring.yaml`: criteria, **weights** (relative; normalized automatically), and per-category
  score adjustments. Rankings update immediately.
- `config/brands/<slug>.yaml`: brand voice, categories, hook types, script structure and timings,
  caption template, hashtag sets, recording checklist, platforms. Add a new file to add a brand, then set `ENGINE_BRAND`.
- `.env`: `ENGINE_DB_URL`, `ENGINE_BRAND`, `ENGINE_SECRET_KEY`, and optionally `ANTHROPIC_API_KEY`.
  Secrets only ever come from the environment.

### Optional: Claude script generator

`pip install -e ".[ai]"` and set `ANTHROPIC_API_KEY` in `.env`. A **Generate script (claude)** button
appears next to the template one. It uses `claude-opus-5-5` by default (override with
`ENGINE_CLAUDE_MODEL`, and tune cost/depth with `ENGINE_CLAUDE_EFFORT=low|medium|high`). It returns
the same structured script, so packaging and approval are unchanged. It is enabled with the API's
server-side refusal fallback. Everything else works without it.

## Architecture

```
Web UI (Flask, server-rendered)   CLI (click)
            └──────────┬──────────┘
                 services/          ← all business rules live here
   ideas · production · publishing · performance · offers
      │            │                       │
  scoring.py   generators/            workflow.py (state machine)
               template | claude | package
                       │
             SQLAlchemy models → SQLite (data/engine.db)
```

**Why this stack:** Python keeps Phase 2/3 work (LLM APIs, analytics ingestion, clustering) in one
language. SQLite needs no server, and a backup is just a copy of the file. SQLAlchemy means moving to
Postgres later is a change to one URL. Flask with plain HTML forms means no JS build and nothing to
deploy. The UI and CLI are thin, so future automations call the same services.

### Data model

| Table | Purpose |
|---|---|
| `brands`, `categories` | Multi-brand ready; categories per brand (not Apple-specific). |
| `ideas` | The content item: title, problem, benefit, audience, hook, steps, tools, source, notes, **status**. |
| `idea_scores` | One row per criterion (1–5, rationale, `scored_by` human/ai). Totals computed at read time from current weights. |
| `status_history` | Audit trail of every status change. |
| `scripts` | Versioned; `sections` JSON (hook/problem/demo/result/cta with timing, voiceover, on-screen text, visual), `hook_type`, generator. |
| `production_packages` | Everything needed to film and post; tied to an exact script version. |
| `renders` | Finished videos from the auto-editor (path, cover, length, music, warnings), per package. |
| `approvals` | Human decisions on a specific package. The queue requires the latest one to be `approved`. |
| `publications` | One per platform post: status, schedule, URL, tracking link. |
| `performance_snapshots` | Time-series metrics per publication (manual / csv / api). |
| `offers`, `offer_links` | Monetization catalog (affiliate, referral, sponsorship, digital product, shortcut pack, newsletter, membership, lead gen, own product, …) linked to ideas **or whole categories**. |
| `revenue_events` | Clicks / conversions / revenue per offer, optionally attributed to a publication. |
| `learnings` | Free-text lessons tied to an idea, publication, or category. |

### Workflow

```
idea → scored → selected → scripted → packaged → in_review → approved → queued → published → measured
                                   ↑                  │
                                   └─ changes_requested
(parked / rejected from most states; parked → back to the queue)
```

## Tests

```bash
pytest
```

Includes an end-to-end test that runs one idea through every stage, a web test that does the same over
HTTP, and tests for the approval gate (you can't queue without approval, and approval is revoked
when the script changes).

## Roadmap

**Phase 2: Automation.** Done: AI idea research with web verification, AI score suggestions,
per-video tracking links, revenue-report attribution, analytics-export import with an inbox, and
metrics-due reminders. Next: direct platform APIs (YouTube Analytics first, since it has the most open
API) as `source=api` snapshots; affiliate matching from `ideas.tools` to offers; trend discovery;
voice and asset generation attached to packages.

**Phase 3: Intelligence.** Compute `category_adjustments` from performance instead of hand-editing them.
Hook A/B tests (two scripts, same idea, compare by `hook_type`). Topic clustering over ideas and learnings.
Monetization and product-opportunity detection from offer clicks and saves.

## Known MVP limits

- The auto-editor can't film your phone: recording the clips is the one manual production step.
  Posting is also manual (TikTok and Instagram require app review before an app can post).
- The template generator produces a structured draft from your idea fields. It is not finished
  copy: expect to edit on-screen text and the problem line.
- No authentication: this is meant to run on your own machine (`127.0.0.1`).
- Report recommendations are simple heuristics and need 3+ videos per group before they say anything.
- Database upgrades are automatic for *added* tables and columns (every command runs them). Renaming or
  removing columns will need a real migration tool (Alembic); add it before making that kind of change.
- AI features were tested against the real SDK with a mock server, not with live API calls.
