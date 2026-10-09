"""Mabaniq — one data-access layer for two engines (Unit 1).

The business code was written against sqlite3 (`?` placeholders, `Row` objects addressable by index and by name,
`cursor.lastrowid`, `rowcount`). This module keeps that surface and provides it on PostgreSQL as well:

* `connect(tenant)` returns either `SqliteConn` (a thin sqlite3 subclass) or `PgConn` (psycopg 3 wrapper).
  The choice is `settings.database_url`: empty → SQLite file per tenant (development, tests);
  `postgresql://…` → one database, one schema, **row-level security per tenant**.
* On PostgreSQL every connection runs `SET ROLE mabaniq_app` (a role that cannot bypass RLS) and
  `set_config('app.org_id', <tenant>)`; every table has `org_id text DEFAULT current_setting('app.org_id')`
  and a policy `tenant_id = current_setting('app.org_id')`, so the application code never filters by tenant.
* SQL written in the sqlite dialect is translated on the fly (see `translate()`); the few constructs that cannot be
  translated mechanically were rewritten portably in the business code (boolean sums, scalar MIN, date windows).

Both wrappers expose the same extras used by the migration/seeding code:
`dialect`, `columns(table)`, `has_table(table)`, `executescript(sql)`, `in_transaction`, `maintenance()`.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from .config import settings

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "db" / "migrations"
APP_ROLE = "mabaniq_app"

# ---------------------------------------------------------------- shared row type
class Row(tuple):
    """tuple + name access + keys(), like sqlite3.Row (so `dict(row)` and `row["col"]` and `row[0]` all work)."""

    __slots__ = ()
    _fields: tuple = ()

    def __getitem__(self, key):  # type: ignore[override]
        if isinstance(key, str):
            try:
                return tuple.__getitem__(self, self._fields.index(key))
            except ValueError:
                raise IndexError(f"No item with that key: {key}") from None
        return tuple.__getitem__(self, key)

    def keys(self):
        return list(self._fields)

    def get(self, key, default=None):
        try:
            return self[key]
        except IndexError:
            return default


def _row_class(fields: tuple):
    return type("Row", (Row,), {"__slots__": (), "_fields": fields})


# ================================================================ SQLite
class SqliteConn(sqlite3.Connection):
    dialect = "sqlite"

    def columns(self, table: str) -> set[str]:
        return {r[1] for r in self.execute(f"PRAGMA table_info({table})")}

    def has_table(self, table: str) -> bool:
        return bool(self.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())

    def maintenance(self) -> None:
        """Allow the demo reseed to clear the append-only audit table (triggers are re-created by init)."""
        self.execute("DROP TRIGGER IF EXISTS audit_no_update")
        self.execute("DROP TRIGGER IF EXISTS audit_no_delete")

    def end_maintenance(self) -> None:
        return None

    def wipe_sql(self, table: str) -> str:
        return f"DELETE FROM {table}"


def _sqlite_connect(path: str) -> SqliteConn:
    c = sqlite3.connect(path, timeout=15, factory=SqliteConn)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA journal_mode=WAL")
    return c


# ================================================================ PostgreSQL
_SERIAL_TABLES: set[str] | None = None


def serial_tables() -> set[str]:
    """Tables whose `id` is generated (sqlite `id INTEGER PRIMARY KEY`) — INSERTs get `RETURNING id` for lastrowid."""
    global _SERIAL_TABLES
    if _SERIAL_TABLES is None:
        from .auth import USERS_SQL
        from .db import SCHEMA
        out = set()
        for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+)\((.*?)\);", SCHEMA + USERS_SQL, re.S):
            if re.search(r"\bid INTEGER PRIMARY KEY\b", m.group(2)):
                out.add(m.group(1))
        _SERIAL_TABLES = out
    return _SERIAL_TABLES


_INSERT_RE = re.compile(r"^\s*INSERT\s+(OR\s+(IGNORE|REPLACE)\s+)?INTO\s+(\w+)", re.I)


def translate(sql: str) -> tuple[str, str | None, bool]:
    """sqlite SQL → PostgreSQL SQL. Returns (sql, inserted_table_or_None, wants_returning_id)."""
    m = _INSERT_RE.match(sql)
    table, mode = (m.group(3), (m.group(2) or "").upper()) if m else (None, "")
    s = sql.replace("%", "%%").replace("?", "%s")
    returning = False
    if table:
        if mode == "IGNORE":
            s = _INSERT_RE.sub(f"INSERT INTO {table}", s, count=1) + " ON CONFLICT DO NOTHING"
        elif mode == "REPLACE":
            if table != "settings":
                raise ValueError("INSERT OR REPLACE is only supported for settings on PostgreSQL")
            s = _INSERT_RE.sub("INSERT INTO settings(k,v)", s, count=1) + " ON CONFLICT (org_id,k) DO UPDATE SET v=EXCLUDED.v"
        if table in serial_tables() and " RETURNING " not in s.upper():
            s += " RETURNING id"
            returning = True
    return s, table, returning


class PgCursor:
    def __init__(self, cur, lastrowid=None):
        self._cur = cur
        self.lastrowid = lastrowid

    @property
    def rowcount(self):
        return self._cur.rowcount

    def _wrap(self, rec):
        if rec is None:
            return None
        return self._cls(rec)

    def _ensure_cls(self):
        if not hasattr(self, "_cls"):
            desc = self._cur.description or ()
            self._cls = _row_class(tuple(d.name for d in desc))

    def fetchone(self):
        self._ensure_cls()
        return self._wrap(self._cur.fetchone())

    def fetchall(self):
        self._ensure_cls()
        return [self._cls(r) for r in self._cur.fetchall()]

    def __iter__(self):
        self._ensure_cls()
        for r in self._cur:
            yield self._cls(r)


class PgConn:
    dialect = "postgres"

    def __init__(self, raw, tenant: str):
        self._c = raw
        self.tenant = tenant

    # -- sqlite-compatible surface
    def execute(self, sql: str, params=()):
        s, table, returning = translate(sql)
        cur = self._c.cursor()
        cur.execute(s, tuple(params) if not isinstance(params, (list, tuple)) or True else params)
        lastrowid = None
        if returning:
            r = cur.fetchone()
            lastrowid = r[0] if r else None
            return PgCursor(cur, lastrowid)
        return PgCursor(cur)

    def executemany(self, sql: str, seq):
        s, _t, _r = translate(sql)
        cur = self._c.cursor()
        cur.executemany(s, [tuple(p) for p in seq])
        return PgCursor(cur)

    def executescript(self, sql: str):
        """DDL/DML script without parameters (psycopg runs several statements in one call)."""
        self._c.execute(sql)
        self._c.commit()

    def commit(self):
        self._c.commit()

    def rollback(self):
        self._c.rollback()

    def close(self):
        self._c.close()

    @property
    def in_transaction(self) -> bool:
        from psycopg.pq import TransactionStatus
        return self._c.info.transaction_status != TransactionStatus.IDLE

    # -- extras
    def columns(self, table: str) -> set[str]:
        return {r[0] for r in self.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=?", (table,))}

    def has_table(self, table: str) -> bool:
        return bool(self.execute("SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=?", (table,)).fetchone())

    def maintenance(self) -> None:
        """Demo reseed only: leave the RLS-bound app role (it has no DELETE on audit) and raise the transaction-local
        flag the audit guard honours. Deletes issued in this mode MUST be scoped with `wipe_sql()` because the session
        user bypasses row-level security."""
        self.execute("RESET ROLE")
        self.execute("SELECT set_config('app.maintenance','1', true)")

    def end_maintenance(self) -> None:
        self.execute(f"SET ROLE {APP_ROLE}")

    def wipe_sql(self, table: str) -> str:
        return f"DELETE FROM {table} WHERE org_id = current_setting('app.org_id', true)"


_pg_ready: set[str] = set()


def _pg_connect(tenant: str) -> PgConn:
    import psycopg
    from psycopg.types.numeric import FloatLoader
    raw = psycopg.connect(settings.database_url, autocommit=False)
    raw.adapters.register_loader("numeric", FloatLoader)  # SUM(bigint) etc. come back as float like sqlite, not Decimal
    if settings.database_url not in _pg_ready:
        apply_migrations(raw)
        _pg_ready.add(settings.database_url)
    with raw.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (APP_ROLE,))
        if cur.fetchone():
            cur.execute(f"SET ROLE {APP_ROLE}")
        cur.execute("SELECT set_config('app.org_id', %s, false)", (tenant,))
    raw.commit()
    return PgConn(raw, tenant)


def apply_migrations(raw) -> list[str]:
    """Apply db/migrations/*.sql not yet recorded in schema_migrations (runs as the connecting user, before SET ROLE)."""
    applied: list[str] = []
    with raw.cursor() as cur:
        cur.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
        cur.execute("SELECT version FROM schema_migrations")
        done = {r[0] for r in cur.fetchall()}
        for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if f.name in done:
                continue
            cur.execute(f.read_text(encoding="utf-8"))
            cur.execute("INSERT INTO schema_migrations(version) VALUES(%s)", (f.name,))
            applied.append(f.name)
    raw.commit()
    return applied


# ================================================================ public API
def is_postgres() -> bool:
    return settings.database_url.startswith("postgres")


def connect(tenant: str, sqlite_path: str | None = None):
    if is_postgres():
        return _pg_connect(tenant)
    return _sqlite_connect(sqlite_path or settings.sqlite_path)
