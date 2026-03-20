"""FastAPI application — Trading Copilot web dashboard.

Startup: creates the database engine, auto-creates tables if needed.
Shutdown: disposes the engine gracefully.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api import analysis as analysis_router
from app.api import assets as assets_router
from app.api import health as health_router
from app.api import settings as settings_router
from app.config import get_database_url, load_config
from app.models.database import Base
from app.models.engine import get_engine, get_session_factory

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup and shutdown resources."""
    # Startup
    database_url = get_database_url()
    engine = get_engine(database_url)

    # Auto-create tables if they don't exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app.state.engine = engine
    app.state.session_factory = get_session_factory(engine)
    app.state.config = load_config()

    db_type = "PostgreSQL" if "postgresql" in database_url else "SQLite"
    logger.info("Trading Copilot started — database: %s", db_type)

    yield

    # Shutdown
    await engine.dispose()
    logger.info("Trading Copilot stopped")


app = FastAPI(
    title="Trading Copilot",
    description="Real-time CFD trading dashboard",
    version="0.1.0",
    lifespan=lifespan,
)

# Static files
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")

# Templates
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))

# API routers
app.include_router(health_router.router, prefix="/api", tags=["health"])
app.include_router(assets_router.router, prefix="/api", tags=["assets"])
app.include_router(analysis_router.router, prefix="/api", tags=["analysis"])
app.include_router(settings_router.router, prefix="/api", tags=["settings"])


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Render the main dashboard page."""
    config = request.app.state.config
    assets = config.get("assets", [])
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
    config = request.app.state.config
    assets = config.get("assets", [])
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
