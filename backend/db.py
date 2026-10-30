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
    out = json.loads(f.read_text())
    from .tenant_profiles import tenants_from_env
    out.update(tenants_from_env())  # 0.13.0: MABANIQ_TENANTS adds organisations without touching the (ephemeral) data dir
    return out


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
  price REAL, status TEXT CHECK(status IN ('a','r','s')), retained INTEGER DEFAULT 0, use TEXT DEFAULT 'residential',
  owner_id INTEGER, lease_state TEXT, parking_bays INTEGER, source TEXT, import_batch TEXT);
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
  id INTEGER PRIMARY KEY, name TEXT, phone TEXT, id_number TEXT, kind TEXT DEFAULT 'individual', cr_number TEXT, tax_no TEXT, rep_name TEXT,
  rep_title TEXT, rep_id_number TEXT, contact_name TEXT, email TEXT, address TEXT, nationality TEXT, id_expiry TEXT, rating TEXT, rating_note TEXT,
  blacklisted INTEGER DEFAULT 0, blacklist_reason TEXT, blacklisted_by TEXT, blacklisted_at TEXT, import_batch TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS leases(
  id INTEGER PRIMARY KEY, unit_id INTEGER, tenant_id INTEGER, start TEXT, end TEXT, annual_rent REAL,
  frequency INTEGER, deposit REAL, status TEXT, municipality_ref TEXT, number TEXT, kind TEXT, signed_at TEXT, prep_free_days INTEGER DEFAULT 0,
  rent_start TEXT, months INTEGER, deposit_state TEXT, charity_clause INTEGER DEFAULT 0, municipality_fee REAL, municipality_date TEXT,
  renewed_from INTEGER, terminated_at TEXT, termination_kind TEXT, termination_note TEXT, source TEXT DEFAULT 'manual', created_by TEXT,
  deposit_deducted REAL, deposit_refund REAL, deposit_settled_at TEXT, deposit_settled_by TEXT);
CREATE TABLE IF NOT EXISTS rent_dues(
  id INTEGER PRIMARY KEY, lease_id INTEGER, due TEXT, amount REAL, paid REAL DEFAULT 0, paid_date TEXT, kind TEXT DEFAULT 'rent', year_no INTEGER, label TEXT, plan_id INTEGER);

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
CREATE TABLE IF NOT EXISTS report_defs(id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, ref TEXT, spec TEXT, params TEXT, owner TEXT, shared INTEGER DEFAULT 1, created TEXT);
CREATE TABLE IF NOT EXISTS report_schedules(id INTEGER PRIMARY KEY, report_id INTEGER REFERENCES report_defs(id), cadence TEXT, hour INTEGER, recipients TEXT, format TEXT, active INTEGER DEFAULT 1,
  next_run TEXT, last_run TEXT, last_error TEXT, created_by TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS campaigns(id INTEGER PRIMARY KEY, project_id INTEGER REFERENCES projects(id), name TEXT NOT NULL, objective TEXT, channels TEXT, audience TEXT, budget REAL DEFAULT 0,
  start_date TEXT, end_date TEXT, offer_text TEXT, message TEXT, status TEXT DEFAULT 'draft', utm TEXT UNIQUE, created_by TEXT, created TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS creatives(id INTEGER PRIMARY KEY, project_id INTEGER REFERENCES projects(id), campaign_id INTEGER, template TEXT, size TEXT, headline TEXT, subline TEXT, cta TEXT, offer TEXT,
  bg_document_id INTEGER, document_id INTEGER, pdf_document_id INTEGER, created_by TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS campaign_sends(id INTEGER PRIMARY KEY, campaign_id INTEGER, channel TEXT, recipient TEXT, lead_id INTEGER, creative_id INTEGER, status TEXT, at TEXT, by_user TEXT);
CREATE TABLE IF NOT EXISTS privacy_requests(
  id INTEGER PRIMARY KEY, customer_id INTEGER, kind TEXT, status TEXT, created TEXT, note TEXT, decided_at TEXT, decided_by TEXT, decision_note TEXT);

-- 0.5.0 — M4: تبرعات التأخير (شرط التبرع) — لا تُقيَّد إيرادًا للمطوّر أبدًا
CREATE TABLE IF NOT EXISTS charity_dues(
  id INTEGER PRIMARY KEY, installment_id INTEGER UNIQUE REFERENCES installments(id), customer_id INTEGER, amount REAL, rate REAL,
  late_days INTEGER, computed_at TEXT, status TEXT CHECK(status IN ('due','collected','disbursed','waived')) DEFAULT 'due',
  collected_at TEXT, collected_ref TEXT, disbursed_at TEXT, beneficiary TEXT, disbursed_ref TEXT, rent_due_id INTEGER, lease_id INTEGER);
-- 0.5.0 — M8: تسوية التنازل في السوق الثانوي بين البائع والمشتري
CREATE TABLE IF NOT EXISTS resale_settlements(
  id INTEGER PRIMARY KEY, resale_id INTEGER UNIQUE, booking_id INTEGER, seller_customer_id INTEGER, buyer_customer_id INTEGER,
  price REAL, seller_paid REAL, unpaid_installments REAL, equity_due_to_seller REAL, fee REAL,
  status TEXT CHECK(status IN ('open','settled')) DEFAULT 'open', created TEXT, settled_at TEXT, reference TEXT, settled_by TEXT);
-- 0.14.0 — طلبات العرض الحي من صفحة الهبوط العامة (backend/landing.py). جدول عام بلا org_id: يعيش في قاعدة المشغّل (jadwa)
-- على SQLite وبلا RLS على PostgreSQL (الترحيل 0007 يوثّق الاستثناء). الاحتفاظ: MABANIQ_RETENTION_DEMO_REQUESTS_DAYS.
CREATE TABLE IF NOT EXISTS demo_requests(
  id INTEGER PRIMARY KEY, created TEXT NOT NULL, name TEXT NOT NULL, company TEXT NOT NULL, email TEXT NOT NULL, phone TEXT NOT NULL,
  projects INTEGER DEFAULT 0, message TEXT, lang TEXT DEFAULT 'ar', ip_hash TEXT, user_agent TEXT, mailed INTEGER DEFAULT 0);

-- 0.20.0 — الوحدات المفعَّلة لكل مؤسسة (backend/registry.py). لا صفوف = الافتراضي من ملف التعريف. تبقى عبر إعادة البذر.
CREATE TABLE IF NOT EXISTS org_modules(
  module TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 1, changed_at TEXT, changed_by TEXT);

-- 0.21.0 — الإيجارات المتكاملة (backend/leasing.py). الدفعات والشيكات دفاتر لا تُعدَّل: التصحيح بحركة معاكسة.
CREATE TABLE IF NOT EXISTS counters(k TEXT PRIMARY KEY, n INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS owners(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT DEFAULT 'own', id_number TEXT, phone TEXT, email TEXT, iban TEXT,
  mgmt_fee_pct REAL DEFAULT 0, mgmt_basis TEXT DEFAULT 'collected', active INTEGER DEFAULT 1, notes TEXT);
CREATE TABLE IF NOT EXISTS unit_meters(
  id INTEGER PRIMARY KEY, unit_id INTEGER REFERENCES units(id), kind TEXT, number TEXT, provider TEXT, shared INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS common_facilities(
  id INTEGER PRIMARY KEY, project_id INTEGER REFERENCES projects(id), name TEXT NOT NULL, kind TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS lease_terms(
  id INTEGER PRIMARY KEY, lease_id INTEGER REFERENCES leases(id), year_no INTEGER NOT NULL, from_date TEXT, to_date TEXT, annual_rent REAL NOT NULL, note TEXT,
  UNIQUE(lease_id, year_no));
CREATE TABLE IF NOT EXISTS lease_events(
  id INTEGER PRIMARY KEY, lease_id INTEGER REFERENCES leases(id), kind TEXT, at TEXT, by_user TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS cheques(
  id INTEGER PRIMARY KEY, direction TEXT DEFAULT 'in', lease_id INTEGER REFERENCES leases(id), due_id INTEGER, number TEXT, bank TEXT, branch TEXT,
  amount REAL NOT NULL, due_date TEXT, received_on TEXT, status TEXT DEFAULT 'held', deposited_on TEXT, cleared_on TEXT, bounce_reason TEXT,
  drawer TEXT, payee TEXT, vendor_id INTEGER, journal_id INTEGER, receipt_no TEXT, created_by TEXT);
CREATE TABLE IF NOT EXISTS rent_payments(
  id INTEGER PRIMARY KEY, due_id INTEGER REFERENCES rent_dues(id), lease_id INTEGER REFERENCES leases(id), amount REAL NOT NULL, paid_on TEXT NOT NULL,
  method TEXT, reference TEXT, cheque_id INTEGER, receipt_no TEXT, recorded_by TEXT, reverses_id INTEGER, note TEXT, created TEXT, import_key TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS ux_leases_number ON leases(number);
CREATE INDEX IF NOT EXISTS ix_rent_payments_due ON rent_payments(due_id);
CREATE INDEX IF NOT EXISTS ix_rent_payments_receipt ON rent_payments(receipt_no);
CREATE INDEX IF NOT EXISTS ix_cheques_lease ON cheques(lease_id);

-- 0.22.0 — عمليات الإيجار (backend/leasing_ops.py، backend/importer.py): التسليم والإنذارات وخطط السداد والصيانة والمصاريف وكشوف الملاك والنطاقات والاستيراد.
CREATE TABLE IF NOT EXISTS lease_handovers(
  id INTEGER PRIMARY KEY, lease_id INTEGER REFERENCES leases(id), kind TEXT NOT NULL, at TEXT, by_user TEXT, condition TEXT, keys INTEGER, notes TEXT, deductions TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS meter_readings(
  id INTEGER PRIMARY KEY, handover_id INTEGER REFERENCES lease_handovers(id), meter_id INTEGER, reading REAL NOT NULL);
CREATE TABLE IF NOT EXISTS arrears_notices(
  id INTEGER PRIMARY KEY, lease_id INTEGER REFERENCES leases(id), seq INTEGER, number TEXT NOT NULL UNIQUE, kind TEXT, issued TEXT, cure_by TEXT, amount REAL,
  sent_via TEXT, sent_at TEXT, created_by TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS payment_plans(
  id INTEGER PRIMARY KEY, lease_id INTEGER REFERENCES leases(id), agreed_on TEXT, status TEXT DEFAULT 'active', note TEXT, approved_by TEXT, total REAL, original TEXT);
CREATE TABLE IF NOT EXISTS vendors(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, cr_number TEXT, phone TEXT, email TEXT, trade TEXT, iban TEXT, active INTEGER DEFAULT 1, tax_no TEXT);
CREATE TABLE IF NOT EXISTS maint_requests(
  id INTEGER PRIMARY KEY, unit_id INTEGER REFERENCES units(id), lease_id INTEGER, source TEXT DEFAULT 'staff', requester TEXT, category TEXT, description TEXT,
  priority TEXT DEFAULT 'normal', status TEXT DEFAULT 'new', created TEXT, updated TEXT, sla_due TEXT, closed_at TEXT, created_by TEXT);
CREATE TABLE IF NOT EXISTS maint_orders(
  id INTEGER PRIMARY KEY, request_id INTEGER REFERENCES maint_requests(id), vendor_id INTEGER, scheduled TEXT, cost REAL, charge_to TEXT DEFAULT 'owner',
  tenant_due_id INTEGER, basis TEXT, doc_ref TEXT, done_at TEXT, expense_id INTEGER, created_by TEXT);
CREATE TABLE IF NOT EXISTS property_expenses(
  id INTEGER PRIMARY KEY, project_id INTEGER, unit_id INTEGER, owner_id INTEGER, category TEXT, amount REAL NOT NULL, spent_on TEXT NOT NULL, vendor_id INTEGER,
  order_id INTEGER, charge_owner INTEGER DEFAULT 1, charge_tenant INTEGER DEFAULT 0, description TEXT, status TEXT DEFAULT 'posted', doc_ref TEXT, created_by TEXT);
CREATE TABLE IF NOT EXISTS owner_statements(
  id INTEGER PRIMARY KEY, owner_id INTEGER REFERENCES owners(id), period TEXT NOT NULL, seq INTEGER DEFAULT 1, kind TEXT DEFAULT 'statement', number TEXT NOT NULL UNIQUE,
  collected REAL, expenses REAL, commission REAL, net REAL, status TEXT DEFAULT 'issued', issued_at TEXT, issued_by TEXT, transferred_on TEXT, transfer_ref TEXT, detail TEXT,
  UNIQUE(owner_id, period, seq));
CREATE TABLE IF NOT EXISTS user_scopes(
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, project_id INTEGER, owner_id INTEGER, created_by TEXT);
CREATE TABLE IF NOT EXISTS import_batches(
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, filename TEXT, sha256 TEXT, rows_ok INTEGER, rows_err INTEGER, rows_conflict INTEGER, by_user TEXT, at TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS ux_charity_rent_due ON charity_dues(rent_due_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_rent_payments_import ON rent_payments(import_key);
CREATE INDEX IF NOT EXISTS ix_handovers_lease ON lease_handovers(lease_id);
CREATE INDEX IF NOT EXISTS ix_notices_lease ON arrears_notices(lease_id);
CREATE INDEX IF NOT EXISTS ix_plans_lease ON payment_plans(lease_id);
CREATE INDEX IF NOT EXISTS ix_maint_unit ON maint_requests(unit_id);
CREATE INDEX IF NOT EXISTS ix_expenses_owner ON property_expenses(owner_id, spent_on);
CREATE INDEX IF NOT EXISTS ix_scopes_user ON user_scopes(user_id);

-- 0.23.0 — النواة المحاسبية (backend/ledger.py، backend/accounting.py): دليل الحسابات ومراكز الكلفة والفترات والقيود المزدوجة. القيد المرحَّل لا يُعدَّل ولا يُحذف.
CREATE TABLE IF NOT EXISTS acc_accounts(
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL, name_en TEXT, type TEXT NOT NULL CHECK (type IN ('asset','liability','equity','revenue','expense')),
  parent_id INTEGER REFERENCES acc_accounts(id), postable INTEGER NOT NULL DEFAULT 1, normal TEXT NOT NULL CHECK (normal IN ('debit','credit')), system_key TEXT,
  active INTEGER NOT NULL DEFAULT 1, vat_class TEXT, cash_class TEXT, note TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS ux_acc_accounts_key ON acc_accounts(system_key) WHERE system_key IS NOT NULL;
CREATE TABLE IF NOT EXISTS acc_cost_centers(
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'other' CHECK (kind IN ('property','project','dept','other')),
  ref_id INTEGER, parent_id INTEGER REFERENCES acc_cost_centers(id), active INTEGER NOT NULL DEFAULT 1);
CREATE UNIQUE INDEX IF NOT EXISTS ux_acc_cc_ref ON acc_cost_centers(kind, ref_id) WHERE ref_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS acc_periods(
  id INTEGER PRIMARY KEY, year INTEGER NOT NULL, month INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12), status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','closed')),
  closed_by TEXT, closed_at TEXT, reopened_by TEXT, reopened_at TEXT, reopen_reason TEXT, UNIQUE(year, month));
CREATE TABLE IF NOT EXISTS acc_journals(
  id INTEGER PRIMARY KEY, number TEXT UNIQUE, jdate TEXT NOT NULL, period_id INTEGER REFERENCES acc_periods(id), memo TEXT,
  kind TEXT NOT NULL DEFAULT 'manual' CHECK (kind IN ('manual','auto','opening','reversal')), source_kind TEXT, source_ref TEXT, source_key TEXT,
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','pending','posted','reversed')),
  created_by TEXT, submitted_by TEXT, approved_by TEXT, posted_by TEXT, posted_at TEXT, reversal_of INTEGER, reversed_by INTEGER, reject_note TEXT, total REAL NOT NULL DEFAULT 0);
CREATE UNIQUE INDEX IF NOT EXISTS ux_acc_journals_source ON acc_journals(source_key) WHERE source_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_acc_journals_date ON acc_journals(jdate);
CREATE TABLE IF NOT EXISTS acc_lines(
  id INTEGER PRIMARY KEY, journal_id INTEGER NOT NULL REFERENCES acc_journals(id), line_no INTEGER NOT NULL, account_id INTEGER NOT NULL REFERENCES acc_accounts(id),
  cost_center_id INTEGER REFERENCES acc_cost_centers(id), debit REAL NOT NULL DEFAULT 0, credit REAL NOT NULL DEFAULT 0, party_type TEXT, party_id INTEGER, vat_class TEXT, memo TEXT,
  CHECK (debit >= 0 AND credit >= 0 AND ((debit > 0) <> (credit > 0))));
CREATE INDEX IF NOT EXISTS ix_acc_lines_journal ON acc_lines(journal_id);
CREATE INDEX IF NOT EXISTS ix_acc_lines_account ON acc_lines(account_id);
CREATE INDEX IF NOT EXISTS ix_acc_lines_party ON acc_lines(party_type, party_id);
CREATE TABLE IF NOT EXISTS acc_source_state(
  id INTEGER PRIMARY KEY, source_kind TEXT NOT NULL, source_ref TEXT NOT NULL, posted REAL NOT NULL DEFAULT 0, n INTEGER NOT NULL DEFAULT 0, UNIQUE(source_kind, source_ref));
-- حرّاس القيد (مرآة mabaniq_acc_journal_guard / mabaniq_acc_lines_guard على PostgreSQL)
CREATE TRIGGER IF NOT EXISTS acc_journal_no_delete BEFORE DELETE ON acc_journals WHEN OLD.status <> 'draft'
BEGIN SELECT RAISE(ABORT, 'a posted journal is immutable'); END;
CREATE TRIGGER IF NOT EXISTS acc_journal_frozen BEFORE UPDATE ON acc_journals
WHEN OLD.status IN ('posted','reversed') AND NOT (OLD.status = 'posted' AND NEW.status = 'reversed' AND NEW.number IS OLD.number AND NEW.jdate = OLD.jdate
     AND NEW.total = OLD.total AND NEW.memo IS OLD.memo AND NEW.source_key IS OLD.source_key AND NEW.kind = OLD.kind)
BEGIN SELECT RAISE(ABORT, 'a posted journal is immutable'); END;
CREATE TRIGGER IF NOT EXISTS acc_journal_balance BEFORE UPDATE OF status ON acc_journals WHEN NEW.status = 'posted' AND OLD.status <> 'posted'
BEGIN SELECT RAISE(ABORT, 'journal is not balanced')
  WHERE (SELECT COUNT(*) FROM acc_lines WHERE journal_id = NEW.id) < 2
     OR ABS((SELECT COALESCE(SUM(debit),0) - COALESCE(SUM(credit),0) FROM acc_lines WHERE journal_id = NEW.id)) > 0.0005; END;
CREATE TRIGGER IF NOT EXISTS acc_lines_no_insert BEFORE INSERT ON acc_lines WHEN (SELECT status FROM acc_journals WHERE id = NEW.journal_id) IS NOT 'draft'
BEGIN SELECT RAISE(ABORT, 'a posted journal is immutable'); END;
CREATE TRIGGER IF NOT EXISTS acc_lines_no_update BEFORE UPDATE ON acc_lines WHEN (SELECT status FROM acc_journals WHERE id = OLD.journal_id) IS NOT 'draft'
BEGIN SELECT RAISE(ABORT, 'a posted journal is immutable'); END;
CREATE TRIGGER IF NOT EXISTS acc_lines_no_delete BEFORE DELETE ON acc_lines WHEN (SELECT status FROM acc_journals WHERE id = OLD.journal_id) IS NOT 'draft'
BEGIN SELECT RAISE(ABORT, 'a posted journal is immutable'); END;

-- 0.24.0 — المحاسبة (الاكتمال): الذمم الدائنة وأوامر الدفع، الحسابات البنكية والمطابقة، الضريبة، الأصول والإهلاك، الموازنات، التمويل الإسلامي (هامش معلوم لا فائدة).
CREATE TABLE IF NOT EXISTS bank_accounts(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, bank TEXT, iban TEXT, kind TEXT NOT NULL DEFAULT 'bank' CHECK (kind IN ('bank','cash','escrow','charity')),
  account_id INTEGER NOT NULL REFERENCES acc_accounts(id), currency TEXT NOT NULL DEFAULT 'OMR', islamic INTEGER NOT NULL DEFAULT 1 CHECK (islamic = 1), project_id INTEGER,
  active INTEGER NOT NULL DEFAULT 1, note TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS ux_bank_accounts_gl ON bank_accounts(account_id);
CREATE TABLE IF NOT EXISTS ap_bills(
  id INTEGER PRIMARY KEY, number TEXT UNIQUE, vendor_id INTEGER NOT NULL REFERENCES vendors(id), bill_date TEXT NOT NULL, due_date TEXT, vendor_ref TEXT, description TEXT,
  net REAL NOT NULL DEFAULT 0, vat_class TEXT NOT NULL DEFAULT 'out_of_scope', vat REAL NOT NULL DEFAULT 0, total REAL NOT NULL DEFAULT 0, paid REAL NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','approved','partly_paid','paid','void')), journal_id INTEGER, void_journal_id INTEGER,
  created_by TEXT, approved_by TEXT, approved_at TEXT, void_reason TEXT);
CREATE INDEX IF NOT EXISTS ix_ap_bills_vendor ON ap_bills(vendor_id);
CREATE TABLE IF NOT EXISTS ap_bill_lines(
  id INTEGER PRIMARY KEY, bill_id INTEGER NOT NULL REFERENCES ap_bills(id), line_no INTEGER NOT NULL, account_id INTEGER NOT NULL REFERENCES acc_accounts(id),
  cost_center_id INTEGER REFERENCES acc_cost_centers(id), description TEXT, amount REAL NOT NULL CHECK (amount > 0));
CREATE INDEX IF NOT EXISTS ix_ap_bill_lines_bill ON ap_bill_lines(bill_id);
CREATE TABLE IF NOT EXISTS ap_payments(
  id INTEGER PRIMARY KEY, bill_id INTEGER NOT NULL REFERENCES ap_bills(id), vendor_id INTEGER NOT NULL REFERENCES vendors(id), amount REAL NOT NULL, paid_on TEXT NOT NULL,
  method TEXT NOT NULL, bank_account_id INTEGER REFERENCES bank_accounts(id), cheque_id INTEGER, reference TEXT, order_id INTEGER, journal_id INTEGER, reverses_id INTEGER, created_by TEXT);
CREATE INDEX IF NOT EXISTS ix_ap_payments_bill ON ap_payments(bill_id);
CREATE TABLE IF NOT EXISTS payment_orders(
  id INTEGER PRIMARY KEY, number TEXT UNIQUE, bill_id INTEGER NOT NULL REFERENCES ap_bills(id), vendor_id INTEGER NOT NULL REFERENCES vendors(id), amount REAL NOT NULL CHECK (amount > 0),
  method TEXT NOT NULL, bank_account_id INTEGER NOT NULL REFERENCES bank_accounts(id), reference TEXT, cheque_number TEXT, cheque_due TEXT,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','executed','rejected')), created_by TEXT, approver1 TEXT, approver1_at TEXT, approver2 TEXT, approver2_at TEXT,
  reject_note TEXT, executed_at TEXT, payment_id INTEGER);
CREATE TABLE IF NOT EXISTS bank_stmt_lines(
  id INTEGER PRIMARY KEY, bank_account_id INTEGER NOT NULL REFERENCES bank_accounts(id), line_date TEXT NOT NULL, description TEXT, reference TEXT, amount REAL NOT NULL, balance REAL,
  acc_line_id INTEGER, status TEXT NOT NULL DEFAULT 'unmatched' CHECK (status IN ('unmatched','matched','ignored')), import_key TEXT NOT NULL, file_sha TEXT, matched_by TEXT, matched_at TEXT, note TEXT,
  UNIQUE(bank_account_id, import_key));
CREATE UNIQUE INDEX IF NOT EXISTS ux_bank_stmt_acc_line ON bank_stmt_lines(acc_line_id) WHERE acc_line_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS bank_recons(
  id INTEGER PRIMARY KEY, bank_account_id INTEGER NOT NULL REFERENCES bank_accounts(id), period_end TEXT NOT NULL, statement_balance REAL NOT NULL, book_balance REAL NOT NULL,
  in_transit REAL NOT NULL DEFAULT 0, not_in_books REAL NOT NULL DEFAULT 0, difference REAL NOT NULL DEFAULT 0, closed_by TEXT, closed_at TEXT, UNIQUE(bank_account_id, period_end));
CREATE TABLE IF NOT EXISTS vat_returns(
  id INTEGER PRIMARY KEY, year INTEGER NOT NULL, quarter INTEGER NOT NULL CHECK (quarter BETWEEN 1 AND 4), output_vat REAL NOT NULL DEFAULT 0, input_vat REAL NOT NULL DEFAULT 0,
  net REAL NOT NULL DEFAULT 0, box_values TEXT, status TEXT NOT NULL DEFAULT 'filed' CHECK (status IN ('draft','filed')), filed_on TEXT, ref TEXT, created_by TEXT, journal_id INTEGER,
  UNIQUE(year, quarter));
CREATE TABLE IF NOT EXISTS fixed_assets(
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL, category TEXT, cost REAL NOT NULL CHECK (cost > 0), acquired TEXT NOT NULL, life_months INTEGER NOT NULL CHECK (life_months > 0),
  salvage REAL NOT NULL DEFAULT 0, method TEXT NOT NULL DEFAULT 'straight_line' CHECK (method = 'straight_line'), cost_center_id INTEGER REFERENCES acc_cost_centers(id),
  account_cost INTEGER NOT NULL REFERENCES acc_accounts(id), account_accum INTEGER NOT NULL REFERENCES acc_accounts(id), account_expense INTEGER NOT NULL REFERENCES acc_accounts(id),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','disposed')), disposed_on TEXT, proceeds REAL, disposal_journal_id INTEGER, note TEXT, created_by TEXT);
CREATE TABLE IF NOT EXISTS depreciation_runs(
  id INTEGER PRIMARY KEY, period TEXT NOT NULL, asset_id INTEGER NOT NULL REFERENCES fixed_assets(id), amount REAL NOT NULL, journal_id INTEGER, UNIQUE(asset_id, period));
CREATE TABLE IF NOT EXISTS acc_budgets(
  id INTEGER PRIMARY KEY, year INTEGER NOT NULL, cost_center_id INTEGER REFERENCES acc_cost_centers(id), account_id INTEGER NOT NULL REFERENCES acc_accounts(id),
  month INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12), amount REAL NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS ux_acc_budgets ON acc_budgets(year, COALESCE(cost_center_id, 0), account_id, month);
CREATE TABLE IF NOT EXISTS fin_contracts(
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK (kind IN ('murabaha','ijara','installment','istisna')), counterparty TEXT NOT NULL, principal REAL NOT NULL CHECK (principal > 0),
  markup_total REAL NOT NULL CHECK (markup_total >= 0), start_date TEXT NOT NULL, end_date TEXT, bank_account_id INTEGER REFERENCES bank_accounts(id),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','closed')), drawdown_journal_id INTEGER, note TEXT, created_by TEXT);
CREATE TABLE IF NOT EXISTS fin_installments(
  id INTEGER PRIMARY KEY, contract_id INTEGER NOT NULL REFERENCES fin_contracts(id), no INTEGER NOT NULL, due TEXT NOT NULL, amount REAL NOT NULL, margin REAL NOT NULL, paid_on TEXT,
  payment_journal_id INTEGER, UNIQUE(contract_id, no));

-- 0.25.0 — الموارد البشرية (النواة): الهيكل والموظفون والوثائق والإجازات والحضور وطلبات الموظف. لا راتب هنا (يأتي في 0.26.0).
CREATE TABLE IF NOT EXISTS departments(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, parent_id INTEGER REFERENCES departments(id), head_employee_id INTEGER REFERENCES employees(id),
  cost_center_id INTEGER REFERENCES acc_cost_centers(id), active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS positions(
  id INTEGER PRIMARY KEY, title TEXT NOT NULL, department_id INTEGER REFERENCES departments(id), grade TEXT, headcount INTEGER NOT NULL DEFAULT 1 CHECK (headcount >= 0),
  active INTEGER NOT NULL DEFAULT 1);
CREATE UNIQUE INDEX IF NOT EXISTS ux_positions_title ON positions(title, COALESCE(department_id, 0));
CREATE TABLE IF NOT EXISTS employees(
  id INTEGER PRIMARY KEY, number TEXT NOT NULL UNIQUE, name TEXT NOT NULL, name_en TEXT, nationality TEXT, omani INTEGER NOT NULL DEFAULT 0,
  id_number TEXT, dob TEXT, gender TEXT CHECK (gender IN ('male','female')), marital TEXT CHECK (marital IN ('single','married','divorced','widowed')),
  phone TEXT, email TEXT, address TEXT,
  department_id INTEGER REFERENCES departments(id), position_id INTEGER REFERENCES positions(id), manager_id INTEGER REFERENCES employees(id) CHECK (manager_id IS NOT id),
  hire_date TEXT NOT NULL, contract_type TEXT NOT NULL DEFAULT 'permanent' CHECK (contract_type IN ('permanent','fixed','part')), contract_end TEXT, probation_end TEXT,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','on_leave','terminated')), terminated_on TEXT, termination_note TEXT,
  bank_name TEXT, iban TEXT, social_ins_no TEXT, pasi_applies INTEGER NOT NULL DEFAULT 0, emergency_contact TEXT, created_by TEXT);
CREATE INDEX IF NOT EXISTS ix_employees_dept ON employees(department_id);
CREATE INDEX IF NOT EXISTS ix_employees_manager ON employees(manager_id);
CREATE TABLE IF NOT EXISTS employee_documents(
  id INTEGER PRIMARY KEY, employee_id INTEGER NOT NULL REFERENCES employees(id),
  kind TEXT NOT NULL CHECK (kind IN ('passport','resident_card','work_permit','labour_card','health_insurance','contract','certificate','other')),
  number TEXT, issued TEXT, expires TEXT, document_id INTEGER, note TEXT, created_by TEXT);
CREATE INDEX IF NOT EXISTS ix_employee_documents_emp ON employee_documents(employee_id);
CREATE TABLE IF NOT EXISTS leave_types(
  id INTEGER PRIMARY KEY, key TEXT NOT NULL, name TEXT NOT NULL, paid INTEGER NOT NULL DEFAULT 1, days_per_year REAL NOT NULL DEFAULT 0 CHECK (days_per_year >= 0),
  accrual TEXT NOT NULL DEFAULT 'annual' CHECK (accrual IN ('annual','monthly','event')), carry_over_max REAL NOT NULL DEFAULT 0 CHECK (carry_over_max >= 0),
  needs_doc INTEGER NOT NULL DEFAULT 0, needs_hr INTEGER NOT NULL DEFAULT 0, gender_only TEXT CHECK (gender_only IN ('male','female')), min_service_months INTEGER NOT NULL DEFAULT 0,
  day_count TEXT NOT NULL DEFAULT 'working' CHECK (day_count IN ('working','calendar')), allow_negative INTEGER NOT NULL DEFAULT 0, rules TEXT,
  valid_from TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, provisional INTEGER NOT NULL DEFAULT 1, note TEXT, UNIQUE(key, valid_from));
CREATE TABLE IF NOT EXISTS leave_balances(
  id INTEGER PRIMARY KEY, employee_id INTEGER NOT NULL REFERENCES employees(id), type_key TEXT NOT NULL, year INTEGER NOT NULL,
  entitled REAL NOT NULL DEFAULT 0, taken REAL NOT NULL DEFAULT 0, carried REAL NOT NULL DEFAULT 0, adjusted REAL NOT NULL DEFAULT 0, adj_note TEXT, UNIQUE(employee_id, type_key, year));
CREATE TABLE IF NOT EXISTS leave_requests(
  id INTEGER PRIMARY KEY, employee_id INTEGER NOT NULL REFERENCES employees(id), type_id INTEGER NOT NULL REFERENCES leave_types(id), type_key TEXT NOT NULL,
  from_date TEXT NOT NULL, to_date TEXT NOT NULL, days REAL NOT NULL CHECK (days > 0), reason TEXT,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected','cancelled')), stage TEXT NOT NULL DEFAULT 'manager' CHECK (stage IN ('manager','hr','done')),
  manager_by TEXT, manager_at TEXT, manager_note TEXT, decided_by TEXT, decided_at TEXT, decision_note TEXT, doc_id INTEGER,
  created_by TEXT, cancelled_by TEXT, cancelled_at TEXT, cancel_reason TEXT, CHECK (to_date >= from_date));
CREATE INDEX IF NOT EXISTS ix_leave_requests_emp ON leave_requests(employee_id, from_date);
CREATE TABLE IF NOT EXISTS holidays(id INTEGER PRIMARY KEY, day TEXT NOT NULL UNIQUE, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS attendance(
  id INTEGER PRIMARY KEY, employee_id INTEGER NOT NULL REFERENCES employees(id), day TEXT NOT NULL, check_in TEXT, check_out TEXT,
  status TEXT NOT NULL CHECK (status IN ('present','absent','late','leave','holiday','remote')), source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual','import','device','leave')), note TEXT,
  UNIQUE(employee_id, day));
CREATE TABLE IF NOT EXISTS hr_requests(
  id INTEGER PRIMARY KEY, employee_id INTEGER NOT NULL REFERENCES employees(id), kind TEXT NOT NULL CHECK (kind IN ('letter','advance','other')), details TEXT, amount REAL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected','done')), requested_at TEXT, decided_by TEXT, decided_at TEXT, decision_note TEXT);
CREATE INDEX IF NOT EXISTS ix_hr_requests_emp ON hr_requests(employee_id);

-- 0.26.0 — الرواتب: هياكل الرواتب والمسيّر والقسائم، معدلات التأمينات (لا تُخمَّن)، السلف والقروض الحسنة بلا فائدة، مكافأة نهاية الخدمة والمخالصة.
CREATE TABLE IF NOT EXISTS hr_rates(
  id INTEGER PRIMARY KEY, key TEXT NOT NULL, value REAL, valid_from TEXT NOT NULL, provisional INTEGER NOT NULL DEFAULT 1, note TEXT, created_by TEXT, UNIQUE(key, valid_from));
CREATE TABLE IF NOT EXISTS pay_components(
  id INTEGER PRIMARY KEY, key TEXT NOT NULL UNIQUE, name TEXT NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('earning','deduction')), pasi_base INTEGER NOT NULL DEFAULT 0,
  system INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS salary_structures(
  id INTEGER PRIMARY KEY, employee_id INTEGER NOT NULL REFERENCES employees(id), effective_from TEXT NOT NULL, basic REAL NOT NULL CHECK (basic >= 0), currency TEXT NOT NULL DEFAULT 'OMR',
  note TEXT, created_by TEXT, UNIQUE(employee_id, effective_from));
CREATE TABLE IF NOT EXISTS salary_lines(
  id INTEGER PRIMARY KEY, structure_id INTEGER NOT NULL REFERENCES salary_structures(id), component_id INTEGER NOT NULL REFERENCES pay_components(id), amount REAL NOT NULL CHECK (amount >= 0),
  UNIQUE(structure_id, component_id));
CREATE TABLE IF NOT EXISTS payroll_runs(
  id INTEGER PRIMARY KEY, period TEXT NOT NULL UNIQUE, status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','computed','approved','paid')),
  headcount INTEGER NOT NULL DEFAULT 0, gross REAL NOT NULL DEFAULT 0, net REAL NOT NULL DEFAULT 0, pasi_employee REAL NOT NULL DEFAULT 0, pasi_employer REAL NOT NULL DEFAULT 0,
  blockers INTEGER NOT NULL DEFAULT 0, created_by TEXT, computed_by TEXT, computed_at TEXT, approved_by TEXT, approved_at TEXT, paid_on TEXT, bank_account_id INTEGER REFERENCES bank_accounts(id),
  journal_id INTEGER, payment_journal_id INTEGER, wps_sha TEXT, wps_at TEXT);
CREATE TABLE IF NOT EXISTS payslips(
  id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES payroll_runs(id), employee_id INTEGER NOT NULL REFERENCES employees(id), basic REAL NOT NULL DEFAULT 0, factor REAL NOT NULL DEFAULT 1,
  earnings TEXT, gross REAL NOT NULL DEFAULT 0, absence_days REAL NOT NULL DEFAULT 0, absence_ded REAL NOT NULL DEFAULT 0, adj_earn REAL NOT NULL DEFAULT 0, adj_ded REAL NOT NULL DEFAULT 0,
  pasi_base REAL NOT NULL DEFAULT 0, pasi_employee REAL NOT NULL DEFAULT 0, pasi_employer REAL NOT NULL DEFAULT 0, loan_ded REAL NOT NULL DEFAULT 0, net REAL NOT NULL DEFAULT 0, warnings TEXT,
  cost_center_id INTEGER REFERENCES acc_cost_centers(id), UNIQUE(run_id, employee_id));
CREATE INDEX IF NOT EXISTS ix_payslips_emp ON payslips(employee_id);
CREATE TABLE IF NOT EXISTS payroll_adjustments(
  id INTEGER PRIMARY KEY, employee_id INTEGER NOT NULL REFERENCES employees(id), period TEXT NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('earning','deduction')), name TEXT NOT NULL,
  amount REAL NOT NULL CHECK (amount > 0), note TEXT, created_by TEXT);
CREATE INDEX IF NOT EXISTS ix_payroll_adj_period ON payroll_adjustments(period);
CREATE TABLE IF NOT EXISTS employee_loans(
  id INTEGER PRIMARY KEY, employee_id INTEGER NOT NULL REFERENCES employees(id), kind TEXT NOT NULL CHECK (kind IN ('advance','qard_hasan')), amount REAL NOT NULL CHECK (amount > 0),
  installments INTEGER NOT NULL CHECK (installments >= 1), start_period TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','active','paid','cancelled')),
  reason TEXT, request_id INTEGER, created_by TEXT, approved_by TEXT, approved_at TEXT, disbursed_on TEXT, bank_account_id INTEGER REFERENCES bank_accounts(id), disburse_journal_id INTEGER);
CREATE INDEX IF NOT EXISTS ix_employee_loans_emp ON employee_loans(employee_id);
CREATE TABLE IF NOT EXISTS loan_installments(
  id INTEGER PRIMARY KEY, loan_id INTEGER NOT NULL REFERENCES employee_loans(id), no INTEGER NOT NULL, period TEXT NOT NULL, amount REAL NOT NULL CHECK (amount > 0),
  status TEXT NOT NULL DEFAULT 'due' CHECK (status IN ('due','deducted','waived','settled')), payslip_id INTEGER REFERENCES payslips(id), UNIQUE(loan_id, no));
CREATE TABLE IF NOT EXISTS eosb_rules(
  id INTEGER PRIMARY KEY, grp TEXT NOT NULL CHECK (grp IN ('omani','expat')), valid_from TEXT NOT NULL, tiers TEXT NOT NULL, cap_months REAL, note TEXT, created_by TEXT, UNIQUE(grp, valid_from));
CREATE TABLE IF NOT EXISTS terminations(
  id INTEGER PRIMARY KEY, employee_id INTEGER NOT NULL UNIQUE REFERENCES employees(id), end_date TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('resignation','termination','end_of_contract','retirement','death','other')), note TEXT, status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','approved','paid')),
  service_years REAL NOT NULL DEFAULT 0, last_basic REAL NOT NULL DEFAULT 0, eosb_amount REAL NOT NULL DEFAULT 0, eosb_steps TEXT, leave_days REAL NOT NULL DEFAULT 0, leave_payout REAL NOT NULL DEFAULT 0,
  loans_due REAL NOT NULL DEFAULT 0, other_dues REAL NOT NULL DEFAULT 0, other_deductions REAL NOT NULL DEFAULT 0, net REAL NOT NULL DEFAULT 0, warnings TEXT, clearance TEXT,
  created_by TEXT, approved_by TEXT, approved_at TEXT, paid_on TEXT, bank_account_id INTEGER REFERENCES bank_accounts(id), journal_id INTEGER, payment_journal_id INTEGER);
CREATE TRIGGER IF NOT EXISTS payslip_frozen_i BEFORE INSERT ON payslips WHEN (SELECT status FROM payroll_runs WHERE id = NEW.run_id) NOT IN ('draft','computed')
BEGIN SELECT RAISE(ABORT, 'an approved payslip is immutable'); END;
CREATE TRIGGER IF NOT EXISTS payslip_frozen_u BEFORE UPDATE ON payslips WHEN (SELECT status FROM payroll_runs WHERE id = OLD.run_id) NOT IN ('draft','computed')
BEGIN SELECT RAISE(ABORT, 'an approved payslip is immutable'); END;
CREATE TRIGGER IF NOT EXISTS payslip_frozen_d BEFORE DELETE ON payslips WHEN (SELECT status FROM payroll_runs WHERE id = OLD.run_id) NOT IN ('draft','computed')
BEGIN SELECT RAISE(ABORT, 'an approved payslip is immutable'); END;

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
    "leads": ["broker_id INTEGER", "bedrooms INTEGER", "campaign_id INTEGER", "email TEXT"],
    "bookings": ["broker_id INTEGER", "list_price REAL", "handed_over TEXT"],
    "installments": ["penalty_waived INTEGER DEFAULT 0"],
    "contractors": ["cr_number TEXT"],
    "ipc_items": ["verified_by TEXT", "method TEXT DEFAULT 'engineer'"],
    "audit": ["prev_hash TEXT", "hash TEXT"],
    "payments": ["gateway_ref TEXT", "reconciled INTEGER DEFAULT 0"],
    "invoices": ["customer_id INTEGER"],  # 0.4.1 — M1: الفواتير تُربط بمعرّف العميل لا باسمه
    "privacy_requests": ["decided_at TEXT", "decided_by TEXT", "decision_note TEXT"],  # 0.5.0 — M5
}
MIGRATIONS.update({  # 0.21.0 — الإيجارات المتكاملة: توسعة الجداول القائمة (القواعد الجديدة تحمل الأعمدة في SCHEMA)
    "units": MIGRATIONS["units"] + ["owner_id INTEGER", "lease_state TEXT", "parking_bays INTEGER"],
    "tenants_l": ["kind TEXT DEFAULT 'individual'", "cr_number TEXT", "tax_no TEXT", "rep_name TEXT", "rep_title TEXT", "rep_id_number TEXT", "contact_name TEXT",
                  "email TEXT", "address TEXT", "nationality TEXT", "id_expiry TEXT", "rating TEXT", "rating_note TEXT", "blacklisted INTEGER DEFAULT 0",
                  "blacklist_reason TEXT", "blacklisted_by TEXT", "blacklisted_at TEXT", "import_batch TEXT"],
    "leases": ["number TEXT", "kind TEXT", "signed_at TEXT", "prep_free_days INTEGER DEFAULT 0", "rent_start TEXT", "months INTEGER", "deposit_state TEXT",
               "charity_clause INTEGER DEFAULT 0", "municipality_fee REAL", "municipality_date TEXT", "renewed_from INTEGER", "terminated_at TEXT",
               "termination_kind TEXT", "termination_note TEXT", "source TEXT DEFAULT 'manual'", "created_by TEXT"],
    "rent_dues": ["kind TEXT DEFAULT 'rent'", "year_no INTEGER", "label TEXT"],
})
MIGRATIONS["leases"] += ["deposit_deducted REAL", "deposit_refund REAL", "deposit_settled_at TEXT", "deposit_settled_by TEXT"]  # 0.22.0 — عمليات الإيجار
MIGRATIONS["rent_dues"] += ["plan_id INTEGER"]
MIGRATIONS["units"] += ["source TEXT", "import_batch TEXT"]
MIGRATIONS["tenants_l"] += ["source TEXT"]
MIGRATIONS["vendors"] = ["tax_no TEXT"]  # 0.24.0
MIGRATIONS["rent_payments"] = ["import_key TEXT"]
MIGRATIONS["charity_dues"] = ["rent_due_id INTEGER", "lease_id INTEGER"]
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
