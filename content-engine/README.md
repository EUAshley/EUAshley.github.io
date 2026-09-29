# Content Engine: Daily Benefit Shorts

A one-person system for producing short-form videos and learning what works:

```
IDEA → SCORE → SELECT → SCRIPT → PRODUCTION PACKAGE → HUMAN APPROVAL
     → PUBLISH QUEUE → PERFORMANCE DATA → LEARNINGS → (better) IDEAS
```

This is **Phase 1 (MVP)**. It runs locally, needs no external APIs, and costs nothing to operate.
Nothing is ever posted to a platform automatically: you post by hand and record the URL.

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
| 6. Approve | *Submit for review* → Approve / Request changes / Reject | **The gate.** Only an approved package can be queued. Editing the script after approval revokes it. |
| 7. Queue | *Add to publish queue* (per platform, optional date) | **Publish queue** page lists what's ready to post. |
| 8. Publish | Post it yourself, then *Mark published* with the URL | |
| 9. Measure | *Add snapshot* (views, saves, shares, …), repeat on day 1 / 7 / 30 | Or bulk: `engine import-metrics file.csv` |
| 10. Learn | *Learnings* on the idea; **Report** page | Which categories, hook types, and platforms perform; which offers earn. |

Useful CLI commands: `engine ideas` (ranked queue), `engine report`, `engine export-package <id> --out exports/x.md`.

### CSV metrics import

Columns: `publication_id` **or** `url` (must match the URL you recorded), then any of
`views, likes, comments, shares, saves, follows, link_clicks, avg_watch_seconds, retention_pct, captured_at`.
Rows that don't match a publication are skipped and reported.

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

**Phase 2: Automation.** AI-assisted scoring suggestions (store as `scored_by=ai` next to human
scores). Automated research and trend discovery that feeds new `ideas` with `source` set. Affiliate
matching from `ideas.tools` to `offers`. Per-publication tracking links for real attribution.
Analytics ingestion as new `source=api` snapshots. Voice and asset generation attached to packages.
Add Alembic migrations before the schema changes with real data in it.

**Phase 3: Intelligence.** Compute `category_adjustments` from performance instead of hand-editing them.
Hook A/B tests (two scripts, same idea, compare by `hook_type`). Topic clustering over ideas and learnings.
Monetization and product-opportunity detection from offer clicks and saves.

## Known MVP limits

- The template generator produces a structured draft from your idea fields. It is not finished
  copy: expect to edit on-screen text and the problem line.
- No authentication: this is meant to run on your own machine (`127.0.0.1`).
- Report recommendations are simple heuristics and need 3+ videos per group before they say anything.
- Schema changes currently mean `create_all` for new tables only. Add Alembic before changing existing columns.
