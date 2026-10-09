"""Logical backup of the Mabaniq PostgreSQL database (Unit 4, docs/RUNBOOK.md §4).

    python scripts/backup/dump.py                               # source = MABANIQ_DATABASE_URL, out = .local/backups
    python scripts/backup/dump.py --db-url postgresql://… --out /backups

Writes <out>/<UTC stamp>/mabaniq.dump (pg_dump -Fc, schema + data of `public`), manifest.json (row count of every
table, sha256 and size of the archive, app version, migrations applied) and checks the archive with `pg_restore --list`.
Exit code 0 only when the archive is written, readable and the manifest is complete. Read-only on the source.
Tools: $PG_BIN, then ./.local/pg/bin, then C:\\istiqama-map\\.local\\pg\\bin (development machine), then PATH.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
EXE = ".exe" if os.name == "nt" else ""


def pg_bin(tool: str) -> str:
    for d in filter(None, [os.environ.get("PG_BIN"), str(ROOT / ".local" / "pg" / "bin"), r"C:\istiqama-map\.local\pg\bin"]):
        p = Path(d) / f"{tool}{EXE}"
        if p.exists():
            return str(p)
    found = shutil.which(tool)
    if not found:
        raise SystemExit(f"{tool} not found: set PG_BIN or install the PostgreSQL client tools")
    return found


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def row_counts(db_url: str) -> tuple[dict[str, int], list[str]]:
    import psycopg
    with psycopg.connect(db_url, autocommit=False) as conn:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY 1")
        tables = [r[0] for r in cur.fetchall()]
        counts = {}
        for t in tables:
            cur.execute(f'SELECT count(*) FROM "{t}"')
            counts[t] = cur.fetchone()[0]
        cur.execute("SELECT version FROM schema_migrations ORDER BY 1")
        migrations = [r[0] for r in cur.fetchall()]
        conn.rollback()
    return counts, migrations


def dump(db_url: str, out_dir: Path) -> Path:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    folder = out_dir / stamp
    folder.mkdir(parents=True, exist_ok=False)
    archive = folder / "mabaniq.dump"
    t0 = time.perf_counter()
    subprocess.run([pg_bin("pg_dump"), "--format=custom", "--no-owner", "--no-privileges", "--schema=public",  # noqa: S603 — argv built here, never from user input
                    "--file", str(archive), db_url], check=True)
    dump_ms = round((time.perf_counter() - t0) * 1000)
    listing = subprocess.run([pg_bin("pg_restore"), "--list", str(archive)], check=True, capture_output=True, text=True).stdout  # noqa: S603 — argv built here, never from user input
    counts, migrations = row_counts(db_url)
    from backend.config import VERSION
    manifest = {"created_utc": stamp, "app_version": VERSION, "database": db_url.rsplit("/", 1)[-1].split("?")[0],
                "archive": archive.name, "bytes": archive.stat().st_size, "sha256": sha256(archive), "pg_dump_ms": dump_ms,
                "toc_entries": sum(1 for line in listing.splitlines() if line and not line.startswith(";")),
                "migrations": migrations, "tables": counts, "rows_total": sum(counts.values())}
    (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        os.chmod(archive, 0o600)
    except OSError:
        pass
    print(f"backup {folder} — {manifest['bytes']:,} bytes, {manifest['rows_total']:,} rows in {len(counts)} tables, {dump_ms} ms")
    return folder


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db-url", default=os.environ.get("MABANIQ_DATABASE_URL", ""))
    ap.add_argument("--out", default=str(ROOT / ".local" / "backups"))
    a = ap.parse_args()
    if not a.db_url.startswith("postgres"):
        ap.error("--db-url (or MABANIQ_DATABASE_URL) must be a postgresql:// URL")
    dump(a.db_url, Path(a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
