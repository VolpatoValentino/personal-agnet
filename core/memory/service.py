from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Sequence

import logfire
from pydantic_core import to_jsonable_python
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ToolCallPart,
    ToolReturnPart,
)
from sqlalchemy import select

from core.entity.db import SessionFactory
from core.entity.models import ConversationHistory


class AsyncMemoryService:
    def __init__(
        self,
        user_id: str,
        session_id: str,
        *,
        include_tool_calls: bool = True,
    ) -> None:
        self.user_id = user_id
        self.session_id = session_id
        self.include_tool_calls = include_tool_calls
        self.history: List[ModelMessage] = []
        self._new_messages: List[ModelMessage] = []
        self._session = None  # populated in __aenter__

    @staticmethod
    def _filter_tool_calls(messages: Sequence[ModelMessage]) -> List[ModelMessage]:
        return [
            m
            for m in messages
            if not any(isinstance(p, (ToolCallPart, ToolReturnPart)) for p in m.parts)
        ]

    async def _fetch_history(self) -> List[ModelMessage]:
        stmt = (
            select(ConversationHistory.message)
            .where(
                ConversationHistory.user_id == self.user_id,
                ConversationHistory.session_id == self.session_id,
            )
            .order_by(ConversationHistory.id.asc())
        )
        result = await self._session.execute(stmt)
        raw = [row for row in result.scalars()]
        if not raw:
            return []
        messages = ModelMessagesTypeAdapter.validate_python(raw)
        return messages if self.include_tool_calls else self._filter_tool_calls(messages)

    def record(self, new_messages: Sequence[ModelMessage]) -> None:
        # `new_messages` from pydantic-ai includes the user prompt + model
        # response(s) + any tool calls/returns. We persist all of them so a
        # restored session looks identical to the live one.
        self._new_messages.extend(new_messages)

    async def __aenter__(self) -> "AsyncMemoryService":
        self._session = SessionFactory()
        await self._session.__aenter__()
        with logfire.span(
            "memory.fetch_history",
            user_id=self.user_id,
            session_id=self.session_id,
        ) as span:
            self.history = await self._fetch_history()
            span.set_attribute("history_length", len(self.history))
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        try:
            if exc_type is None and self._new_messages:
                with logfire.span(
                    "memory.persist_history",
                    user_id=self.user_id,
                    session_id=self.session_id,
                    new_messages=len(self._new_messages),
                ):
                    now = datetime.now(timezone.utc)
                    self._session.add_all(
                        ConversationHistory(
                            user_id=self.user_id,
                            session_id=self.session_id,
                            created_at=now,
                            message=to_jsonable_python(m),
                        )
                        for m in self._new_messages
                    )
                    await self._session.commit()
        finally:
            await self._session.__aexit__(exc_type, exc, tb)
            self._session = None
        return False  # don't swallow exceptions


async def list_recent_sessions(user_id: str, limit: int = 20) -> List[dict]:
    from sqlalchemy import func

    async with SessionFactory() as s:
        stmt = (
            select(
                ConversationHistory.session_id.label("session_id"),
                func.min(ConversationHistory.created_at).label("started_at"),
                func.max(ConversationHistory.created_at).label("last_at"),
                func.count(ConversationHistory.id).label("message_count"),
            )
            .where(ConversationHistory.user_id == user_id)
            .group_by(ConversationHistory.session_id)
            .order_by(func.max(ConversationHistory.created_at).desc())
            .limit(limit)
        )
        rows = (await s.execute(stmt)).all()
        return [
            {
                "session_id": r.session_id,
                "started_at": r.started_at,
                "last_at": r.last_at,
                "message_count": r.message_count,
            }
            for r in rows
        ]
