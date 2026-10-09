# Mabaniq v1 — Architecture & Contracts

> Target: the engineering bar of *Istiqama Projects Map v3* (`C:\istiqama-map/docs/ARCHITECTURE.md`), applied to a
> PropTech back office. This document describes the **target** and marks what already exists (✅), what is in
> progress (🟨) and what is planned (⬜). Progress lives in `PROGRESS.md`.

## 0. Ground rules

- No secrets in the repo; everything configurable in env vars (`.env.example`). `backend/config.py` is the only
  reader of the environment and blocks a production start when anything required is missing. ✅
- Every DB object is created by a numbered file in `db/migrations/` (⬜ Unit 1). Until then `backend/db.py::SCHEMA`
  + `MIGRATIONS` upgrade SQLite in place at start-up. ✅
- Soft delete and standard columns (`created_at`, `updated_at`, `created_by`, `updated_by`, `version`,
  `deleted_at`) on every table (⬜ Unit 1). Today: `created`/`updated` text dates on some tables.
- Isolation of developers (tenants) enforced by the database (RLS), not by code paths (⬜ Unit 1). Today: one
  SQLite file per tenant, selected by the `mbq_tenant` cookie and a context variable. ✅
- The browser talks to the backend only through `/api/*` with cookie session + CSRF token; the staff UI, the
  customer app and the broker portal share one `api()` helper per page. ✅

## 1. Runtime topology

```
Browser (staff SPA · customer app · broker portal — Arabic RTL, no inline JS)
   │  same-origin /api/*  (cookie mbq_session HttpOnly + mbq_csrf double-submit)
   ▼
Reverse proxy (Cloudflare / platform) ── trusted for client ip only from loopback (MABANIQ_TRUST_PROXY)
   ▼
mabaniq-api (uvicorn, container deploy/Dockerfile, non-root, /health /ready /version)
   ├─ ObservabilityMiddleware: request id, JSON access log, JSON 500            ✅ Unit 0
   ├─ security middleware: rate limit → CSRF (origin + token) → size/type caps → headers   ✅
   ├─ routers: app.py (core + auth + portal) · modules.py (land→finance) · modules2.py (post-sale→admin)
   ├─ engines.py / engines_ext.py: explainable rule engines (pricing, default risk, cash radar, feasibility, KYC, WA)
   └─ dbx (⬜ Unit 1): one API over PostgreSQL (prod) / SQLite (dev, tests)
   ▼
PostgreSQL 17 (prod, RLS, pgTAP)  ·  SQLite WAL (dev/tests)
Object storage: `data/docs_store/<tenant>/` on disk today → bucket in Unit 4
```

## 2. Data layer

### 2.1 Today (0.5.0 / 0.6.0)

- 65 tables in `backend/db.py::SCHEMA` (SQLite dialect), parametrised SQL everywhere (417 `?` placeholders,
  512 `execute` calls), one connection per request opened by `common.db()` and closed/rolled back in the
  middleware's `finally`.
- Audit: `audit` table with hash chain (`prev_hash`, `hash`) and `BEFORE UPDATE/DELETE` triggers that abort.
- PII at rest: `customers.id_number`, `customers.dob`, `tenants_l.id_number` encrypted with Fernet
  (`backend/pii.py`, prefix `enc:v1:`), migrated lazily on `init`.

### 2.2 Target (Unit 1) — `backend/dbx.py` contract

```python
with dbx.connection(tenant_id) as c:      # sets `SET LOCAL app.tenant_id = …` on PostgreSQL
    row = c.one("SELECT … WHERE id=:id", id=…)   # named parameters, dialect-neutral
    rows = c.all(…); c.exec(…); new_id = c.insert("table", {...}, returning="id")
    c.upsert("table", {...}, conflict=["installment_id"], update=[...])   # replaces INSERT OR IGNORE/REPLACE
```

- Dialect differences isolated in `dbx.sqlite` / `dbx.postgres`: upsert, `returning`, boolean sums, date
  arithmetic (`julianday` → `date` subtraction), `substr(x,1,7)` → `to_char(date,'YYYY-MM')`.
- PostgreSQL schema in `db/migrations/0001_initial.sql`: every table gets `tenant_id uuid not null`, standard
  columns, `private.tg_std()` trigger, `private.tg_audit()` → `audit_log`; **RLS enabled and forced** with
  `USING (tenant_id = current_setting('app.tenant_id')::uuid)`; the API role has no `DELETE` grant on financial
  tables; `audit_log` has no `UPDATE/DELETE` grants at all.
- pgTAP in `db/tests/*.sql`: for every table — RLS enabled, forced, policy present, cross-tenant read returns 0 rows,
  cross-tenant write raises; audit immutability; charity/invoice/payment invariants (ledger gap = 0).
- Migration of the existing 65-table SQLite model is mechanical but large (see counts above); it is done
  table-group by table-group behind the `dbx` contract so the pytest suite stays green on both engines.

## 3. Security baseline (✅ unless marked)

| Control | Where |
| --- | --- |
| Server-side authorization on every endpoint (`need` / `act_as`), role → permission sets | `backend/auth.py` |
| Password hashing PBKDF2-SHA256 200k, policy ≥ 10 chars, forced change, TOTP with replay guard, MFA mandatory for admin/finance in prod | `auth.py` |
| Lockout persisted in DB (5/5 min per ip+user, 20/15 min per account) + token-bucket rate limits per ip (login, webhook, api) | `auth.py`, `observability.py` |
| CSRF: Origin/Referer check + double-submit token on every mutating `/api/*` | `app.py::_inner` |
| CSP `script-src 'self'`, HSTS 2y, COOP/CORP, X-Frame DENY, nosniff, Permissions-Policy, Referrer same-origin | `app.py`, `docs/SECURITY_HEADERS.md` |
| Request size caps (64 kB JSON, 5.3 MB upload), content-type whitelist, upload magic-byte check, sandboxed download | `app.py`, `modules2.py` |
| Secrets from env or `data/secrets/` (0600); never in DB; production refuses to start without them | `config.py`, `pii.py` |
| PII encryption at rest, masked lists, logged full reads, customer consent with notice version, erasure workflow with legal-hold blockers | `pii.py`, `modules.py`, `modules2.py` |
| Audit hash chain + immutability triggers, `GET /api/audit/verify` | `db.py` |
| Payment webhook: HMAC-SHA256, ±300 s window, idempotent by gateway ref | `modules.py` |
| Structured logs without PII, request id in every 500 | `observability.py` |
| ⬜ Unit 1: RLS per tenant; rate-limit state in DB; `DELETE` grants removed from financial tables |
| ⬜ Unit 2: session rotation on privilege change, device revocation, graded lockout, recovery codes |
| ⬜ Unit 3: `style-src 'self'`, self-hosted fonts, hashed immutable assets, Playwright e2e |
| ⬜ Unit 4: Sentry, backup drill, retention schedule, k6 |

## 4. Business invariants the tests enforce

- Ledger: Σ `installments.paid_amount` = Σ `payments.amount` (`/api/bank.ledger_gap == 0`).
- No sale confirmation before KYC `verified`; no contract before privacy consent; no price change after signature.
- No handover with the buyer's own installments unpaid, with a bank-financing installment unpaid **and no bank
  disbursement letter document**, with open snags, with an unsigned contract, with unverified KYC, or with an open
  resale settlement.
- Late payment never creates revenue: it creates a `charity_dues` row (due → collected → disbursed) exported as
  trust entries.
- Invoices are linked by `customer_id`; the customer portal never matches by name.
- Lease dues sum to `annual_rent / 12 × months`.

## 5. Decisions

| # | Decision | Why |
| --- | --- | --- |
| D1 | Keep FastAPI/Python and add a `dbx` layer instead of rewriting on Frappe | Owner decision 2 pending; 5 000 lines of tested business logic are the asset; Frappe would restart from zero |
| D2 | RLS in one PostgreSQL database instead of one database per tenant | Backups, migrations, cross-tenant reporting and connection pooling; isolation enforced by the engine (map v3 pattern) |
| D3 | Charity condition instead of late-payment penalty revenue | Owner rule: Islamic finance only; the contract clause and the ledger agree |
| D4 | Consent is recorded by the customer (app) or witnessed on paper by staff, never implied by data entry | PDPL: consent must be an act of the data subject |
| D5 | Erasure = pseudonymisation with legal-hold blockers, financial records kept | Oman commercial/tax retention duties |
| D6 | In-memory rate limiter per process in Unit 0 | No shared store yet; documented limit, moved to the DB in Unit 1 |
| D7 | Arabic-Indic digits kept in the UI (unlike map D18) until the owner decides | Existing users of the demo; owner question ب |
