# ── Stage 1a: lite builder (no ML deps) ──────────────
FROM python:3.12-slim AS builder-lite

WORKDIR /build
COPY requirements-base.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements-base.txt

# ── Stage 1b: full builder ───────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build
COPY requirements.lock .
RUN pip install --no-cache-dir --prefix=/install -r requirements.lock

# ── Stage 2a: lite runtime (no transformers/torch) ───
FROM python:3.12-slim AS lite

WORKDIR /app
COPY --from=builder-lite /install /usr/local
COPY . .

# Non-root user
RUN useradd -m trader && chown -R trader:trader /app
USER trader

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"

CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8000"]

# ── Stage 2b: full runtime (default) ─────────────────
FROM python:3.12-slim

WORKDIR /app
COPY --from=builder /install /usr/local
COPY . .

# Non-root user
RUN useradd -m trader && chown -R trader:trader /app
USER trader

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"

CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8000"]
