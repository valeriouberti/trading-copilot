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
from app.api import analytics_api as analytics_router
from app.api import assets as assets_router
from app.api import health as health_router
from app.api import monitor as monitor_router
from app.api import portfolio as portfolio_router
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

    # Initialize ETF scheduler (cron-based)
    from app.services.monitor import ETFScheduler

    scheduler = ETFScheduler(app)
    app.state.monitor = scheduler
    scheduler.install_signal_handlers()
    scheduler.start()
    await scheduler.startup_catchup()

    db_type = "PostgreSQL" if "postgresql" in settings.database_url else "SQLite"
    logger.info("ETF Swing Trader started — database: %s", db_type)

    yield

    # Shutdown
    await scheduler.shutdown()
    await engine.dispose()
    logger.info("Trading Copilot stopped")


app = FastAPI(
    title="ETF Swing Trader",
    description="UCITS ETF swing trading assistant",
    version="6.0.0",
    lifespan=lifespan,
)

# Structured logging + correlation ID middleware
if os.environ.get("TRADING_COPILOT_JSON_LOGS", "").lower() in ("1", "true"):
    from app.middleware.logging import CorrelationIDMiddleware, configure_logging
    configure_logging()
    app.add_middleware(CorrelationIDMiddleware)

# API key authentication (only if env var is set)
_api_key = os.environ.get("TRADING_COPILOT_API_KEY", "")
if _api_key:
    from app.middleware.auth import APIKeyMiddleware
    app.add_middleware(APIKeyMiddleware, api_key=_api_key)

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
app.include_router(analytics_router.router, prefix="/api", tags=["analytics"])
app.include_router(settings_router.router, prefix="/api", tags=["settings"])
app.include_router(monitor_router.router, prefix="/api", tags=["monitor"])
app.include_router(portfolio_router.router, prefix="/api", tags=["portfolio"])
app.include_router(trades_router.router, prefix="/api", tags=["trades"])
app.include_router(ws_router.router, tags=["websocket"])


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


async def _page_ctx(request: Request, title: str, **extra) -> dict:
    """Build common template context with nav_assets for the navbar."""
    assets = await get_all_assets(request.app.state.session_factory)
    return {"request": request, "title": title, "nav_assets": assets, **extra}


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Render the main dashboard page."""
    assets = await get_all_assets(request.app.state.session_factory)
    ctx = await _page_ctx(request, "Trading Copilot", assets=assets)
    return templates.TemplateResponse("dashboard.html", ctx)


@app.get("/asset/{symbol}", response_class=HTMLResponse)
async def asset_detail(request: Request, symbol: str):
    """Render the single-asset analysis page."""
    assets = await get_all_assets(request.app.state.session_factory)
    asset = next(
        (a for a in assets if a["symbol"] == symbol),
        {"symbol": symbol, "display_name": symbol},
    )
    ctx = await _page_ctx(
        request, f"{asset['display_name']} — Trading Copilot", asset=asset
    )
    return templates.TemplateResponse("asset_detail.html", ctx)


@app.get("/portfolio", response_class=HTMLResponse)
async def portfolio_page(request: Request):
    """Render the portfolio (open positions) page."""
    ctx = await _page_ctx(request, "Portfolio — ETF Swing Trader")
    return templates.TemplateResponse("portfolio.html", ctx)


@app.get("/trades", response_class=HTMLResponse)
async def trades_page(request: Request):
    """Render the trade journal page."""
    assets = await get_all_assets(request.app.state.session_factory)
    ctx = await _page_ctx(request, "Trade Journal — Trading Copilot", assets=assets)
    return templates.TemplateResponse("trades.html", ctx)


@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request):
    """Render the performance analytics page."""
    ctx = await _page_ctx(request, "Analytics — Trading Copilot")
    return templates.TemplateResponse("analytics.html", ctx)


@app.get("/signals", response_class=HTMLResponse)
async def signals_page(request: Request):
    """Render the signal history page."""
    ctx = await _page_ctx(request, "Signal History — Trading Copilot")
    return templates.TemplateResponse("signals.html", ctx)


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Render the settings page."""
    ctx = await _page_ctx(request, "Settings — Trading Copilot")
    return templates.TemplateResponse("settings.html", ctx)
