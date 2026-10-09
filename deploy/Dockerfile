# Mabaniq API image. Build context: repository root.  docker build -f deploy/Dockerfile .
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PORT=8800 HOST=0.0.0.0
ARG GIT_SHA=""
ENV MABANIQ_GIT_SHA=$GIT_SHA
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY frontend ./frontend
COPY db ./db
COPY README.md CHANGELOG-0.5.0.md ./

# data/ holds SQLite (demo only) and generated demo secrets; it is ephemeral on Railway (no VOLUME: the platform rejects it) — PostgreSQL and env secrets are the durable state.
RUN useradd --create-home --uid 10001 mabaniq && mkdir -p /app/data && chown -R mabaniq:mabaniq /app
USER mabaniq
EXPOSE 8800
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8800/health', timeout=3).status==200 else 1)"

# --proxy-headers: trust X-Forwarded-* only from the platform proxy (loopback / private network)
CMD ["sh", "-c", "uvicorn backend.app:app --host ${HOST} --port ${PORT} --proxy-headers --forwarded-allow-ips='*' --no-access-log"]
