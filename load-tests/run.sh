#!/usr/bin/env sh
# k6 load run against a private API instance (Unit 4, acceptance 15). Usage:
#   sh load-tests/run.sh [sqlite|postgres] [VUS] [RAMP] [STEADY] [RAMP_DOWN]
# postgres mode needs MABANIQ_DATABASE_URL (the local cluster: postgresql://postgres@127.0.0.1:54330/mabaniq_test).
# The instance runs with relaxed per-IP limits (every VU shares one address) and retention disabled; results in load-tests/results/.
set -eu
MODE="${1:-sqlite}"; VUS="${2:-300}"; RAMP="${3:-30s}"; STEADY="${4:-2m}"; RAMP_DOWN="${5:-20s}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${MABANIQ_LOAD_PORT:-8802}"
K6="${K6:-$(command -v k6 || echo /c/istiqama-map/.local/k6/k6.exe)}"
PY="${PYTHON:-$ROOT/.venv/Scripts/python.exe}"
[ -x "$PY" ] || PY=python
PASSWORD="Load-Pass-2026-k6"
TMP="$(mktemp -d)"
mkdir -p "$ROOT/load-tests/results"

if [ "$MODE" = "postgres" ]; then
  [ -n "${MABANIQ_DATABASE_URL:-}" ] || { echo "MABANIQ_DATABASE_URL required for postgres mode"; exit 2; }
  DBENV="MABANIQ_DATABASE_URL=$MABANIQ_DATABASE_URL"
else
  DBENV="MABANIQ_DATABASE_URL= MABANIQ_DB=$TMP/load.db"
fi

echo "starting API ($MODE) on :$PORT with ${WEB_CONCURRENCY:-1} worker(s) …"
env $DBENV MABANIQ_DEMO_PASSWORD="$PASSWORD" MABANIQ_FORCE_PW_CHANGE=0 MABANIQ_RATE_LOGIN=1000/60 MABANIQ_RATE_API=1000000/60 \
    MABANIQ_LOG_JSON=0 MABANIQ_LOG_LEVEL=WARNING MABANIQ_RETENTION=0 MABANIQ_PG_POOL_MAX="${MABANIQ_PG_POOL_MAX:-40}" PYTHONIOENCODING=utf-8 \
    "$PY" -m uvicorn backend.app:app --host 127.0.0.1 --port "$PORT" --workers "${WEB_CONCURRENCY:-1}" --no-access-log --log-level warning >"$TMP/api.log" 2>&1 &
API=$!
stop_api() {
  kill $API 2>/dev/null || true
  # uvicorn --workers children survive the parent on Windows; free the port explicitly
  command -v powershell >/dev/null 2>&1 && powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort $PORT -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id \$_.OwningProcess -Force }" >/dev/null 2>&1 || true
}
trap stop_api EXIT INT TERM
for i in $(seq 1 60); do curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break; sleep 1; done
curl -fsS "http://127.0.0.1:$PORT/version"; echo

cd "$ROOT/load-tests"
"$K6" run --quiet -e BASE_URL="http://127.0.0.1:$PORT" -e PASSWORD="$PASSWORD" -e VUS="$VUS" -e RAMP="$RAMP" -e STEADY="$STEADY" \
    -e RAMP_DOWN="$RAMP_DOWN" -e OUT_DIR=./results -e MODE="$MODE" mix.js
echo "api log tail:"; tail -3 "$TMP/api.log" || true
