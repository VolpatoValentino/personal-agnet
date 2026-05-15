"""Shared chat-endpoint factory used by the local and Google agent routers.

Holds per-session conversation history in-process so multi-turn chats
work without an external store. Restarting the API clears all sessions.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, AsyncIterator

import logfire
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage

from api.app.configs.schemas import ChatRequest, ChatResponse
from api.app.routers._router import Intent, classify
from api.app.utils.mcp_utils import get_toolsets

# session_id -> message history
_SESSIONS: dict[str, list[ModelMessage]] = {}
# session_id -> (last user message, last classified intents) — used to give
# the intent router context for short follow-ups like "yes" / "?" / "go".
_PRIOR_TURNS: dict[str, tuple[str, list[Intent]]] = {}


def _sse(event: dict[str, Any]) -> str:
    """Encode a dict as a single Server-Sent Events frame."""
    return f"data: {json.dumps(event, default=str)}\n\n"


def build_chat_router(
    *,
    prefix: str,
    agent: Agent,
    span_name: str,
    span_attributes: dict[str, Any] | None = None,
    operation_id: str | None = None,
) -> APIRouter:
    """Build a router exposing `POST /{prefix}/chat` (blocking JSON) and
    `POST /{prefix}/chat/stream` (Server-Sent Events) backed by `agent`.

    History is keyed by `session_id`: if the client doesn't send one, a new
    UUID is allocated and returned, and subsequent calls with that id will
    continue the same conversation.
    """
    router = APIRouter(prefix=f"/{prefix}", tags=[prefix])
    base_attrs = dict(span_attributes or {})

    @router.post("/chat", operation_id=operation_id or f"{prefix}_chat_endpoint")
    async def chat_endpoint(request: ChatRequest) -> ChatResponse:
        session_id = request.session_id or str(uuid.uuid4())
        history = _SESSIONS.get(session_id, [])

        with logfire.span(
            span_name,
            session_id=session_id,
            history_length=len(history),
            message_length=len(request.message),
            **base_attrs,
        ) as span:
            prior = _PRIOR_TURNS.get(session_id)
            decision = await classify(
                request.message,
                prior_message=prior[0] if prior else None,
                prior_intents=prior[1] if prior else None,
            )
            span.set_attribute("intents", [i.value for i in decision.intents])
            span.set_attribute("intent_reason", decision.reason)

            result = await agent.run(
                request.message,
                message_history=history,
                toolsets=get_toolsets(decision.intents),
            )
            _SESSIONS[session_id] = result.all_messages()
            _PRIOR_TURNS[session_id] = (request.message, list(decision.intents))
            span.set_attribute("reply_length", len(result.output))
            return ChatResponse(reply=result.output, session_id=session_id)

    stream_op_id = (
        f"{operation_id}_stream" if operation_id else f"{prefix}_chat_stream_endpoint"
    )

    @router.post("/chat/stream", operation_id=stream_op_id)
    async def chat_stream_endpoint(request: ChatRequest) -> StreamingResponse:
        session_id = request.session_id or str(uuid.uuid4())
        history = _SESSIONS.get(session_id, [])

        async def event_source() -> AsyncIterator[str]:
            with logfire.span(
                span_name + ".stream",
                session_id=session_id,
                history_length=len(history),
                message_length=len(request.message),
                **base_attrs,
            ) as span:
                yield _sse({"type": "session", "session_id": session_id})
                total_chars = 0
                try:
                    prior = _PRIOR_TURNS.get(session_id)
                    decision = await classify(
                        request.message,
                        prior_message=prior[0] if prior else None,
                        prior_intents=prior[1] if prior else None,
                    )
                    span.set_attribute("intents", [i.value for i in decision.intents])
                    span.set_attribute("intent_reason", decision.reason)
                    yield _sse({
                        "type": "intent",
                        "intents": [i.value for i in decision.intents],
                        "reason": decision.reason,
                    })

                    async with agent.run_stream(
                        request.message,
                        message_history=history,
                        toolsets=get_toolsets(decision.intents),
                    ) as result:
                        async for delta in result.stream_text(delta=True):
                            if not delta:
                                continue
                            total_chars += len(delta)
                            yield _sse({"type": "text", "text": delta})
                        _SESSIONS[session_id] = result.all_messages()
                        _PRIOR_TURNS[session_id] = (request.message, list(decision.intents))
                    span.set_attribute("reply_length", total_chars)
                    yield _sse({"type": "done"})
                except Exception as exc:  # noqa: BLE001 - report to client
                    logfire.exception("chat_stream_failed", session_id=session_id)
                    yield _sse({"type": "error", "message": str(exc)})

        return StreamingResponse(
            event_source(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",  # disable proxy buffering if any
            },
        )

    return router
