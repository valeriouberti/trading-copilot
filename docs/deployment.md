# Deployment

## Local Development

```bash
git clone <repo-url>
cd trading-assistant

python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt        # or: pip install .

cp .env.example .env
# Edit .env with your GROQ_API_KEY

python run_webapp.py
# Open http://localhost:8000
```

**Alternative install via pyproject.toml:**

```bash
pip install .                          # base dependencies
pip install ".[dev]"                   # with test dependencies
```

The app uses SQLite by default -- no database setup required.

---

## Docker

### Quick Start

```bash
cp .env.example .env
# Edit .env with your GROQ_API_KEY

docker compose up -d
# Open http://localhost:8000
```

This starts two containers:

| Container | Image | Purpose |
|-----------|-------|---------|
| `postgres` | `postgres:16-alpine` | PostgreSQL database |
| `trading-app` | Built from Dockerfile | ETF Swing Trader |

The app waits for PostgreSQL to be healthy before starting. Data is persisted in a Docker volume (`pgdata`).

### Environment Variables in Docker

Docker Compose passes variables from your `.env` file to the container. The `DATABASE_URL` is set automatically to point at the PostgreSQL container:

```
postgresql+asyncpg://trading:${POSTGRES_PASSWORD}@postgres:5432/trading
```

You only need to set `GROQ_API_KEY` and optionally Telegram config in `.env`.

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

---

## Production Considerations

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

Returns status of database, scheduler, cache, and circuit breakers. Use this for load balancer health checks and monitoring.

### Logging

The app uses structured JSON logging with correlation IDs. Log level defaults to `INFO`. Logs go to stderr (standard for containerized deployments).

### Resource Usage

- **Memory**: ~200 MB
- **CPU**: Mostly idle. Spikes during analysis (indicator computation) and sentiment (LLM calls)
- **Disk**: SQLite DB grows slowly. PostgreSQL recommended for long-term use
- **Network**: External API calls to yfinance, Groq, Polymarket, Forex Factory

### Groq API Budget

Dev Tier provides 500,000 requests/day and 300,000 tokens/minute. Each ETF analysis uses ~4 LLM calls:

```
8 ETFs x 4 calls = 32 calls per full screening
3 screenings/day (08:00 + manual) = ~96 calls/day
```

Well within Dev Tier limits. Monitor usage at [console.groq.com/usage](https://console.groq.com/usage).
