# NeuroAxis Social Pipeline — Phase 1 Design

**Date:** 2026-09-05
**Status:** Approved for implementation (scope agreed by JP; detailed design built autonomously while JP was unavailable — see "Rulings made autonomously" at end)
**Source of truth:** [Marketing agent — social media automation (Canva + Metricool)](https://app.notion.com/p/3d082a12021a819ba339f01d3f13310f) (Notion, NeuroAxis HQ / Task Tracker)

---

## 1. Purpose

A serverless pipeline that removes the manual work of running NeuroAxis organic social media:

1. **Generate** funnel-tagged educational/promotional content — copy written by Claude, artwork produced by autofilling a tagged Canva brand template and exporting a static PNG.
2. **Stage** each item in a Notion review queue ("Marketing Content Queue") under a configurable approval mode.
3. **Publish** approved items as a *batch spread across multiple weeks* to Metricool, which posts them organically to X, Facebook, Instagram and Google Business Profile.

Runs for free on GitHub Actions — no server, no new subscription. Paid advertising (Google Ads) is handled separately by JP and is **out of scope**.

## 2. Scope

### In scope (Phase 1)

- Static image content only (PNG from a Canva template autofill).
- Target networks: **X/Twitter, Facebook, Instagram, Google Business Profile**.
- Claude-authored copy with a NeuroAxis brand-voice + healthcare-compliance system prompt and a post-generation compliance validator.
- Funnel model: every content item is tagged **TOFU** (awareness/engagement), **MOFU** (consideration) or **BOFU** (conversion / the "advertisement"). Weekly schedules mix stages.
- Batch + schedule: "generate N items, spread them across W weeks at P posts/week."
- Three approval modes, selected per environment: `review` (default), `auto`, `veto`.
- Notion Marketing Content Queue as the durable state store and review surface (Gallery view with thumbnails).
- Idempotent publish (never double-schedules a row).

### Explicitly deferred (later phases, designed so they bolt on without rework)

| Phase | Deferred item |
|---|---|
| 2 | Rotation & recycling engine — reschedule top performers, remix older library items, no-repeat window, rank by Metricool analytics |
| 3 | Video — Canva video templates, MP4 export, adds YouTube + TikTok + Reels |
| 4 | Trend-responsive content — vidIQ or similar trend research feeding the generator |
| 5 | LinkedIn, Pinterest, blog CMS |

The **content data model** (funnel stage, topic, batch, per-network variants, performance fields) is finalised in Phase 1 so later phases only add rows/consumers, not migrations.

## 3. Architecture

Single Python package `src/`, invoked as `python -m src.pipeline <command>`. Two commands, one shared config and client layer.

```
                    ┌──────────────────────────────────────────────┐
  generate  ──────► │ content.py   → Claude → ContentItem[]         │
                    │ canva_client → autofill template → export PNG │
                    │ media hosting → commit PNG to media/ on main  │
                    │ notion_client → create queue rows (status per │
                    │                 APPROVAL_MODE)                 │
                    └──────────────────────────────────────────────┘
                                       │  (human review in Notion, or auto)
                                       ▼
                    ┌──────────────────────────────────────────────┐
  publish   ──────► │ notion_client → query rows ready to post     │
                    │ scheduling.py → assign each a datetime across │
                    │                 the W-week horizon (pure)     │
                    │ metricool_client → createScheduledPost        │
                    │ notion_client → mark row Scheduled + store id │
                    └──────────────────────────────────────────────┘
```

GitHub Actions: one workflow, `workflow_dispatch` (manual `generate` with a `count` input) + `schedule` cron (periodic `publish`).

### 3.1 Modules

| Module | Responsibility | Key public surface | Depends on |
|---|---|---|---|
| `src/config.py` | Load + validate all settings from env / `.env` | `Settings` dataclass; `Settings.load()` raising `ConfigError` listing every missing key | `python-dotenv` |
| `src/content.py` | Claude call → structured, compliance-checked content | `generate_content_items(settings, count, mix) -> list[ContentItem]`; `ContentItem` dataclass; `ComplianceError` | `anthropic` |
| `src/compliance.py` | Brand + healthcare content rules | `check(text) -> list[str]` (violations); `BANNED_PATTERNS` | stdlib |
| `src/canva_client.py` | Canva Connect API: token refresh, autofill, export | `CanvaClient.render(item, template_id, field_map) -> bytes` (PNG); lower-level `refresh_token`, `create_autofill_job`, `wait_for_autofill`, `export_design` | `requests` |
| `src/media.py` | Make a PNG publicly reachable for Metricool | `publish_media(png_bytes, slug, batch) -> str` (raw GitHub URL); commits to `media/` | `git` (subprocess) |
| `src/notion_client.py` | Notion REST wrapper for the content queue | `create_content_row(...)`, `query_ready_to_publish(mode) -> list[QueueRow]`, `mark_row(page_id, **props)` | `requests` |
| `src/scheduling.py` | **Pure** logic: items + horizon → `[(item, datetime)]` | `build_schedule(items, start, weeks, per_week, mix, tz, slot_times) -> list[ScheduledItem]` | stdlib `zoneinfo` |
| `src/pipeline.py` | Orchestration + argparse CLI | `main(argv)`, `cmd_generate`, `cmd_publish` | all of the above |

Rationale for two modules the README did not list:
- **`notion_client.py`** — the README's file list omitted it, but Notion is the state store; publish cannot work without reading it.
- **`scheduling.py`** — isolating the date-spreading maths as a pure function makes the one piece of real business logic fully unit-testable with no mocks.
- **`media.py`** — see §3.3.
- **`compliance.py`** — healthcare advertising claims are a real risk for this brand (§4); the rules deserve their own tested unit.

### 3.2 Data model — `ContentItem` and the Notion queue

`ContentItem` (in-process):

```python
@dataclass
class ContentItem:
    funnel_stage: Literal["TOFU", "MOFU", "BOFU"]
    topic: str                 # short slug, e.g. "time-blindness"
    title: str                 # human name for the Notion row
    headline: str              # Canva field: headline
    body: str                  # Canva field: body
    cta: str                   # Canva field: cta
    caption: str               # full post text (Notion Notes / Metricool text)
    hashtags: list[str]
    platforms: list[str]       # subset of configured networks
    image_url: str | None = None      # filled after canva+media
    canva_design_url: str | None = None
```

Notion "Marketing Content Queue" (existing DB — schema already present):

| Property | Type | Written by | Notes |
|---|---|---|---|
| Name | title | generate | `ContentItem.title` |
| Batch | text | generate | e.g. `Batch 2 - 2026-09-12` |
| Content Type | select | generate | mapped from funnel stage: TOFU→`Educational Short`, MOFU→`General Post`, BOFU→`Ad` |
| Platform | multi-select | generate | `ContentItem.platforms` |
| Status | select | generate + human + publish | `Pending`/`Approved`/`Rejected`/`Needs Edit`/`Posted` |
| Scheduled Date | date | publish | assigned by `scheduling.py` |
| Canva Link | url | generate | design edit URL |
| Thumbnail | file | generate | the exported PNG (via external URL) |
| Notes | text | generate | full caption + hashtags |

**New property required (one-time, add via Notion UI or the client on first run):** `Metricool ID` (text) — stores the scheduled-post id for idempotency. Also `Funnel Stage` (select: TOFU/MOFU/BOFU) so later phases can filter without parsing Content Type. The pipeline will create these two properties if absent.

### 3.3 Media hosting

Metricool's `createScheduledPost` needs a **publicly reachable** media URL, and posts are scheduled up to 4 weeks out. Canva export URLs are short-lived signed URLs — unsafe to hand to a scheduler.

**Decision:** `generate` downloads the PNG and commits it to `media/<batch>/<slug>.png` on `main`; the stored URL is
`https://raw.githubusercontent.com/jpyoung2011-ai/neuroaxis-social-pipeline/main/media/<batch>/<slug>.png`.
Permanent, free, no extra service. The repo is private, but `raw.githubusercontent.com` URLs for a private repo require a token — so **the repo must be public, or** we use a dedicated public `neuroaxis-social-media` repo for assets only. → **Ruling:** create assets in a separate **public** repo `neuroaxis-social-assets` (no code, just PNGs). Configurable via `MEDIA_REPO`. If JP prefers, a Cloudinary/S3 bucket can replace `media.py` without touching anything else.

### 3.4 Approval modes (`APPROVAL_MODE`)

| Mode | `generate` sets Status | `publish` schedules rows where… |
|---|---|---|
| `review` (default) | `Pending` | Status == `Approved` |
| `auto` | `Approved` | Status == `Approved` |
| `veto` | `Pending` | Status == `Pending` AND row age ≥ `VETO_HOURS` (default 48) AND Status != `Rejected` |

In every mode, `publish` skips rows that already have a `Metricool ID` or Status `Posted`/`Rejected`/`Needs Edit`.

### 3.5 Scheduling logic (`build_schedule`)

Pure function. Inputs: approved items, `start_date`, `weeks`, `per_week`, funnel `mix` (e.g. `{"TOFU":3,"MOFU":1,"BOFU":1}`), `tz`, `slot_times` (per weekday list of `HH:MM`, or per-network best times supplied by caller).

Algorithm:
1. Order items to satisfy the weekly mix (round-robin by stage, BOFU never two days running).
2. Walk forward from `start_date`, skipping weekends unless `include_weekends`, placing `per_week` items per ISO week at the configured slot times.
3. Return `[(item, aware_datetime)]`. Never schedules in the past (clamps to `now + 1h`).

Deterministic given inputs → straightforward table-driven unit tests.

## 4. Compliance guardrail

NeuroAxis is a regulated healthcare provider. HQ rules and ASA/CAP health-claims rules mean generated copy MUST NOT:

- claim or imply **CQC registration** (locked wording: "Operating to CQC standards" only);
- promise to **cure**, "fix", or guarantee outcomes;
- **diagnose** the reader or assert they "have ADHD";
- name prescription medications or imply medication outcomes;
- use Trustpilot logos/widgets (text only);
- make superiority claims that can't be substantiated ("the best", "fastest in the UK").

`compliance.check()` runs on every generated `caption`, `headline`, `body`, `cta`. Any violation → `content.py` asks Claude to regenerate that item once with the violation fed back; a second failure raises `ComplianceError` and that item is dropped from the batch (logged, non-fatal for the rest).

The Claude system prompt encodes the same rules positively (brand voice: "professional yet approachable and empowering", "ADHD clarity, without the wait"; palette and services for context) plus the funnel-stage brief.

## 5. Error handling

- **Fail visibly** (HQ rule) — no swallowed exceptions. Each external call wrapped with a specific exception type and a clear message; `pipeline.py` catches per-item where it makes sense (one bad item ≠ whole batch fails) and re-raises fatal config/auth errors.
- Canva token refresh failure, Notion auth failure, Metricool auth failure → fatal, non-zero exit.
- Canva autofill/export polling: bounded retries with backoff, timeout → item-level failure.
- `--dry-run`: `generate` runs copy + Canva + compliance and prints the items and the PNG paths, **no** Notion write, **no** media commit. `publish --dry-run` reads Notion and prints the computed schedule, **no** Metricool write, **no** Notion update.
- Every run prints a summary: N generated / N skipped / N scheduled / failures.

## 6. Testing strategy

`pytest`, HTTP mocked with `responses`. `requirements-dev.txt` adds `pytest`, `responses`.

| Unit | Tests |
|---|---|
| `config.py` | missing-key errors list every gap; happy path; type coercion (ints, comma-lists) |
| `compliance.py` | each banned pattern caught; clean text passes; case-insensitivity |
| `content.py` | Anthropic client mocked → returns valid `ContentItem[]`; schema enforced; compliance regeneration loop (1 retry then drop); funnel mix respected |
| `canva_client.py` | token refresh request shape; autofill create→poll→complete; export create→poll→download; error/timeout paths |
| `notion_client.py` | create row payload shape per approval mode; query filter per mode; `mark_row` property mapping; auto-creates missing properties |
| `scheduling.py` | table-driven: horizons, mixes, weekend skip, past-clamp, BOFU spacing, fewer items than slots |
| `media.py` | git subprocess mocked; URL construction; slug sanitisation |
| `pipeline.py` | full flow with every client mocked, once per approval mode; `--dry-run` performs no mutations; per-item failure isolation |

Target: every module has tests; `pipeline` integration test is the safety net. No live-credential test in CI; a `scripts/smoke.py` (manual) does one real end-to-end `--dry-run`.

## 7. Configuration (additions to `.env.example`)

```
# Approval flow
APPROVAL_MODE=review            # review | auto | veto
VETO_HOURS=48

# Batch / scheduling defaults (overridable by CLI flags)
BATCH_COUNT=5
SCHEDULE_WEEKS=4
POSTS_PER_WEEK=5
FUNNEL_MIX=TOFU:3,MOFU:1,BOFU:1
SCHEDULE_SLOTS=10:00,13:00,17:00
INCLUDE_WEEKENDS=false

# Networks (v1 static)
METRICOOL_NETWORKS=twitter,facebook,instagram,gmb

# Notion
NOTION_TOKEN=
NOTION_CONTENT_DB_ID=

# Media hosting
MEDIA_REPO=jpyoung2011-ai/neuroaxis-social-assets
MEDIA_REPO_TOKEN=              # PAT with contents:write on the assets repo (CI)

# Anthropic
ANTHROPIC_MODEL=claude-sonnet-5
```

## 8. Build sequence (for the implementation plan)

1. `config.py` + tests
2. `compliance.py` + tests
3. `scheduling.py` + tests (pure, no deps — fast win)
4. `canva_client.py` + tests
5. `notion_client.py` + tests
6. `media.py` + tests
7. `content.py` + tests (depends on compliance)
8. `pipeline.py` + integration tests (depends on all)
9. `.github/workflows/publish.yml` + `README` update + `.env.example` update + `scripts/smoke.py`

## 9. What still needs JP (cannot be done autonomously)

- Tag the real Canva brand template's text boxes as autofill data fields; provide `CANVA_BRAND_TEMPLATE_ID` and the field names.
- Create the Canva Developer Portal integration; run `setup_canva_oauth.py` for `CANVA_REFRESH_TOKEN`.
- Metricool `METRICOOL_TOKEN` / `USER_ID` / `BLOG_ID`, and confirm the connected network account ids.
- Create the public `neuroaxis-social-assets` repo (or choose Cloudinary/S3).
- Notion internal integration token + share the Marketing Content Queue DB with it; provide `NOTION_CONTENT_DB_ID`.
- `ANTHROPIC_API_KEY`.
- Decide the default `APPROVAL_MODE` for the live GitHub Actions environment (recommended: `review` until trust is established).

## 10. Rulings made autonomously (JP to review)

| # | Ruling | Cost if wrong |
|---|---|---|
| 1 | Direct TDD implementation by the main session rather than the subagent-driven-development dispatch ceremony — JP is away, no context-preservation benefit, lower token cost. | None structural; just a process choice. |
| 2 | Work on branch `feat/phase-1-pipeline`, not `main`, not a worktree. | Trivial to rebase/merge. |
| 3 | Media hosted as PNGs committed to a **separate public repo** `neuroaxis-social-assets`. | If JP wants Cloudinary/S3, only `media.py` changes (one module, isolated). |
| 4 | Approval mode is env-configured; **`review` is the default**, honouring the "approval-before-posting" rule in Notion. | If JP wanted `auto` by default, one env var. |
| 5 | Funnel→Content Type mapping: TOFU→Educational Short, MOFU→General Post, BOFU→Ad. Adds a dedicated `Funnel Stage` select too. | Cosmetic; re-mappable. |
| 6 | Two new Notion properties (`Metricool ID`, `Funnel Stage`) auto-created by the client if missing. | If JP dislikes auto-schema-changes, make it a manual step. |
| 7 | CLI is `generate` / `publish` subcommands (README implied one entry point `python -m src.pipeline`). Both honour `--dry-run`. | Interface only; documented in README update. |
| 8 | `content.py` drops (does not fail the batch on) an item that fails compliance twice. | A quiet gap in a batch; logged. Alternative: fail loudly. |
| 9 | Default networks `twitter,facebook,instagram,gmb` (Metricool's key for Google Business Profile is `gmb`). | Verify against Metricool account; one env var. |
