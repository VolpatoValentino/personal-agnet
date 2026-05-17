from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import logfire
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from core.entity.db import SessionFactory
from core.entity.models import ConversationHistory, SessionSummary

_IDLE_MINUTES = int(os.getenv("SUMMARIZER_IDLE_MINUTES", "30"))
_MAX_CHARS_PER_TURN = 600  # truncate long messages so the summarizer prompt stays small
_SUMMARY_INSTRUCTIONS = (
    "You are summarizing a single chat session between the user and a "
    "personal-agent assistant. Output ONE short paragraph (2-4 sentences) "
    "covering: what the user wanted, what was accomplished or attempted, "
    "and any decisions or open questions worth remembering for next time. "
    "Lead with the topic, not 'in this session'. No preamble, no bullets, "
    "no markdown headers. Plain text only."
)


def _build_summarizer() -> Agent | None:
    provider = os.getenv("SUMMARIZER_PROVIDER", "gemini").lower()
    if provider == "gemini":
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return None
        model_name = os.getenv("SUMMARIZER_MODEL", "gemini-2.5-flash")
        model = GoogleModel(model_name, provider=GoogleProvider(api_key=api_key))
    else:
        base_url = os.getenv("SUMMARIZER_BASE_URL", "http://localhost:8080/v1")
        api_key = os.getenv("SUMMARIZER_API_KEY", "local")
        model_name = os.getenv("SUMMARIZER_MODEL", "gemma-4-26B")
        model = OpenAIChatModel(
            model_name,
            provider=OpenAIProvider(base_url=base_url, api_key=api_key),
        )
    return Agent(model, instructions=_SUMMARY_INSTRUCTIONS)


_SUMMARIZER: Agent | None = _build_summarizer()


def _message_to_text(m: ModelMessage) -> str | None:
    role: str
    if isinstance(m, ModelRequest):
        # User prompts live as UserPromptPart inside a ModelRequest. Tool
        # returns are also ModelRequest but with ToolReturnPart parts.
        text_chunks = [
            p.content for p in m.parts if isinstance(p, UserPromptPart) and p.content
        ]
        if not text_chunks:
            return None
        role = "user"
    elif isinstance(m, ModelResponse):
        text_chunks = [p.content for p in m.parts if isinstance(p, TextPart) and p.content]
        if not text_chunks:
            return None
        role = "assistant"
    else:
        return None

    body = " ".join(str(c) for c in text_chunks).strip()
    if not body:
        return None
    if len(body) > _MAX_CHARS_PER_TURN:
        body = body[:_MAX_CHARS_PER_TURN] + "…"
    return f"{role}: {body}"


async def _load_session_text(user_id: str, session_id: str) -> tuple[str, int, datetime, datetime]:
    async with SessionFactory() as s:
        stmt = (
            select(
                ConversationHistory.message,
                ConversationHistory.created_at,
            )
            .where(
                ConversationHistory.user_id == user_id,
                ConversationHistory.session_id == session_id,
            )
            .order_by(ConversationHistory.id.asc())
        )
        rows = (await s.execute(stmt)).all()

    if not rows:
        return "", 0, datetime.now(timezone.utc), datetime.now(timezone.utc)

    raw = [r.message for r in rows]
    messages = ModelMessagesTypeAdapter.validate_python(raw)
    rendered = [t for t in (_message_to_text(m) for m in messages) if t]
    return (
        "\n".join(rendered),
        len(rows),
        rows[0].created_at,
        rows[-1].created_at,
    )


async def find_stale_unsummarized(
    user_id: str, *, exclude_session_id: str | None = None
) -> list[str]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=_IDLE_MINUTES)
    async with SessionFactory() as s:
        already_summarized_stmt = select(SessionSummary.session_id).where(
            SessionSummary.user_id == user_id
        )
        already_summarized = {row for row, in (await s.execute(already_summarized_stmt))}

        stmt = (
            select(
                ConversationHistory.session_id,
                func.max(ConversationHistory.created_at).label("last_at"),
            )
            .where(ConversationHistory.user_id == user_id)
            .group_by(ConversationHistory.session_id)
            .having(func.max(ConversationHistory.created_at) < cutoff)
        )
        rows = (await s.execute(stmt)).all()

    return [
        row.session_id
        for row in rows
        if row.session_id not in already_summarized
        and row.session_id != exclude_session_id
    ]


async def summarize_session(user_id: str, session_id: str) -> str | None:
    if _SUMMARIZER is None:
        logfire.warn("memory.summarizer_disabled", reason="no summarizer agent configured")
        return None

    with logfire.span(
        "memory.summarize_session", user_id=user_id, session_id=session_id
    ) as span:
        transcript, count, started, ended = await _load_session_text(user_id, session_id)
        if not transcript or count == 0:
            span.set_attribute("skipped", "empty_session")
            return None
        span.set_attribute("message_count", count)
        span.set_attribute("transcript_chars", len(transcript))

        try:
            result = await _SUMMARIZER.run(transcript)
            summary = (result.output or "").strip()
        except Exception as exc:  # noqa: BLE001 - degrade gracefully
            logfire.exception(
                "memory.summarize_failed", user_id=user_id, session_id=session_id
            )
            return None

        if not summary:
            return None

        async with SessionFactory() as s:
            stmt = sqlite_insert(SessionSummary).values(
                user_id=user_id,
                session_id=session_id,
                summary=summary,
                message_count=count,
                started_at=started,
                ended_at=ended,
            )
            # Idempotent: if we race with another summarizer, ignore.
            stmt = stmt.on_conflict_do_nothing(index_elements=["session_id"])
            await s.execute(stmt)
            await s.commit()

        span.set_attribute("summary_chars", len(summary))
        return summary


async def latest_summary(
    user_id: str, *, exclude_session_id: str | None = None
) -> str | None:
    async with SessionFactory() as s:
        stmt = (
            select(SessionSummary.summary)
            .where(SessionSummary.user_id == user_id)
            .order_by(SessionSummary.ended_at.desc())
            .limit(1)
        )
        if exclude_session_id:
            stmt = stmt.where(SessionSummary.session_id != exclude_session_id)
        result = await s.execute(stmt)
        row = result.first()
        return row.summary if row else None
