"""مبانيك | Mabaniq — طبقة البيانات.

التعدد (Multi-tenancy): لكل مطوّر قاعدة بيانات مستقلة (عزل مادي كامل للبيانات).
يُحدَّد المطوّر من سياق الطلب (TENANT)، ولا يمكن لجلسة مطوّر أن تُقرأ في قاعدة مطوّر آخر.
SQLite في هذا الإصدار؛ PostgreSQL مع تشفير القرص في الإنتاج.
"""
import contextvars
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path

from . import dbx

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "mabaniq.db"
DEFAULT_TENANT = "jadwa"
TENANT = contextvars.ContextVar("tenant", default=DEFAULT_TENANT)
TENANT_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")


def base_db() -> Path:
    return Path(os.environ.get("MABANIQ_DB", str(DEFAULT_DB)))


def data_dir() -> Path:
    d = base_db().parent
    d.mkdir(parents=True, exist_ok=True)
    return d


def tenants() -> dict:
    f = data_dir() / "tenants.json"
    if not f.exists():
        f.write_text(json.dumps({"jadwa": "جدوى للتطوير (بيانات تجريبية)",
                                 "nahda": "النهضة للتطوير العقاري (مطوّر تجريبي ثانٍ)"}, ensure_ascii=False, indent=1))
    return json.loads(f.read_text())


def valid_tenant(code: str) -> bool:
    return bool(code) and bool(TENANT_RE.match(code)) and code in tenants()


def db_path(tenant: str | None = None) -> str:
    t = tenant or TENANT.get()
    if t == DEFAULT_TENANT:
        return str(base_db())
    if not TENANT_RE.match(t):
        raise ValueError("bad tenant")
    return str(data_dir() / f"tenant_{t}.db")


OPEN = contextvars.ContextVar("open_conns", default=None)  # Unit 4: every connection opened inside a request is closed with it


def connect(tenant: str | None = None):
    """Unit 1: one entry point for both engines (sqlite file per tenant, or PostgreSQL with RLS per tenant).
    Unit 4: when a request-scoped list is active (set by the app middleware) the connection is registered in it, so
    auth/business code that forgets `close()` still returns its pooled connection at the end of the request."""
    t = tenant or TENANT.get()
    c = dbx.connect(t) if dbx.is_postgres() else dbx.connect(t, db_path(t))
    lst = OPEN.get()
    if lst is not None:
        lst.append(c)
    return c


SCHEMA = """
CREATE TABLE IF NOT EXISTS projects(
  id INTEGER PRIMARY KEY, code TEXT UNIQUE, name TEXT, location TEXT, kind TEXT,
  build_pct REAL, planned_monthly_sales REAL, handover TEXT, land_id INTEGER, completed INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS units(
  id INTEGER PRIMARY KEY, project_id INTEGER REFERENCES projects(id), code TEXT UNIQUE,
  building TEXT, floor INTEGER, pos INTEGER, type TEXT, area REAL, view TEXT,
  price REAL, status TEXT CHECK(status IN ('a','r','s')), retained INTEGER DEFAULT 0, use TEXT DEFAULT 'residential');
CREATE TABLE IF NOT EXISTS customers(
  id INTEGER PRIMARY KEY, name TEXT, phone TEXT, created TEXT, rescheduled INTEGER DEFAULT 0,
  id_type TEXT, id_number TEXT, nationality TEXT, id_expiry TEXT, dob TEXT, pep INTEGER DEFAULT 0,
  source_of_funds TEXT, kyc_status TEXT DEFAULT 'pending', kyc_risk TEXT, kyc_note TEXT, kyc_at TEXT,
  consent_at TEXT, email TEXT, consent_version TEXT, consent_source TEXT, erased_at TEXT);
CREATE TABLE IF NOT EXISTS leads(
  id INTEGER PRIMARY KEY, name TEXT, phone TEXT, interest TEXT, project_id INTEGER REFERENCES projects(id),
  channel TEXT, stage INTEGER, interactions INTEGER, budget REAL, created TEXT, last_contact TEXT, score INTEGER,
  broker_id INTEGER, bedrooms INTEGER);
CREATE TABLE IF NOT EXISTS bookings(
  id INTEGER PRIMARY KEY, unit_id INTEGER REFERENCES units(id), customer_id INTEGER REFERENCES customers(id),
  lead_id INTEGER, plan TEXT, price REAL, status TEXT CHECK(status IN ('pending','confirmed','cancelled')),
  created TEXT, expires TEXT, broker_id INTEGER, list_price REAL, handed_over TEXT);
CREATE TABLE IF NOT EXISTS installments(
  id INTEGER PRIMARY KEY, booking_id INTEGER REFERENCES bookings(id), seq INTEGER, label TEXT,
  due_date TEXT, amount REAL, paid_amount REAL DEFAULT 0, paid_date TEXT, penalty_waived INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS contractors(id INTEGER PRIMARY KEY, name TEXT, cr_number TEXT);
CREATE TABLE IF NOT EXISTS ipcs(
  id INTEGER PRIMARY KEY, project_id INTEGER REFERENCES projects(id), contractor_id INTEGER REFERENCES contractors(id),
  no INTEGER, stage TEXT, claimed_pct REAL, stage_value REAL, status TEXT, approved_pct REAL, created TEXT);
CREATE TABLE IF NOT EXISTS ipc_items(
  id INTEGER PRIMARY KEY, ipc_id INTEGER REFERENCES ipcs(id), item TEXT, weight REAL, verified_pct REAL, evidence INTEGER,
  verified_by TEXT, method TEXT DEFAULT 'engineer');
CREATE TABLE IF NOT EXISTS cost_schedule(
  id INTEGER PRIMARY KEY, project_id INTEGER REFERENCES projects(id), month TEXT, amount REAL, label TEXT);
CREATE TABLE IF NOT EXISTS decisions_log(key TEXT PRIMARY KEY, action TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, at TEXT, actor TEXT, action TEXT, detail TEXT, prev_hash TEXT, hash TEXT);
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS service_requests(
  id INTEGER PRIMARY KEY, booking_id INTEGER REFERENCES bookings(id), category TEXT, description TEXT,
  status TEXT CHECK(status IN ('new','in_progress','done')), created TEXT, updated TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS resale(
  id INTEGER PRIMARY KEY, booking_id INTEGER REFERENCES bookings(id), ask_price REAL, fee REAL,
  status TEXT CHECK(status IN ('pending','listed','rejected','sold')), created TEXT);
CREATE TABLE IF NOT EXISTS payments(
  id INTEGER PRIMARY KEY, installment_id INTEGER REFERENCES installments(id), amount REAL, at TEXT, method TEXT, receipt TEXT,
  gateway_ref TEXT UNIQUE, reconciled INTEGER DEFAULT 0);

-- الأراضي والجدوى
CREATE TABLE IF NOT EXISTS lands(
  id INTEGER PRIMARY KEY, name TEXT, location TEXT, area REAL, zoning TEXT, far REAL, max_floors INTEGER,
  price REAL, status TEXT, lat REAL, lng REAL, notes TEXT);
CREATE TABLE IF NOT EXISTS feasibility(
  id INTEGER PRIMARY KEY, land_id INTEGER, name TEXT, inputs TEXT, results TEXT, created TEXT, by TEXT);

-- التراخيص والجهات
CREATE TABLE IF NOT EXISTS permits(
  id INTEGER PRIMARY KEY, project_id INTEGER, authority TEXT, kind TEXT, ref TEXT, status TEXT,
  applied TEXT, issued TEXT, expires TEXT, notes TEXT);

-- الإنشاء
CREATE TABLE IF NOT EXISTS contracts_c(
  id INTEGER PRIMARY KEY, project_id INTEGER, contractor_id INTEGER, value REAL, retention_pct REAL,
  delay_penalty_per_day REAL, start TEXT, finish TEXT);
CREATE TABLE IF NOT EXISTS schedule_tasks(
  id INTEGER PRIMARY KEY, project_id INTEGER, name TEXT, planned_start TEXT, planned_end TEXT,
  actual_start TEXT, actual_end TEXT, pct REAL, depends_on INTEGER, weight REAL);
CREATE TABLE IF NOT EXISTS change_orders(
  id INTEGER PRIMARY KEY, project_id INTEGER, no INTEGER, title TEXT, reason TEXT, cost REAL, days INTEGER,
  status TEXT, requested TEXT, decided TEXT, decided_by TEXT);
CREATE TABLE IF NOT EXISTS site_reports(
  id INTEGER PRIMARY KEY, project_id INTEGER, day TEXT, workers INTEGER, weather TEXT, work_done TEXT,
  issues TEXT, photos INTEGER, by TEXT);
CREATE TABLE IF NOT EXISTS ncrs(
  id INTEGER PRIMARY KEY, project_id INTEGER, title TEXT, severity TEXT, status TEXT, raised TEXT, closed TEXT, location TEXT);
CREATE TABLE IF NOT EXISTS budgets(
  id INTEGER PRIMARY KEY, project_id INTEGER, category TEXT, amount REAL);

-- المبيعات: العقود والتوقيع والخصومات والوسطاء
CREATE TABLE IF NOT EXISTS sale_contracts(
  id INTEGER PRIMARY KEY, booking_id INTEGER UNIQUE, number TEXT, body TEXT, sha256 TEXT, status TEXT,
  created TEXT, customer_signed_at TEXT, customer_sig TEXT, developer_signed_at TEXT, developer_sig TEXT);
CREATE TABLE IF NOT EXISTS discount_requests(
  id INTEGER PRIMARY KEY, booking_id INTEGER, pct REAL, reason TEXT, status TEXT, requested_by TEXT,
  decided_by TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS brokers(
  id INTEGER PRIMARY KEY, name TEXT, license_no TEXT, phone TEXT, rate REAL, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS commissions(
  id INTEGER PRIMARY KEY, broker_id INTEGER, booking_id INTEGER UNIQUE, amount REAL, status TEXT, paid_at TEXT);
CREATE TABLE IF NOT EXISTS watchlist(id INTEGER PRIMARY KEY, name TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS resale_offers(
  id INTEGER PRIMARY KEY, resale_id INTEGER, buyer_name TEXT, buyer_phone TEXT, price REAL, status TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS viewings(
  id INTEGER PRIMARY KEY, lead_id INTEGER, project_id INTEGER, at TEXT, status TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS wa_messages(
  id INTEGER PRIMARY KEY, phone TEXT, direction TEXT, body TEXT, at TEXT, lead_id INTEGER, engine TEXT);

-- المالية
CREATE TABLE IF NOT EXISTS invoices(
  id INTEGER PRIMARY KEY, number TEXT UNIQUE, kind TEXT, ref_type TEXT, ref_id INTEGER, customer TEXT,
  net REAL, vat_rate REAL, vat REAL, total REAL, issued TEXT, note TEXT, customer_id INTEGER REFERENCES customers(id));
CREATE INDEX IF NOT EXISTS ix_inv_customer ON invoices(customer_id);
CREATE TABLE IF NOT EXISTS refunds(
  id INTEGER PRIMARY KEY, booking_id INTEGER, paid REAL, deducted REAL, refund REAL, status TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS pay_intents(
  id TEXT PRIMARY KEY, installment_id INTEGER, amount REAL, status TEXT, created TEXT, provider TEXT);
CREATE TABLE IF NOT EXISTS bank_lines(
  id INTEGER PRIMARY KEY, day TEXT, amount REAL, reference TEXT, matched_payment INTEGER, imported TEXT);
CREATE TABLE IF NOT EXISTS distributions(
  id INTEGER PRIMARY KEY, project_id INTEGER, investor TEXT, amount REAL, day TEXT, note TEXT);

-- ما بعد البيع
CREATE TABLE IF NOT EXISTS snags(
  id INTEGER PRIMARY KEY, booking_id INTEGER, item TEXT, location TEXT, status TEXT, raised TEXT, closed TEXT);
CREATE TABLE IF NOT EXISTS handovers(
  id INTEGER PRIMARY KEY, booking_id INTEGER UNIQUE, appointment TEXT, status TEXT, certificate_no TEXT,
  handed_at TEXT, warranty_until TEXT, structural_until TEXT, meter_readings TEXT, keys INTEGER);
CREATE TABLE IF NOT EXISTS titles(
  id INTEGER PRIMARY KEY, booking_id INTEGER UNIQUE, status TEXT, fee REAL, applied TEXT, deed_no TEXT, issued TEXT);
CREATE TABLE IF NOT EXISTS fm_assets(
  id INTEGER PRIMARY KEY, project_id INTEGER, name TEXT, category TEXT, last_service TEXT, interval_days INTEGER,
  installed TEXT);
CREATE TABLE IF NOT EXISTS work_orders(
  id INTEGER PRIMARY KEY, asset_id INTEGER, kind TEXT, title TEXT, due TEXT, status TEXT, done TEXT, cost REAL);
CREATE TABLE IF NOT EXISTS oa_budget(
  id INTEGER PRIMARY KEY, project_id INTEGER, year INTEGER, line TEXT, amount REAL);
CREATE TABLE IF NOT EXISTS oa_charges(
  id INTEGER PRIMARY KEY, project_id INTEGER, booking_id INTEGER, year INTEGER, amount REAL, paid REAL DEFAULT 0, issued TEXT);
CREATE TABLE IF NOT EXISTS oa_motions(
  id INTEGER PRIMARY KEY, project_id INTEGER, title TEXT, opened TEXT, closes TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS oa_votes(
  motion_id INTEGER, booking_id INTEGER, vote TEXT, weight REAL, at TEXT, PRIMARY KEY(motion_id, booking_id));
CREATE TABLE IF NOT EXISTS tenants_l(
  id INTEGER PRIMARY KEY, name TEXT, phone TEXT, id_number TEXT);
CREATE TABLE IF NOT EXISTS leases(
  id INTEGER PRIMARY KEY, unit_id INTEGER, tenant_id INTEGER, start TEXT, end TEXT, annual_rent REAL,
  frequency INTEGER, deposit REAL, status TEXT, municipality_ref TEXT);
CREATE TABLE IF NOT EXISTS rent_dues(
  id INTEGER PRIMARY KEY, lease_id INTEGER, due TEXT, amount REAL, paid REAL DEFAULT 0, paid_date TEXT);

-- المؤسسية
CREATE TABLE IF NOT EXISTS documents(
  id INTEGER PRIMARY KEY, ref_type TEXT, ref_id INTEGER, title TEXT, category TEXT, filename TEXT, mime TEXT,
  size INTEGER, sha256 TEXT, stored TEXT, uploaded_by TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS notifications(
  id INTEGER PRIMARY KEY, audience TEXT, customer_id INTEGER, channel TEXT, title TEXT, body TEXT,
  status TEXT, created TEXT, dedupe TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS api_keys(
  id INTEGER PRIMARY KEY, name TEXT, key_hash TEXT UNIQUE, prefix TEXT, created TEXT, last_used TEXT, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS reset_tokens(token_hash TEXT PRIMARY KEY, user_id INTEGER, expires REAL, used INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS quotes(
  id INTEGER PRIMARY KEY, number TEXT UNIQUE, unit_id INTEGER REFERENCES units(id), customer_name TEXT, phone TEXT, email TEXT, plan TEXT,
  list_price REAL, discount_pct REAL DEFAULT 0, price REAL, valid_until TEXT, status TEXT DEFAULT 'issued', schedule TEXT, notes TEXT,
  created TEXT, created_by TEXT, booking_id INTEGER, lead_id INTEGER);
CREATE TABLE IF NOT EXISTS doc_issues(
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, ref_id INTEGER NOT NULL, number TEXT, verify_code TEXT UNIQUE NOT NULL, sha256 TEXT, issued TEXT, issued_by TEXT, revised TEXT,
  UNIQUE(kind, ref_id));
CREATE TABLE IF NOT EXISTS doc_sends(id INTEGER PRIMARY KEY, kind TEXT, ref_id INTEGER, channel TEXT, recipient TEXT, sent_by TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS share_links(token_hash TEXT PRIMARY KEY, kind TEXT, ref_id INTEGER, expires REAL, created REAL, created_by TEXT, opened INTEGER DEFAULT 0, last_open TEXT);
CREATE TABLE IF NOT EXISTS plans(
  id INTEGER PRIMARY KEY, project_id INTEGER REFERENCES projects(id), building TEXT, floor INTEGER, unit_type TEXT, kind TEXT NOT NULL, title TEXT,
  document_id INTEGER REFERENCES documents(id), markers TEXT DEFAULT '[]', public INTEGER DEFAULT 1, created TEXT, created_by TEXT);
CREATE TABLE IF NOT EXISTS privacy_requests(
  id INTEGER PRIMARY KEY, customer_id INTEGER, kind TEXT, status TEXT, created TEXT, note TEXT, decided_at TEXT, decided_by TEXT, decision_note TEXT);

-- 0.5.0 — M4: تبرعات التأخير (شرط التبرع) — لا تُقيَّد إيرادًا للمطوّر أبدًا
CREATE TABLE IF NOT EXISTS charity_dues(
  id INTEGER PRIMARY KEY, installment_id INTEGER UNIQUE REFERENCES installments(id), customer_id INTEGER, amount REAL, rate REAL,
  late_days INTEGER, computed_at TEXT, status TEXT CHECK(status IN ('due','collected','disbursed','waived')) DEFAULT 'due',
  collected_at TEXT, collected_ref TEXT, disbursed_at TEXT, beneficiary TEXT, disbursed_ref TEXT);
-- 0.5.0 — M8: تسوية التنازل في السوق الثانوي بين البائع والمشتري
CREATE TABLE IF NOT EXISTS resale_settlements(
  id INTEGER PRIMARY KEY, resale_id INTEGER UNIQUE, booking_id INTEGER, seller_customer_id INTEGER, buyer_customer_id INTEGER,
  price REAL, seller_paid REAL, unpaid_installments REAL, equity_due_to_seller REAL, fee REAL,
  status TEXT CHECK(status IN ('open','settled')) DEFAULT 'open', created TEXT, settled_at TEXT, reference TEXT, settled_by TEXT);

CREATE INDEX IF NOT EXISTS ix_units_project ON units(project_id);
CREATE INDEX IF NOT EXISTS ix_inst_booking ON installments(booking_id);
CREATE INDEX IF NOT EXISTS ix_book_unit ON bookings(unit_id);
CREATE INDEX IF NOT EXISTS ix_book_customer ON bookings(customer_id);

-- سجل التدقيق غير قابل للتعديل أو الحذف
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
"""

# أعمدة أُضيفت بعد الإصدار 0.2 — ترقية تلقائية لقواعد البيانات القائمة
MIGRATIONS = {
    "projects": ["land_id INTEGER", "completed INTEGER DEFAULT 0"],
    "units": ["retained INTEGER DEFAULT 0", "use TEXT DEFAULT 'residential'"],
    "customers": ["id_type TEXT", "id_number TEXT", "nationality TEXT", "id_expiry TEXT", "dob TEXT", "pep INTEGER DEFAULT 0",
                  "source_of_funds TEXT", "kyc_status TEXT DEFAULT 'pending'", "kyc_risk TEXT", "kyc_note TEXT", "kyc_at TEXT",
                  "consent_at TEXT", "email TEXT"],
    "leads": ["broker_id INTEGER", "bedrooms INTEGER"],
    "bookings": ["broker_id INTEGER", "list_price REAL", "handed_over TEXT"],
    "installments": ["penalty_waived INTEGER DEFAULT 0"],
    "contractors": ["cr_number TEXT"],
    "ipc_items": ["verified_by TEXT", "method TEXT DEFAULT 'engineer'"],
    "audit": ["prev_hash TEXT", "hash TEXT"],
    "payments": ["gateway_ref TEXT", "reconciled INTEGER DEFAULT 0"],
    "invoices": ["customer_id INTEGER"],  # 0.4.1 — M1: الفواتير تُربط بمعرّف العميل لا باسمه
    "privacy_requests": ["decided_at TEXT", "decided_by TEXT", "decision_note TEXT"],  # 0.5.0 — M5
}
MIGRATIONS["customers"] += ["consent_version TEXT", "consent_source TEXT", "erased_at TEXT"]  # 0.5.0 — M5


def init(c) -> None:
    if c.dialect == "postgres":  # schema comes from db/migrations (applied in dbx on first connection)
        from .pii import encrypt_existing
        encrypt_existing(c)
        c.commit()
        return
    for table, cols in MIGRATIONS.items():
        have = c.columns(table)
        if have:
            for col in cols:
                if col.split()[0] not in have:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {col}")
    c.executescript(SCHEMA)
    from .pii import encrypt_existing  # noqa: E402 — استيراد متأخر لتجنب الدور
    encrypt_existing(c)
    c.commit()


def setting(c, k, default=None):
    r = c.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()
    return r["v"] if r else default


def setting_f(c, k, default=0.0) -> float:
    try:
        return float(setting(c, k, default))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- سجل تدقيق بسلسلة بصمات
def _h(prev, at, actor, action, detail) -> str:
    return hashlib.sha256("\x1f".join([prev or "", at, actor or "", action or "", detail or ""]).encode()).hexdigest()


def audit_insert(c, actor, action, detail) -> None:
    at = dt.datetime.now().isoformat(timespec="seconds")
    prev = c.execute("SELECT hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
    prev = prev["hash"] if prev else ""
    c.execute("INSERT INTO audit(at,actor,action,detail,prev_hash,hash) VALUES(?,?,?,?,?,?)",
              (at, actor, action, detail, prev, _h(prev, at, actor, action, detail)))


def audit_verify(c) -> dict:
    prev, n = "", 0
    for r in c.execute("SELECT * FROM audit ORDER BY id"):
        n += 1
        if (r["prev_hash"] or "") != prev or r["hash"] != _h(prev, r["at"], r["actor"], r["action"], r["detail"]):
            return {"ok": False, "entries": n, "broken_at": r["id"]}
        prev = r["hash"]
    return {"ok": True, "entries": n, "head": prev[:16]}


def wipe_for_reseed(c, tables) -> None:
    """إعادة البيانات التجريبية فقط (معطّلة في الإنتاج): تُزال حماية السجل مؤقتًا ثم تُعاد."""
    c.maintenance()
    for t in tables:
        c.execute(c.wipe_sql(t))
    c.commit()
    c.end_maintenance()
    init(c)


def backup(c, reason="manual") -> str:
    if getattr(c, "dialect", "sqlite") == "postgres":
        return "postgres: use pg_dump (docs/RUNBOOK.md §4)"
    d = data_dir() / "backups"
    d.mkdir(exist_ok=True)
    os.chmod(d, 0o700)
    name = f"{TENANT.get()}-{dt.datetime.now():%Y%m%d-%H%M%S}-{reason}.db"
    dst = sqlite3.connect(str(d / name))
    c.backup(dst)
    dst.close()
    os.chmod(d / name, 0o600)
    keep = sorted(d.glob(f"{TENANT.get()}-*.db"))
    for old in keep[:-14]:  # الاحتفاظ بآخر 14 نسخة
        old.unlink()
    return name
