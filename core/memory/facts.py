from __future__ import annotations

import logfire
from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from core.entity.db import SessionFactory
from core.entity.models import UserFact


async def get_facts(user_id: str) -> dict[str, str]:
    async with SessionFactory() as s:
        stmt = (
            select(UserFact.key, UserFact.value)
            .where(UserFact.user_id == user_id)
            .order_by(UserFact.key.asc())
        )
        rows = (await s.execute(stmt)).all()
        return {key: value for key, value in rows}


async def set_fact(user_id: str, key: str, value: str) -> None:
    key = (key or "").strip()
    value = (value or "").strip()
    if not key or not value:
        return
    with logfire.span("memory.set_fact", user_id=user_id, key=key, value_length=len(value)):
        async with SessionFactory() as s:
            stmt = sqlite_insert(UserFact).values(
                user_id=user_id, key=key, value=value
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["user_id", "key"],
                set_={"value": stmt.excluded.value},
            )
            await s.execute(stmt)
            await s.commit()


async def delete_fact(user_id: str, key: str) -> bool:
    key = (key or "").strip()
    if not key:
        return False
    with logfire.span("memory.delete_fact", user_id=user_id, key=key) as span:
        async with SessionFactory() as s:
            stmt = delete(UserFact).where(
                UserFact.user_id == user_id, UserFact.key == key
            )
            result = await s.execute(stmt)
            await s.commit()
            span.set_attribute("deleted_rows", result.rowcount or 0)
            return (result.rowcount or 0) > 0


def render_facts_prompt(facts: dict[str, str]) -> str:
    if not facts:
        return ""
    lines = ["## What you remember about the user"]
    for key, value in facts.items():
        lines.append(f"- **{key}**: {value}")
    return "\n".join(lines)
