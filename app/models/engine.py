"""Async database engine factory.

Creates the SQLAlchemy async engine and session factory.
Supports both SQLite (aiosqlite) and PostgreSQL (asyncpg).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker

from fastapi import Request


def get_engine(database_url: str) -> AsyncEngine:
    """Create an async engine from the database URL."""
    connect_args: dict = {}
    if database_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}

    return create_async_engine(
        database_url,
        echo=False,
        connect_args=connect_args,
    )


def get_session_factory(
    engine: AsyncEngine,
) -> sessionmaker[AsyncSession]:
    """Create an async session factory bound to the engine."""
    return sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db(request: Request):
    """FastAPI dependency that yields a database session per request."""
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        yield session
