# Build status — Phase 1

**As of:** 2026-09-05, built autonomously while JP was out. Branch: `feat/phase-1-pipeline`.
**Tests:** 69 passing (`pytest`), every module covered, all HTTP mocked.

## What is built and tested

| Module | State |
|---|---|
| `src/config.py` | ✅ loads/validates all env vars, reports every gap at once |
| `src/compliance.py` | ✅ 10 healthcare-advertising guardrails (CQC, cures, diagnosis, meds, superiority, Trustpilot) |
| `src/scheduling.py` | ✅ pure multi-week spread, funnel mix, weekend skip, past-clamp, BOFU spacing |
| `src/canva_client.py` | ✅ token refresh (+rotation callback), autofill, export, download, `render()` |
| `src/notion_client.py` | ✅ create/query/mark rows, approval-mode-aware querying, auto-adds `Metricool ID` + `Funnel Stage` |
| `src/media.py` | ✅ commits PNG to public assets repo, returns raw URL; token passed via http header, redacted from errors |
| `src/metricool_client.py` | ✅ v2 scheduler: normalize media, create post, list posts |
| `src/content.py` | ✅ brief planning from funnel mix, Claude forced-tool call, compliance retry-then-drop |
| `src/pipeline.py` | ✅ `generate`/`publish` CLI, per-item failure isolation, `--dry-run` on both |
| `.github/workflows/publish.yml` | ✅ cron `publish` + manual `generate`/`publish` dispatch |
| `scripts/smoke.py` | ✅ manual 1-item real-credential dry-run |

## Not done / not possible without JP

1. **No live run has happened.** No credentials in this environment.
2. **⚠ Canva Autofill API may require Canva Enterprise.** Canva's docs say the acting user
   must be on Enterprise (or a limited dev trial). If JP's Canva is Pro, autofill may fail
   with `feature_not_available` — this would block the whole approach and needs checking first.
3. **Metricool payload shape** was reverse-engineered from Metricool's public CLI wrapper,
   not their official API docs. Verify field names (`providers`, `publicationDate`,
   `autoPublish`) on the first real `publish --dry-run` against a test blog.
4. **`gmb` network key** for Google Business Profile is assumed — confirm against the
   connected Metricool account.
5. Manual steps in `README.md` §1–7: Canva template tagging, OAuth, Notion integration,
   Metricool token, public assets repo, Anthropic key.
6. **Notion approval default:** shipped as `APPROVAL_MODE=review`. Change the Actions
   variable to `auto`/`veto` when trust is established.

## Rulings made autonomously (also in the spec §10)

1. Direct TDD build, not the subagent-dispatch ceremony (JP away, cheaper). — cost if wrong: none structural.
2. Branch `feat/phase-1-pipeline`, not `main`. — trivial to merge/rebase.
3. Media = PNGs in a separate **public** repo. — swap `media.py` for S3/Cloudinary if disliked; isolated.
4. `APPROVAL_MODE=review` default. — one variable to change.
5. Funnel→Content Type map: TOFU→Educational Short, MOFU→General Post, BOFU→Ad. — cosmetic.
6. Client auto-creates `Metricool ID` + `Funnel Stage` Notion properties. — make manual if disliked.
7. CLI is `generate`/`publish` subcommands. — documented in README.
8. A twice-non-compliant generated item is dropped (logged), batch continues. — quiet gap; alternative is fail-loud.
9. Default networks `twitter,facebook,instagram,gmb`. — verify against Metricool; one variable.
10. Canva token via `http.extraheader` + error redaction (security fix from commit review).

## Suggested next actions for JP

1. Check Canva account tier vs the Autofill API requirement — **do this before anything else**.
2. `pip install -r requirements-dev.txt && pytest` to see it green locally.
3. Work through README §1–7, then `python -m scripts.smoke`.
4. `python -m src.pipeline generate --count 3 --dry-run`, eyeball `./out/*.png` and the logged copy.
5. If happy: push secrets/variables, merge `feat/phase-1-pipeline`, let the cron run `publish`.
