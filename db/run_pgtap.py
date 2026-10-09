"""Run the pgTAP suite without pg_prove: `python db/run_pgtap.py [postgresql://…]` (default MABANIQ_DATABASE_URL).

Each file in db/tests/*.sql is a self-contained TAP script (BEGIN … SELECT * FROM finish(); ROLLBACK;). The TAP lines are
collected from every statement's result set; any `not ok` or a failed plan fails the run. Exit code 0 = green.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def split_statements(sql: str) -> list[str]:
    """Split on ';' outside dollar-quoted blocks and quotes (enough for our TAP files)."""
    out, buf, i, n = [], [], 0, len(sql)
    in_dollar = None
    in_quote = None
    while i < n:
        ch = sql[i]
        if in_dollar:
            if sql.startswith(in_dollar, i):
                buf.append(in_dollar)
                i += len(in_dollar)
                in_dollar = None
                continue
        elif in_quote:
            if ch == in_quote:
                if sql[i + 1:i + 2] == in_quote:  # escaped ''
                    buf.append(ch * 2)
                    i += 2
                    continue
                in_quote = None
        else:
            if ch == "-" and sql.startswith("--", i):
                j = sql.find("\n", i)
                i = n if j < 0 else j
                continue
            m = re.match(r"\$[A-Za-z_]*\$", sql[i:])
            if m:
                in_dollar = m.group(0)
                buf.append(in_dollar)
                i += len(in_dollar)
                continue
            if ch == "'":
                in_quote = ch
            elif ch == ";":
                stmt = "".join(buf).strip()
                if stmt:
                    out.append(stmt)
                buf = []
                i += 1
                continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


def run_file(dsn: str, path: Path) -> tuple[int, int, list[str]]:
    ok = bad = 0
    failures: list[str] = []
    planned = None
    with psycopg.connect(dsn, autocommit=True) as conn:
        from backend.dbx import apply_migrations
        apply_migrations(conn)
        cur = conn.cursor()
        for stmt in split_statements(path.read_text(encoding="utf-8")):
            try:
                cur.execute(stmt)
            except psycopg.Error as e:
                failures.append(f"SQL error in {path.name}: {e}\n  {stmt[:200]}")
                bad += 1
                break
            if cur.description:
                for row in cur.fetchall():
                    line = str(row[0]) if row else ""
                    if re.match(r"^\d+\.\.\d+$", line):
                        planned = int(line.split("..")[1])
                    elif line.startswith("ok "):
                        ok += 1
                    elif line.startswith("not ok"):
                        bad += 1
                        failures.append(f"{path.name}: {line}")
                    elif line.startswith("# Looks like") or line.startswith("# Failed"):
                        failures.append(f"{path.name}: {line}")
    if planned is not None and ok + bad != planned:
        failures.append(f"{path.name}: planned {planned} tests, ran {ok + bad}")
        bad += 1
    return ok, bad, failures


def main() -> int:
    dsn = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("MABANIQ_DATABASE_URL", "")
    if not dsn.startswith("postgres"):
        print("usage: python db/run_pgtap.py postgresql://… (or set MABANIQ_DATABASE_URL)")
        return 2
    total_ok = total_bad = 0
    all_failures: list[str] = []
    for f in sorted((ROOT / "db" / "tests").glob("*.sql")):
        ok, bad, failures = run_file(dsn, f)
        total_ok += ok
        total_bad += bad
        all_failures += failures
        print(f"{'✅' if not bad else '❌'} {f.name}: {ok} ok, {bad} failed")
    for line in all_failures:
        print("   ", line)
    print(f"pgTAP: {total_ok} ok, {total_bad} failed")
    return 0 if total_bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
