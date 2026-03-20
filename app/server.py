"""FastAPI application — Trading Copilot web dashboard.

Startup: creates the database engine, auto-creates tables if needed.
Shutdown: disposes the engine gracefully.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api import analysis as analysis_router
from app.api import assets as assets_router
from app.api import health as health_router
from app.api import monitor as monitor_router
from app.api import settings as settings_router
from app.api import trades as trades_router
from app.api import websocket as ws_router
from app.config import get_settings, to_config_dict
from app.models.database import (
    Base,
    get_all_assets,
    get_all_rss_feeds,
    seed_assets_from_config,
    seed_rss_feeds,
)
from app.models.engine import get_engine, get_session_factory

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup and shutdown resources."""
    # Startup
    settings = get_settings()
    engine = get_engine(settings.database_url)

    # Auto-create tables if they don't exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app.state.engine = engine
    app.state.session_factory = get_session_factory(engine)
    app.state.settings = settings
    app.state.config = to_config_dict(settings)  # backward compat for modules

    # Seed assets and RSS feeds from config.yaml (or defaults) on first run
    await seed_assets_from_config(app.state.session_factory, app.state.config)
    await seed_rss_feeds(app.state.session_factory, settings.rss_feeds or None)

    # Load RSS feeds from DB into config dict (source of truth is DB)
    app.state.config["rss_feeds"] = await get_all_rss_feeds(app.state.session_factory)

    # Seed telegram config from env vars into DB (first run only)
    from app.models.database import get_telegram_config, upsert_telegram_config

    tg_db = await get_telegram_config(app.state.session_factory)
    if not tg_db["bot_token"] and settings.telegram_bot_token:
        await upsert_telegram_config(
            app.state.session_factory,
            settings.telegram_bot_token,
            settings.telegram_chat_id,
            settings.telegram_enabled,
        )

    # Initialize background monitor
    from app.services.monitor import AssetMonitor

    monitor = AssetMonitor(app)
    app.state.monitor = monitor
    monitor.install_signal_handlers()
    await monitor.restore_from_db()

    db_type = "PostgreSQL" if "postgresql" in settings.database_url else "SQLite"
    logger.info("Trading Copilot started — database: %s", db_type)

    yield

    # Shutdown
    await monitor.shutdown()
    await engine.dispose()
    logger.info("Trading Copilot stopped")


app = FastAPI(
    title="Trading Copilot",
    description="Real-time CFD trading dashboard",
    version="5.3.0",
    lifespan=lifespan,
)

# Structured logging + correlation ID middleware
if os.environ.get("TRADING_COPILOT_JSON_LOGS", "").lower() in ("1", "true"):
    from app.middleware.logging import CorrelationIDMiddleware, configure_logging
    configure_logging()
    app.add_middleware(CorrelationIDMiddleware)

# Rate limiting
from app.middleware.rate_limit import limiter
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Static files
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")

# Templates
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))

# API routers
app.include_router(health_router.router, prefix="/api", tags=["health"])
app.include_router(assets_router.router, prefix="/api", tags=["assets"])
app.include_router(analysis_router.router, prefix="/api", tags=["analysis"])
app.include_router(settings_router.router, prefix="/api", tags=["settings"])
app.include_router(monitor_router.router, prefix="/api", tags=["monitor"])
app.include_router(trades_router.router, prefix="/api", tags=["trades"])
app.include_router(ws_router.router, tags=["websocket"])


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Render the main dashboard page."""
    assets = await get_all_assets(request.app.state.session_factory)
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "assets": assets,
            "title": "Trading Copilot",
        },
    )


@app.get("/asset/{symbol}", response_class=HTMLResponse)
async def asset_detail(request: Request, symbol: str):
    """Render the single-asset analysis page."""
    assets = await get_all_assets(request.app.state.session_factory)
    asset = next(
        (a for a in assets if a["symbol"] == symbol),
        {"symbol": symbol, "display_name": symbol},
    )
    return templates.TemplateResponse(
        "asset_detail.html",
        {
            "request": request,
            "asset": asset,
            "title": f"{asset['display_name']} — Trading Copilot",
        },
    )


@app.get("/trades", response_class=HTMLResponse)
async def trades_page(request: Request):
    """Render the trade journal page."""
    assets = await get_all_assets(request.app.state.session_factory)
    return templates.TemplateResponse(
        "trades.html",
        {
            "request": request,
            "assets": assets,
            "title": "Trade Journal — Trading Copilot",
        },
    )


@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request):
    """Render the performance analytics page."""
    return templates.TemplateResponse(
        "analytics.html",
        {
            "request": request,
            "title": "Analytics — Trading Copilot",
        },
    )


@app.get("/signals", response_class=HTMLResponse)
async def signals_page(request: Request):
    """Render the signal history page."""
    return templates.TemplateResponse(
        "signals.html",
        {
            "request": request,
            "title": "Signal History — Trading Copilot",
        },
    )


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Render the settings page."""
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "title": "Settings — Trading Copilot",
        },
    )
