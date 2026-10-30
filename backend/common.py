"""أدوات مشتركة بين الوحدات: الاتصال، المنفّذ، سجل التدقيق."""
import contextvars
import datetime as dt

from fastapi import Depends

from .auth import ensure_schema, need
from .db import TENANT, audit_insert, connect, init  # OPEN lives in db.py since Unit 4 (every connect() registers itself)

ACTOR = contextvars.ContextVar("actor", default="النظام")


def xlock(c, key: str) -> None:
    """0.28.2: a transaction-scoped advisory lock on `key` (PostgreSQL only; SQLite has one writer). Two requests that would read the same balance and both write against it
    (a receipt and a reversal on one lease, two postings with one source_key) queue instead of racing; the lock is released at commit/rollback."""
    if getattr(c, "dialect", "") == "postgres":
        c.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (f"{getattr(c, 'tenant', '')}|{key}",))
_ready: set = set()


def close_all(lst):
    """يُستدعى في نهاية كل طلب: تراجع عن أي معاملة غير مكتملة وإغلاق الاتصالات (يمنع قفل قاعدة البيانات)."""
    for c in lst or []:
        try:
            if c.in_transaction:
                c.rollback()
            c.close()
        except Exception:  # noqa: BLE001
            pass


def db():
    c = connect()  # registered in OPEN by connect()
    t = TENANT.get()
    if t not in _ready:
        init(c)
        ensure_schema(c)
        _ready.add(t)
    return c


def reset_ready():
    _ready.clear()


def act_as(perm):
    """صلاحية + تسجيل اسم المنفّذ في سجل التدقيق."""
    async def dep(u: dict = Depends(need(perm))):
        ACTOR.set(f"{u['name']} ({u['role_label']})")
        return u
    return dep


def audit(c, action, detail, actor=None):
    audit_insert(c, actor or ACTOR.get(), action, detail)


def today() -> dt.date:
    return dt.date.today()


def now_s() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def rows(cur) -> list:
    return [dict(r) for r in cur]
