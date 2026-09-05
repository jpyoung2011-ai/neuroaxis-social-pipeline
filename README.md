# NeuroAxis Social Pipeline

A serverless automation that runs NeuroAxis organic social media:

1. **Generate** — Claude writes funnel-tagged post copy (headline / body / CTA / caption),
   Canva autofills a tagged brand template with it and exports a PNG.
2. **Stage** — each item lands in a Notion review queue ("Marketing Content Queue")
   under a configurable approval mode.
3. **Publish** — approved items are scheduled as a batch, spread across several weeks,
   to Instagram / Facebook / X / Google Business Profile via the **Metricool API**.

Runs for free on **GitHub Actions** — no server, no VPS, no new subscription.
Paid advertising (Google Ads) is handled separately and is not part of this.

See `docs/superpowers/specs/2026-09-05-phase-1-social-pipeline-design.md` for the full design,
and `STATUS.md` for exactly what is built and what still needs you.

---

## How it works

```
generate:  Claude (copy) -> Canva (autofill template -> PNG) -> commit PNG to assets repo
           -> create Notion queue row (Pending / Approved, per APPROVAL_MODE)

  ... you review in Notion's "Review Gallery" (or a mode approves automatically) ...

publish:   read Approved/ready rows -> spread across the horizon (scheduling.py)
           -> Metricool createScheduledPost -> mark the Notion row Posted
```

### Two commands

```bash
python -m src.pipeline generate --count 5 [--batch-label "Batch 3"] [--dry-run]
python -m src.pipeline publish [--dry-run]
```

`--dry-run` on `generate` writes the PNGs to `./out/` and does nothing else.
`--dry-run` on `publish` prints the computed schedule and writes nothing.

### Approval modes (`APPROVAL_MODE`)

| Mode | `generate` creates rows as | `publish` schedules |
|------|----------------------------|---------------------|
| `review` (default) | `Pending` | rows you set to `Approved` |
| `auto` | `Approved` | those `Approved` rows |
| `veto` | `Pending` | any not `Rejected` after `VETO_HOURS` |

`publish` never re-schedules a row that already has a `Metricool ID`.

### Funnel model

Every item is tagged **TOFU** (awareness / engagement), **MOFU** (consideration) or
**BOFU** (conversion — the "advertisement"). `FUNNEL_MIX` sets the weekly ratio;
`scheduling.py` spreads the stages across each week and keeps BOFU posts apart.

---

## Why it's built this way (read before assuming something is missing)

- Canva's Connect API requires **OAuth 2.0 with PKCE** — no static API key.
  `setup_canva_oauth.py` does the one-time browser authorization and prints the refresh token.
- Canva **rotates the refresh token on every use**. In CI the pipeline logs the new value;
  update the `CANVA_REFRESH_TOKEN` secret when it changes (or re-run `setup_canva_oauth.py`).
- Canva's Autofill API needs the acting Canva user to be on **Canva Enterprise**, or within
  the limited development trial. If autofill returns `feature_not_available` /
  `trial_quota_exceeded`, that's an account-tier issue, not a bug. **Verify this early.**
- Your Canva brand template must already have its text boxes tagged as **data fields**
  (Canva UI, one-time). The API can only autofill fields that exist.
- Metricool needs a **publicly reachable** media URL and posts schedule weeks out, but Canva
  export URLs expire in 24h — so rendered PNGs are committed to a **separate public repo**
  (`MEDIA_REPO`) and referenced by their stable `raw.githubusercontent.com` URL.
- Metricool authenticates with a static token (`X-Mc-Auth` header + query params) — no OAuth.
- Notion is the durable state store and review surface, not just a log.

---

## One-time setup

### 1. Tag your Canva template for autofill
In Canva, open the NeuroAxis post template → for each text box, right-click → "Add data field"
→ name them (e.g. `headline`, `body`, `cta`). Note the brand template ID from the URL
(`canva.com/design/<THIS_PART>/...`). Put the field names in `CANVA_FIELD_*`.

### 2. Create a Canva integration
[Canva Developer Portal](https://www.canva.com/developers/integrations/connect-api) →
Create an integration. Note the Client ID, generate a Client Secret. Enable scopes:
`asset:read/write`, `brandtemplate:content:read`, `brandtemplate:meta:read`,
`design:content:read/write`, `design:meta:read`, `profile:read`. Set the redirect URL to
`http://127.0.0.1:8765/oauth/redirect`.

### 3. Authorize once, locally
```bash
python -m venv .venv && . .venv/Scripts/activate   # or .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fill in CANVA_CLIENT_ID / CANVA_CLIENT_SECRET
python setup_canva_oauth.py # prints CANVA_REFRESH_TOKEN -> put it in .env
```

### 4. Notion
Create an internal integration ([notion.so/my-integrations](https://www.notion.so/my-integrations)),
share the "Marketing Content Queue" database with it. Put the token in `NOTION_TOKEN` and the
database ID in `NOTION_CONTENT_DB_ID`. The pipeline auto-adds two properties it needs
(`Metricool ID`, `Funnel Stage`) on first `publish`.

### 5. Metricool
Metricool → Settings → API → copy the token, `userId`, `blogId` into `METRICOOL_*`.
Confirm the connected network accounts match `METRICOOL_NETWORKS`.

### 6. Media assets repo
Create a **public** repo (e.g. `neuroaxis-social-assets`), set `MEDIA_REPO` to `owner/name`,
and put a token with `contents:write` on it in `MEDIA_REPO_TOKEN`.

### 7. Anthropic
API key from [console.anthropic.com](https://console.anthropic.com) → `ANTHROPIC_API_KEY`.

### 8. Smoke test, then go live
```bash
pip install -r requirements-dev.txt
pytest                       # all unit tests
python -m scripts.smoke      # 1 item, real Canva + Claude, PNG to ./out/, no posting
python -m src.pipeline generate --count 3 --dry-run
```
Then add every `.env` value to the repo: secrets for tokens/keys, Actions **variables** for
the non-secret tuning knobs (`APPROVAL_MODE`, `FUNNEL_MIX`, `SCHEDULE_*`, `BRAND_*`,
`METRICOOL_NETWORKS`, `CANVA_FIELD_*`, `ANTHROPIC_MODEL`, `MEDIA_REPO`). The workflow
(`.github/workflows/publish.yml`) runs `publish` on a cron and `generate`/`publish` on demand.

---

## Files

| Path | Responsibility |
|------|----------------|
| `setup_canva_oauth.py` | one-time local OAuth (PKCE) authorization |
| `src/config.py` | load + validate every setting from the environment |
| `src/compliance.py` | healthcare-advertising guardrails for generated copy |
| `src/content.py` | Claude call → structured, compliance-checked `ContentItem[]` |
| `src/canva_client.py` | token refresh, autofill job, export job, download |
| `src/media.py` | commit the PNG to the assets repo, return its raw URL |
| `src/notion_client.py` | create / query / update the Marketing Content Queue |
| `src/scheduling.py` | pure logic: items + horizon → dated post slots |
| `src/metricool_client.py` | normalize media, create scheduled post |
| `src/pipeline.py` | orchestration + CLI (`generate` / `publish`) |
| `scripts/smoke.py` | manual real-credential dry-run check |
| `.github/workflows/publish.yml` | the free scheduled trigger |

## What still needs a human

- Approving content in Notion (unless `APPROVAL_MODE=auto`) — this pipeline handles the
  repeatable mechanics of an approved concept, not review of net-new ideas.
- Re-authorizing Canva if you revoke the integration or change scopes.
- Editing `CANVA_BRAND_TEMPLATE_ID` / field names if you change templates.
