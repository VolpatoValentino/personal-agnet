from __future__ import annotations

import os
from pathlib import Path

import logfire
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.entity.models import Base

_DEFAULT_DB_PATH = Path("data/agent.db")


def _db_path() -> Path:
    raw = os.getenv("MEMORY_DB_PATH")
    if raw:
        return Path(raw).expanduser()
    return _DEFAULT_DB_PATH


def _build_engine() -> AsyncEngine:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite+aiosqlite:///{path}"
    engine = create_async_engine(url, future=True)

    # Enable WAL + sensible defaults on every new sqlite connection.
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return engine


ENGINE: AsyncEngine = _build_engine()
SessionFactory = async_sessionmaker(ENGINE, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    with logfire.span("memory.init_db", path=str(_db_path())):
        async with ENGINE.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)


def user_id() -> str:
    return os.getenv("AGENT_USER_ID", "me")
