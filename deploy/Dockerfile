# Mabaniq image. Build context: repository root.  docker build -f deploy/Dockerfile .
# Stage 1 — web bundle (Vite): web/ → frontend/dist (hashed, immutable assets; self-hosted fonts; no inline scripts)
FROM node:24-slim AS web
WORKDIR /src
COPY package.json package-lock.json vite.config.js ./
RUN npm ci --no-audit --no-fund --ignore-scripts
COPY web ./web
RUN npm run build && node -e "const s=require('fs').statSync('frontend/dist/index.html'); if(!s.size) process.exit(1)"

# Stage 2 — API
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PORT=8800 HOST=0.0.0.0
ARG GIT_SHA=""
ENV MABANIQ_GIT_SHA=$GIT_SHA
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY db ./db
COPY README.md CHANGELOG-0.5.0.md ./
COPY --from=web /src/frontend/dist ./frontend/dist

# data/ holds SQLite (demo only) and generated demo secrets; it is ephemeral on Railway (no VOLUME: the platform rejects it) — PostgreSQL and env secrets are the durable state.
RUN useradd --create-home --uid 10001 mabaniq && mkdir -p /app/data && chown -R mabaniq:mabaniq /app
USER mabaniq
EXPOSE 8800
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8800/health', timeout=3).status==200 else 1)"

# --proxy-headers: trust X-Forwarded-* only behind the platform proxy
CMD ["sh", "-c", "uvicorn backend.app:app --host ${HOST} --port ${PORT} --proxy-headers --forwarded-allow-ips='*' --no-access-log"]
