"""Configuration management — Pydantic Settings with env var priority.

Priority chain: env vars > .env file > config.yaml > defaults.

Secrets (API keys, tokens) come ONLY from environment variables.
Static config (RSS feeds, seed assets) comes from config.yaml.
Telegram runtime settings are stored in the database.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_YAML_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


class Settings(BaseSettings):
    """Application settings — typed and validated."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────────────────
    database_url: str = Field(
        default="sqlite+aiosqlite:///./trading.db",
        description="Async SQLAlchemy database URL",
    )

    # ── Secrets (always from env vars) ────────────────────────────────
    groq_api_key: str = Field(default="", description="Groq LLM API key")
    twelve_data_api_key: str = Field(default="", description="Twelve Data API key")
    telegram_bot_token: str = Field(default="", description="Telegram bot token")
    telegram_chat_id: str = Field(default="", description="Telegram chat ID")
    telegram_enabled: bool = Field(default=False, description="Enable Telegram notifications")

    # ── App config (env overrides YAML) ───────────────────────────────
    groq_model: str = Field(default="llama-3.3-70b-versatile")
    lookback_hours: int = Field(default=16, ge=1, le=168)
    report_language: str = Field(default="italian")

    # ── Static config (loaded from YAML) ──────────────────────────────
    rss_feeds: list[dict[str, str]] = Field(default_factory=list)
    seed_assets: list[dict[str, str]] = Field(default_factory=list)


def _load_yaml(path: Path | None = None) -> dict[str, Any]:
    """Load config.yaml. Returns empty dict if file is missing."""
    yaml_path = path or _YAML_PATH
    if not yaml_path.exists():
        return {}
    with open(yaml_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache()
def get_settings(yaml_path: str | None = None) -> Settings:
    """Create a Settings instance with YAML values as fallbacks.

    Env vars always win over YAML. YAML wins over pydantic defaults.
    """
    yaml_data = _load_yaml(Path(yaml_path) if yaml_path else None)
    overrides: dict[str, Any] = {}

    # Static lists from YAML (no env var equivalent)
    if yaml_data.get("rss_feeds"):
        overrides["rss_feeds"] = yaml_data["rss_feeds"]
    if yaml_data.get("seed_assets"):
        overrides["seed_assets"] = yaml_data["seed_assets"]
    elif yaml_data.get("assets"):
        # Backward compat: old config.yaml used "assets" key
        overrides["seed_assets"] = yaml_data["assets"]

    # YAML fallbacks — only apply if env var is NOT set
    if yaml_data.get("groq_model") and not os.environ.get("GROQ_MODEL"):
        overrides["groq_model"] = yaml_data["groq_model"]
    if yaml_data.get("lookback_hours") and not os.environ.get("LOOKBACK_HOURS"):
        overrides["lookback_hours"] = yaml_data["lookback_hours"]
    if yaml_data.get("report_language") and not os.environ.get("REPORT_LANGUAGE"):
        overrides["report_language"] = yaml_data["report_language"]

    # Database URL from YAML as fallback
    db_url = yaml_data.get("database", {}).get("url")
    if db_url and not os.environ.get("DATABASE_URL"):
        overrides["database_url"] = db_url

    # Telegram from YAML as fallback (for migration — new installs use env only)
    tg = yaml_data.get("telegram", {})
    if tg.get("bot_token") and not os.environ.get("TELEGRAM_BOT_TOKEN"):
        overrides["telegram_bot_token"] = tg["bot_token"]
    if tg.get("chat_id") and not os.environ.get("TELEGRAM_CHAT_ID"):
        overrides["telegram_chat_id"] = str(tg["chat_id"])
    if "enabled" in tg and not os.environ.get("TELEGRAM_ENABLED"):
        overrides["telegram_enabled"] = tg["enabled"]

    return Settings(**overrides)


def get_database_url() -> str:
    """Resolve database URL. Used by alembic and engine factory."""
    return get_settings().database_url


def to_config_dict(settings: Settings | None = None) -> dict[str, Any]:
    """Convert Settings to a legacy config dict for backward compatibility.

    Modules like analyzer.py and monitor.py still receive config as a dict.
    This function bridges the typed Settings to the old dict interface.
    """
    s = settings or get_settings()
    return {
        "rss_feeds": s.rss_feeds,
        "assets": s.seed_assets,
        "groq_model": s.groq_model,
        "lookback_hours": s.lookback_hours,
        "report_language": s.report_language,
        "database": {"url": s.database_url},
        "telegram": {
            "bot_token": s.telegram_bot_token,
            "chat_id": s.telegram_chat_id,
            "enabled": s.telegram_enabled,
        },
    }
