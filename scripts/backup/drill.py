"""Restore drill (Unit 4, acceptance criterion 14, docs/RUNBOOK.md §4) — one command, read-only on the source:

    python scripts/backup/drill.py --source postgresql://…/mabaniq_test --target mabaniq_drill [--keep] [--pgtap]

 1. dump.py       logical backup + manifest (row counts in one snapshot, sha256, pg_restore --list)
 2. restore       into a NEW database named mabaniq_<label> (created here; refused if it exists), pg_restore --no-owner
 3. verify        row count of every table equals the manifest · schema_migrations identical · audit hash chain intact
                  (backend.db.audit_verify on every tenant) · mabaniq_app grants re-applied (GRANT lines of the
                  migrations are not in the dump: `--no-privileges`; the drill re-runs the GRANT/REVOKE statements)
 4. pgtap         (--pgtap) the pgTAP suite on the restored copy
 5. drop          the restored database unless --keep
Writes .local/backup-drill/drill-<stamp>.json with every duration and result. Exit 0 only when every step passed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "backup"))
from dump import dump, pg_bin, row_counts  # noqa: E402


def with_db(url: str, db: str) -> str:
    u = urlsplit(url)
    return urlunsplit((u.scheme, u.netloc, "/" + db, u.query, u.fragment))


def grant_statements() -> list[str]:
    """GRANT/REVOKE lines of the migrations (privileges are not part of the dump)."""
    out = []
    for f in sorted((ROOT / "db" / "migrations").glob("*.sql")):
        for m in re.finditer(r"^\s*(GRANT|REVOKE)\b[^;]*;", f.read_text(encoding="utf-8"), re.M | re.S):
            out.append(m.group(0).strip())
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", default=os.environ.get("MABANIQ_DATABASE_URL", ""))
    ap.add_argument("--target", default="mabaniq_drill")
    ap.add_argument("--out", default=str(ROOT / ".local" / "backups"))
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--pgtap", action="store_true")
    ap.add_argument("--pgtap-sql", default="", help="pgtap.sql to load when the extension is not installed in the cluster (CI)")
    a = ap.parse_args()
    if not a.source.startswith("postgres"):
        ap.error("--source must be a postgresql:// URL")
    if not a.target.startswith("mabaniq_"):
        ap.error("drill databases must be named mabaniq_<label>")
    import psycopg

    report: dict = {"started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "source_db": urlsplit(a.source).path.lstrip("/"),
                    "target_db": a.target, "steps": {}, "ok": False}
    stamps: dict[str, float] = {}

    def step(name):
        stamps[name] = time.perf_counter()

    def done(name, ok=True, **info):
        report["steps"][name] = {"ok": ok, "ms": round((time.perf_counter() - stamps[name]) * 1000), **info}
        print(("✅" if ok else "❌"), name, json.dumps(info, ensure_ascii=False)[:300])
        if not ok:
            raise SystemExit(f"drill failed at {name}")

    admin_url = with_db(a.source, "postgres")
    target_url = with_db(a.source, a.target)
    try:
        step("dump")
        folder = dump(a.source, Path(a.out))
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        done("dump", folder=str(folder), rows=manifest["rows_total"], bytes=manifest["bytes"])

        step("create_target")
        with psycopg.connect(admin_url, autocommit=True) as c:
            if c.execute("SELECT 1 FROM pg_database WHERE datname=%s", (a.target,)).fetchone():
                done("create_target", False, reason="target database already exists")
            c.execute(f'CREATE DATABASE "{a.target}"')
        with psycopg.connect(target_url, autocommit=True) as c:
            c.execute("DROP SCHEMA public CASCADE")  # the archive carries its own CREATE SCHEMA public (pg_dump --schema=public)
        done("create_target")

        step("restore")
        subprocess.run([pg_bin("pg_restore"), "--no-owner", "--no-privileges", "--exit-on-error", "--dbname", target_url,  # noqa: S603 — argv built here, never from user input
                        str(folder / manifest["archive"])], check=True)
        with psycopg.connect(target_url, autocommit=True) as c:
            for stmt in grant_statements():
                c.execute(stmt)
        done("restore")

        step("verify_rows")
        counts, migrations = row_counts(target_url)
        diff = {t: (manifest["tables"].get(t), n) for t, n in counts.items() if manifest["tables"].get(t) != n}
        done("verify_rows", not diff and migrations == manifest["migrations"], tables=len(counts), mismatches=diff,
             migrations_equal=migrations == manifest["migrations"])

        step("verify_audit_chain")
        from backend import dbx
        from backend.db import audit_verify
        with psycopg.connect(target_url, autocommit=False) as raw:
            from psycopg.types.numeric import FloatLoader
            raw.adapters.register_loader("numeric", FloatLoader)
            orgs = [r[0] for r in raw.execute("SELECT DISTINCT org_id FROM audit").fetchall()]
            results = {}
            for org in orgs:
                raw.execute(f"SET ROLE {dbx.APP_ROLE}")
                raw.execute("SELECT set_config('app.org_id', %s, false)", (org,))
                v = audit_verify(dbx.PgConn(raw, org))
                results[org] = v
                raw.execute("RESET ROLE")
            raw.rollback()
        done("verify_audit_chain", all(v.get("ok") for v in results.values()) or not orgs, tenants=results)

        if a.pgtap:
            step("pgtap")
            # the dump carries only schema public: the pgTAP extension (or its plain SQL in CI) must be re-created on the copy
            if a.pgtap_sql:
                subprocess.run([pg_bin("psql"), target_url, "-v", "ON_ERROR_STOP=1", "-q", "-f", a.pgtap_sql], check=True)  # noqa: S603
            else:
                with psycopg.connect(target_url, autocommit=True) as c:
                    c.execute("CREATE EXTENSION IF NOT EXISTS pgtap")
            r = subprocess.run([sys.executable, str(ROOT / "db" / "run_pgtap.py"), target_url], capture_output=True, text=True)  # noqa: S603 — argv built here, never from user input
            done("pgtap", r.returncode == 0, tail=r.stdout.strip().splitlines()[-1:] + r.stderr.strip().splitlines()[-2:])

        report["ok"] = True
    finally:
        if not a.keep:
            step("drop_target")
            try:
                with psycopg.connect(admin_url, autocommit=True) as c:
                    c.execute(f'DROP DATABASE IF EXISTS "{a.target}" WITH (FORCE)')
                report["steps"]["drop_target"] = {"ok": True, "ms": round((time.perf_counter() - stamps["drop_target"]) * 1000)}
            except Exception as e:  # noqa: BLE001
                report["steps"]["drop_target"] = {"ok": False, "error": str(e)}
        report["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        out = ROOT / ".local" / "backup-drill"
        out.mkdir(parents=True, exist_ok=True)
        p = out / f"drill-{report['started_utc'].replace(':', '').replace('-', '')}.json"
        p.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(("drill OK" if report["ok"] else "drill FAILED"), "→", p)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
