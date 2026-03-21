# Deployment

## Local Development

```bash
git clone <repo-url>
cd trading-assistant

python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env with your API keys

python run_webapp.py
# Open http://localhost:8000
```

The app uses SQLite by default — no database setup required.

---

## Docker

### Quick Start

```bash
cp .env.example .env
# Edit .env with your API keys

docker compose up -d
# Open http://localhost:8000
```

This starts two containers:

| Container | Image | Purpose |
|-----------|-------|---------|
| `postgres` | `postgres:16-alpine` | PostgreSQL database |
| `trading-app` | Built from Dockerfile | Trading Copilot |

The app waits for PostgreSQL to be healthy before starting. Data is persisted in a Docker volume (`pgdata`).

### Docker Image Variants

The Dockerfile provides two targets:

| Target | Build Command | Size | Includes |
|--------|--------------|------|----------|
| **full** (default) | `docker compose up -d` | ~3 GB | All dependencies including transformers, torch (FinBERT fallback) |
| **lite** | `docker build --target lite -t trading-lite .` | ~500 MB | Core dependencies only, no ML models |

The **lite** image skips FinBERT (the local sentiment fallback). It still works — sentiment analysis uses the Groq LLM exclusively. Use lite when:
- You always have a Groq API key set
- You want smaller images for CI/CD or constrained environments

### Environment Variables in Docker

Docker Compose passes variables from your `.env` file to the container. The `DATABASE_URL` is set automatically to point at the PostgreSQL container:

```
postgresql+asyncpg://trading:${POSTGRES_PASSWORD}@postgres:5432/trading
```

You only need to set API keys and Telegram config in `.env`.

### Custom PostgreSQL Password

```bash
# In .env
POSTGRES_PASSWORD=your_secure_password
```

Default is `trading_local` if unset.

---

## PostgreSQL

### Using Docker Compose (recommended)

PostgreSQL is included in `docker-compose.yml`. No extra setup needed.

### Using an External PostgreSQL

Set `DATABASE_URL` in `.env`:

```env
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/trading
```

The app auto-creates tables on first startup via SQLAlchemy.

### Migrations

Alembic handles schema migrations:

```bash
# Apply all pending migrations
alembic upgrade head

# Create a new migration after model changes
alembic revision --autogenerate -m "description"

# Check current migration state
alembic current
```

The initial schema migration is at `alembic/versions/e1b5a34759a7_initial_schema.py`.

### Backup & Restore

**SQLite:**

```bash
# Backup
cp trading.db trading.db.bak

# Restore
cp trading.db.bak trading.db
```

**PostgreSQL (Docker):**

```bash
# Backup
docker compose exec postgres pg_dump -U trading trading > backup.sql

# Restore
docker compose exec -T postgres psql -U trading trading < backup.sql
```

**PostgreSQL (external):**

```bash
pg_dump -h host -U user trading > backup.sql
psql -h host -U user trading < backup.sql
```

---

## Production Considerations

### Authentication

Set `TRADING_COPILOT_API_KEY` to enable API key authentication:

```env
TRADING_COPILOT_API_KEY=your_secret_key
```

When set, all API endpoints require either:
- `X-API-Key` header
- `api_key` query parameter

Public paths (dashboard pages, `/api/health`, static files) are exempt.

When unset, authentication is disabled (development mode).

### Rate Limiting

Built-in rate limits (per IP via slowapi):

| Endpoint Group | Limit |
|---------------|-------|
| Analysis (`/analyze`) | 60 req/min |
| Monitor control | 10 req/min |
| General API | 120 req/min |

Exceeded limits return `429 Too Many Requests`.

### Reverse Proxy

For production, run behind nginx or Caddy:

```nginx
server {
    listen 443 ssl;
    server_name trading.example.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

The `Connection "upgrade"` headers are required for WebSocket (`/ws/signals`) to work.

### Health Check

```
GET /api/health
```

Returns status of database, monitor, cache, and circuit breakers. Use this for load balancer health checks and monitoring.

### Logging

The app uses structured JSON logging with correlation IDs. Log level defaults to `INFO`. Logs go to stderr (standard for containerized deployments).

### Resource Usage

- **Memory**: ~200 MB (lite), ~1.5 GB (full, with ML models loaded)
- **CPU**: Mostly idle. Spikes during analysis (indicator computation) and sentiment (LLM calls)
- **Disk**: SQLite DB grows slowly. PostgreSQL recommended for long-term use
- **Network**: External API calls to yfinance, Twelve Data, Groq, Polymarket, Forex Factory

### Twelve Data Credit Budget

The free tier provides 800 credits/day. The monitor's light poll uses 1 credit per check (every 2 min per asset). With 3 assets monitored continuously:

```
3 assets x 1 credit x 30 checks/hour x 8 hours = 720 credits
```

Monitor the budget at `/api/monitor/budget` or in the Settings page.
