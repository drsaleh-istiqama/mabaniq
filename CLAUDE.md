# CLAUDE.md — Mabaniq (مبانيك) v1

> **بالعربية:** هذا مستودع منصة «مبانيك» للتطوير العقاري (منتج جدوى). المرجع الأعلى تقييم 2026-10-09 وقرار
> المالك (د. صالح الزهيمي) في اليوم نفسه: **رفع البنية والأمان إلى مستوى «خارطة مشاريع الاستقامة v3»**
> (`C:\istiqama-map`). حالة العمل في `PROGRESS.md` — اقرأه أولًا واستأنف من أول بند غير منجز. القرارات
> المعلّقة على المالك في `docs/OWNER_DECISIONS.md` — **لا تُفترض**.
>
> هذا المستودع **خارج خزنة المعرفة** (`C:\DrSaleh`): قواعد الخزنة (backups/، التوقيع في frontmatter،
> `git vault-commit`) لا تنطبق هنا؛ تنطبق قواعد هذا الملف. ما يُتعلَّم هنا ويستحق البقاء يُدوَّن في الخزنة
> في صفحة `wiki/knowledge/mabaniq-platform-review-v0.4.md` أو صفحة مشروع مستقلة.

## Read first

1. `PROGRESS.md` — units, resume point, lessons.
2. `docs/ARCHITECTURE.md` — target topology, data layer contract, security baseline, decisions D1….
3. `docs/ACCEPTANCE.md` — measurable criteria; every ✅ names the command that proved it.
4. `docs/OWNER_DECISIONS.md` — never assume; use the documented placeholders.
5. `CHANGELOG-0.4.1.md`, `CHANGELOG-0.5.0.md` — what the review fixed and why.

## Binding technical decisions

| Area        | Decision                                                                                                                                         |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| Backend     | Python 3.12 · FastAPI · one data-access layer (`backend/dbx.py`, Unit 1) that runs on PostgreSQL 17 in prod and SQLite in dev/tests.             |
| Isolation   | One database, **row-level security per developer (tenant)** enforced by PostgreSQL, not by application code (Unit 1). Until then: one SQLite file per tenant. |
| Migrations  | `db/migrations/NNNN_name.sql`, append-only; a file applied anywhere is never edited. Local-only shims live outside `db/migrations`.               |
| Secrets     | Environment only (`.env.example` lists every variable). Demo mode may generate secrets under `data/secrets/` (mode 600). Never in the database, never in git. |
| Config      | `backend/config.py` is the only reader of `os.environ`. `settings.validate()` blocks a production start.                                        |
| Security    | CSP `script-src 'self'` (no inline scripts, no inline handlers — delegation via `data-call`), CSRF double-submit on every mutating request, HSTS 2y, COOP/CORP, rate limits, audit hash chain, PII encrypted at rest, server-side authz on every endpoint. |
| Logging     | JSON lines with `request_id`; one access line per request; no PII in logs.                                                                      |
| Frontend    | Arabic RTL first (`dir="rtl" lang="ar"` explicit), Hijri date first in customer-facing pages; Sources in `web/` (plain ESM, 4 entries) built by Vite into `frontend/dist` (git-ignored; the API refuses to start without it). Locale files `web/locales/{ar,en}.json` via `data-i18n`; Tajawal self-hosted; **Western digits only** — `WD()` inside `esc()` normalises every string, `npm run check` rejects Arabic-Indic digits in sources. |
| Finance     | Islamic finance only (owner rule 2026-10-04): no interest income or cost; late payment = charity condition (`charity_dues`), never revenue.      |
| Tests       | pytest (API, security, business modules, regressions per release) · pgTAP for RLS (Unit 1) · Playwright critical path `e2e/` (`npm run e2e`) · k6 (Unit 4). |
| CI/CD       | GitHub Actions `.github/workflows/ci.yml`: quality (ruff · `npm run check` · build · size · audits) · test (SQLite) · test-pg (PostgreSQL + pgTAP + backup→restore drill) · e2e (Playwright) · image. Load: `sh load-tests/run.sh postgres 300` locally (not in CI).                    |
| Version     | Single source `backend/config.py::VERSION`, exposed on `/version` and injected as `MABANIQ_GIT_SHA` by the image build.                         |

## Run locally

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt -r requirements-dev.txt   # Windows
cp .env.example .env
.venv/Scripts/uvicorn backend.app:app --port 8800     # http://localhost:8800 — demo data seeds itself
npm ci && npm run build                                # web bundle → frontend/dist (required before the API starts)
.venv/Scripts/python -m pytest -q tests                # 80 tests
.venv/Scripts/python -m backend.selfcheck              # pre-flight: config, health, headers, CSP, bundle, authz
ruff check backend tests && npm run check && npm run size
npm run e2e                                            # Playwright critical path (local Chrome; CI uses Chromium)
docker compose up --build                              # API + PostgreSQL 17 (API uses PostgreSQL from Unit 1)
```

## Working rules

- Units 0–4 of PROGRESS.md are complete (0.9.0, 2026-10-10). New work starts from the open items at the end of PROGRESS.md and `docs/OWNER_DECISIONS.md`. Do not move on while tests fail.
- One clear commit per completed item; update `PROGRESS.md` in the same commit. Never commit `.env`, `data/`, `.venv/`.
- Code and comments may be Arabic or English; **user-facing text is Arabic** (English through `web/locales/en.json` + `data-i18n`, never hard-coded strings; dynamic strings from the API stay Arabic until the API grows a locale parameter).
- Every write endpoint: server-side permission (`need/act_as`), Pydantic model with bounds, one audit line, one DB connection per request, commit once.
- No new inline `<script>`, no `onclick=`, no external script/style/font hosts (`npm run check` + `test_security.py` enforce it). A new remote origin is a CSP change in `app.py` with a test and a line in `docs/SECURITY_HEADERS.md`.
- Never edit `frontend/dist`; edit `web/` and rebuild. Hashed assets are immutable-cached, pages are `no-store`.
- Read-heavy dashboards go through `backend/cache.py` (`_cached_json` in app.py): per-tenant, 10 s, invalidated by any mutating `/api` request, single-flight. A write done outside the API (script, SQL) is visible after one TTL. Tests run with `MABANIQ_CACHE_TTL=0` (tests/conftest.py).
- PostgreSQL connections come from a pool (`dbx.pool()`); every `connect()` inside a request is registered in `db.OPEN` and closed with it — still call `close()` in scripts and background jobs. `RESET ROLE; RESET ALL` runs on every return to the pool: never rely on session state across requests.
- Financial ledgers have no DELETE for the app role (migration 0003); corrections are new rows. New ledger table → add it to the REVOKE list and to `db/tests/02_unit4_integrity.sql`.
- External identity lives in `backend/identity.py` (+ `backend/mail.py`): flows never create accounts; tokens are hashed, single-use, short-lived; Google state is signed and browser-bound; TOTP accounts are excluded from link/Google sign-in. New e-mail goes through `mail.send` (SMTP or outbox) — never a direct smtplib call elsewhere.
- Reports: ready reports are functions in `reports.READY`; custom reports only through `reports.DATASETS` (whitelisted columns/types/permission) — never interpolate user input into SQL. Charts in the web are `web/charts.js` (SVG); in PDF `backend/pdfcharts.py`.
- Marketing: `project_signals` is the single source of a project's marketing state; offers/messages are checked by `_forbidden_offer` (no interest-bearing incentives); creatives come from `adgen.compose` only (programmatic Arabic text, no people).
- Background work goes through `jobs.tick` (idempotent, multi-worker safe), not new threads or timers.
- Documents: `backend/pdfgen.py` renders, `backend/paperwork.py` decides who may see/send what and registers every issue in `doc_issues`; never store generated PDFs; new document kind → renderer + `render()` branch + `STAFF_PERMS` + portal ownership check + test. Plans go through `plans.py` and the shared `store_upload`.
- Click delegation (`data-call="NS.fn"`) calls `fn` with `this = NS` (`apply`); handlers that use `this.cur` depend on it.
- Retention rules live only in `backend/retention.py` (documented in RUNBOOK §5); a new table with personal data gets a rule there or an explicit "kept because …" note.
- Bash heredocs in this environment corrupt backslashes: write scripts with the Write tool, not `python - <<EOF`.
- Never add a git remote or push without the owner's explicit permission (owner decision 10).
