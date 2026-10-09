#!/usr/bin/env bash
# تشغيل مبانيك محليًا: ./run.sh  ثم افتح http://localhost:8800
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  uv venv -q .venv && uv pip install -q --python .venv/bin/python -r requirements.txt
fi
exec .venv/bin/uvicorn backend.app:app --host "${HOST:-127.0.0.1}" --proxy-headers --forwarded-allow-ips=127.0.0.1 --port "${PORT:-8800}"
