"""Configuration loader for the web app.

Reads config.yaml and provides FastAPI dependencies for injecting
configuration into endpoints.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


@lru_cache()
def load_config(path: str | None = None) -> dict:
    """Load and validate the YAML config file.

    Raises ValueError if the config is invalid.
    """
    config_path = Path(path) if path else _CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if not config:
        raise ValueError(f"Configuration file is empty: {config_path}")

    if not config.get("assets"):
        raise ValueError("'assets' missing or empty in config")

    for i, asset in enumerate(config["assets"]):
        if not asset.get("symbol"):
            raise ValueError(f"assets[{i}]: 'symbol' missing")

    if not config.get("rss_feeds"):
        raise ValueError("'rss_feeds' missing or empty in config")

    return config


def reload_config() -> dict:
    """Clear the cache and reload config from disk."""
    load_config.cache_clear()
    return load_config()


def save_config(config: dict, path: str | None = None) -> None:
    """Write the config dict back to config.yaml, preserving comments where possible."""
    config_path = Path(path) if path else _CONFIG_PATH
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def get_database_url() -> str:
    """Resolve database URL.

    Priority: DATABASE_URL env var > config.yaml > default SQLite.
    """
    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        return env_url

    config = load_config()
    return config.get("database", {}).get(
        "url", "sqlite+aiosqlite:///./trading.db"
    )


def get_config() -> dict:
    """FastAPI dependency that returns the cached config."""
    return load_config()
