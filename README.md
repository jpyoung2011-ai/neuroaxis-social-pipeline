# NeuroAxis Social Pipeline

A small, self-contained automation that:

1. Generates on-brand educational post copy (headline / body / caption) with Claude.
2. Autofills a tagged Canva brand template with that copy via Canva's official **Connect API**.
3. Schedules the resulting image + caption to Instagram/Facebook via the **Metricool API**.

It runs on a schedule for free using **GitHub Actions** — no server, no VPS, no new subscription.
GitHub Actions' free tier covers this easily at a weekly/biweekly cadence on a private repo.

---

## Why it's built this way (read this before assuming something is missing)

- Canva's Connect API requires **OAuth 2.0 with PKCE** — there is no static "API key" you can
  paste in. The one-time authorization has to happen in a real browser, once, on your machine.
  `setup_canva_oauth.py` does this for you locally and prints the values you need.
- Canva access tokens expire after ~4 hours. This project stores the long-lived **refresh token**
  as a GitHub Actions secret, and the pipeline exchanges it for a fresh access token every run.
- Your Canva brand template must already have its text boxes tagged as **data fields** (Canva's
  own UI, one-time, ~5 minutes) — the API can only autofill fields that exist. This is not
  something an API call can do for you; Canva doesn't expose template-tagging over the API.
- Metricool authenticates with a static account token (`X-Mc-Auth` header) — no OAuth dance there.

## One-time setup

### 1. Tag your Canva template for autofill

In Canva, open your existing NeuroAxis post template → for each text box you want to fill
programmatically, right-click → "Add data field" → give it a short name (e.g. `headline`,
`body`, `cta`). Note the **brand template ID** from the share URL
(`canva.com/design/<THIS_PART>/...`).

### 2. Create a Canva integration

1. Go to the [Canva Developer Portal](https://www.canva.com/developers/integrations/connect-api) → **Create an integration**.
2. Note the **Client ID**, click **Generate secret** and save the **Client Secret**.
3. Under **Scopes**, enable: `asset` (read/write), `brandtemplate:content` (read),
   `brandtemplate:meta` (read), `design:content` (read/write), `design:meta` (read), `profile` (read).
4. Under **Authentication → Add Authentication**, set the redirect URL to:
   `http://127.0.0.1:8765/oauth/redirect`

### 3. Run the local OAuth authorization once

```bash
pip install -r requirements.txt
cp .env.example .env
# fill in CANVA_CLIENT_ID and CANVA_CLIENT_SECRET in .env
python setup_canva_oauth.py
```

This opens your browser, you approve the integration once, and the script prints a
`CANVA_REFRESH_TOKEN` value. Put it in `.env` and later in your GitHub repo secrets.

### 4. Get your Metricool token

Metricool → Settings → API → copy your token, `userId`, and `blogId`. Add them to `.env`.

### 5. Get an Anthropic API key

From the [Claude Console](https://console.anthropic.com) — used for writing the post copy.

### 6. Test it locally

```bash
python -m src.pipeline --dry-run
```

`--dry-run` generates copy and builds the Canva design, but does not schedule to Metricool —
use this to sanity-check output before trusting the schedule.

### 7. Push to GitHub and add secrets

Create a **private** repo, push this code, then under
**Settings → Secrets and variables → Actions**, add every value from your `.env` as a secret
(same names). The included workflow (`.github/workflows/publish.yml`) runs on a weekly cron
and calls the pipeline the same way you did locally — for free, on GitHub's infrastructure.

---

## What still needs a human

- Approving new content concepts (per your original brief) — this pipeline is meant for the
  repeatable/bulk case once a concept is approved, not for skipping review of net-new ideas.
- Re-running `setup_canva_oauth.py` if you ever revoke the integration or change scopes.
- Editing `CANVA_BRAND_TEMPLATE_ID` / field names in `.env` if you change templates.

## Files

- `setup_canva_oauth.py` — one-time local OAuth authorization (PKCE flow + local callback server).
- `src/config.py` — loads all credentials/settings from environment variables.
- `src/canva_client.py` — token refresh, create autofill job, poll job, get export URL.
- `src/metricool_client.py` — normalize media URL, create scheduled post.
- `src/content.py` — Claude call that writes headline/body/caption as structured JSON.
- `src/pipeline.py` — wires the above together; entry point for both local runs and CI.
- `.github/workflows/publish.yml` — the free scheduled trigger.
