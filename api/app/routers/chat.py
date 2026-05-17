"""Shared chat-endpoint factory used by every per-provider agent router.

Conversation history is persisted in SQLite (see `core/memory/`,
`core/entity/`) — the agent picks up where the session left off even
after the server restarts. Pending `ask_user` calls and the intent
router's prior-turn hint are still in-process state (they only matter
for the *current* in-flight turn and are cheap to lose on restart).

Streaming endpoint supports the `ask_user` deferred tool: when the agent
calls it, the run pauses with a `DeferredToolRequests` output. The server
ships the question to the client over SSE and stashes the pending state.
The client posts back with `request.answer = {call_id, value}` and the
server resumes the run via `deferred_tool_results`.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from typing import Any, AsyncIterator

import logfire
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage
from pydantic_ai.tools import DeferredToolRequests, DeferredToolResults

from api.app.configs.schemas.chat import ChatRequest, ChatResponse
from core.agent.ask_user import ASK_USER_TOOL_NAME, ASK_USER_TOOLSET
from core.agent.intent_classifier import Intent, TurnContext, classify
from core.client.mcp import get_toolsets
from core.entity.db import user_id as default_user_id
from core.memory.facts import get_facts
from core.memory.service import AsyncMemoryService
from core.memory.summaries import (
    find_stale_unsummarized,
    latest_summary,
    summarize_session,
)

# session_id -> (last user message, last classified intents). In-process
# only; if missing, the next turn just re-classifies.
_PRIOR_TURNS: dict[str, tuple[str, list[Intent]]] = {}


@dataclass
class _PendingQuestion:
    call_id: str
    question: str
    options: list[str]
    intents: list[Intent]


# session_id -> currently-pending ask_user call (if any). In-process: a
# pending question only matters for the next request from this exact
# client. If the server restarts mid-question, the client gets an error
# and can retry the original message.
_PENDING_QUESTIONS: dict[str, _PendingQuestion] = {}


def _sse(event: dict[str, Any]) -> str:
    """Encode a dict as a single Server-Sent Events frame."""
    return f"data: {json.dumps(event, default=str)}\n\n"


def _coerce_args(args: Any) -> dict[str, Any]:
    """Tool-call args from pydantic-ai can be a dict or a JSON string."""
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        try:
            return json.loads(args)
        except json.JSONDecodeError:
            return {}
    return {}


def _streaming_toolsets(intents: list[Intent]) -> list:
    """Tools the streaming endpoint exposes: intent-gated MCPs + ask_user."""
    return [*get_toolsets(intents), ASK_USER_TOOLSET]


async def _summarize_stale_sessions_bg(user_id: str, current_session_id: str) -> None:
    """Fire-and-forget: summarize any idle sessions that don't have a
    summary yet. Errors are logged and swallowed — episodic memory is
    nice-to-have, never break a user-facing turn for it.
    """
    try:
        stale = await find_stale_unsummarized(
            user_id, exclude_session_id=current_session_id
        )
        for sid in stale:
            await summarize_session(user_id, sid)
    except Exception:  # noqa: BLE001
        logfire.exception("memory.bg_summarize_failed", user_id=user_id)


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
    """
    router = APIRouter(prefix=f"/{prefix}", tags=[prefix])
    base_attrs = dict(span_attributes or {})

    @router.post("/chat", operation_id=operation_id or f"{prefix}_chat_endpoint")
    async def chat_endpoint(request: ChatRequest) -> ChatResponse:
        if not request.message:
            return ChatResponse(reply="Empty message.", session_id=request.session_id or "")
        session_id = request.session_id or str(uuid.uuid4())
        uid = default_user_id()

        async with AsyncMemoryService(uid, session_id) as mem:
            with logfire.span(
                span_name,
                user_id=uid,
                session_id=session_id,
                history_length=len(mem.history),
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

                facts = await get_facts(uid)
                span.set_attribute("user_facts_count", len(facts))

                recent: str | None = None
                if not mem.history:
                    recent = await latest_summary(uid, exclude_session_id=session_id)
                    span.set_attribute("has_recent_summary", recent is not None)
                    asyncio.create_task(_summarize_stale_sessions_bg(uid, session_id))

                # Blocking endpoint intentionally does NOT expose ask_user —
                # the request/response model can't handle a paused run.
                result = await agent.run(
                    request.message,
                    message_history=mem.history,
                    toolsets=get_toolsets(decision.intents),
                    deps=TurnContext(
                        intents=list(decision.intents),
                        user_id=uid,
                        user_facts=facts,
                        recent_summary=recent,
                    ),
                )
                mem.record(result.new_messages())
                _PRIOR_TURNS[session_id] = (request.message, list(decision.intents))
                span.set_attribute("reply_length", len(result.output))
                return ChatResponse(reply=result.output, session_id=session_id)

    stream_op_id = (
        f"{operation_id}_stream" if operation_id else f"{prefix}_chat_stream_endpoint"
    )

    @router.post("/chat/stream", operation_id=stream_op_id)
    async def chat_stream_endpoint(request: ChatRequest) -> StreamingResponse:
        session_id = request.session_id or str(uuid.uuid4())
        uid = default_user_id()

        async def event_source() -> AsyncIterator[str]:
            yield _sse({"type": "session", "session_id": session_id})

            async with AsyncMemoryService(uid, session_id) as mem:
                with logfire.span(
                    span_name + ".stream",
                    user_id=uid,
                    session_id=session_id,
                    history_length=len(mem.history),
                    has_message=request.message is not None,
                    has_answer=request.answer is not None,
                    **base_attrs,
                ) as span:
                    try:
                        deferred_results: DeferredToolResults | None = None
                        intents: list[Intent]

                        if request.answer is not None:
                            pending = _PENDING_QUESTIONS.pop(session_id, None)
                            if pending is None or pending.call_id != request.answer.call_id:
                                yield _sse({
                                    "type": "error",
                                    "message": "No matching pending question for this session.",
                                })
                                return
                            intents = pending.intents
                            deferred_results = DeferredToolResults(
                                calls={request.answer.call_id: request.answer.value}
                            )
                            span.set_attribute("resumed_from_question", True)
                            yield _sse({
                                "type": "intent",
                                "intents": [i.value for i in intents],
                                "reason": "resuming after ask_user answer",
                            })
                            user_prompt: str | None = None
                        elif request.message is not None:
                            prior = _PRIOR_TURNS.get(session_id)
                            decision = await classify(
                                request.message,
                                prior_message=prior[0] if prior else None,
                                prior_intents=prior[1] if prior else None,
                            )
                            intents = list(decision.intents)
                            span.set_attribute("intents", [i.value for i in intents])
                            span.set_attribute("intent_reason", decision.reason)
                            yield _sse({
                                "type": "intent",
                                "intents": [i.value for i in intents],
                                "reason": decision.reason,
                            })
                            _PENDING_QUESTIONS.pop(session_id, None)
                            user_prompt = request.message
                        else:
                            yield _sse({
                                "type": "error",
                                "message": "Request must include either `message` or `answer`.",
                            })
                            return

                        facts = await get_facts(uid)
                        span.set_attribute("user_facts_count", len(facts))

                        recent: str | None = None
                        if not mem.history:
                            recent = await latest_summary(
                                uid, exclude_session_id=session_id
                            )
                            span.set_attribute("has_recent_summary", recent is not None)
                            asyncio.create_task(
                                _summarize_stale_sessions_bg(uid, session_id)
                            )

                        total_chars = 0
                        final_output: Any = None

                        async with agent.run_stream(
                            user_prompt,
                            message_history=mem.history,
                            toolsets=_streaming_toolsets(intents),
                            deps=TurnContext(
                                intents=list(intents),
                                user_id=uid,
                                user_facts=facts,
                                recent_summary=recent,
                            ),
                            output_type=[str, DeferredToolRequests],
                            deferred_tool_results=deferred_results,
                        ) as result:
                            async for delta in result.stream_text(delta=True):
                                if not delta:
                                    continue
                                total_chars += len(delta)
                                yield _sse({"type": "text", "text": delta})
                            final_output = await result.get_output()
                            mem.record(result.new_messages())

                        if user_prompt is not None:
                            _PRIOR_TURNS[session_id] = (user_prompt, list(intents))
                        span.set_attribute("reply_length", total_chars)

                        if isinstance(final_output, DeferredToolRequests) and final_output.calls:
                            call = final_output.calls[0]
                            if call.tool_name != ASK_USER_TOOL_NAME:
                                yield _sse({
                                    "type": "error",
                                    "message": f"Unsupported deferred tool: {call.tool_name}",
                                })
                                return
                            args = _coerce_args(call.args)
                            question = args.get("question") or "(no question)"
                            options = args.get("options") or []
                            if not isinstance(options, list) or len(options) < 2:
                                options = ["Yes", "No"]
                            _PENDING_QUESTIONS[session_id] = _PendingQuestion(
                                call_id=call.tool_call_id,
                                question=question,
                                options=[str(o) for o in options],
                                intents=intents,
                            )
                            span.set_attribute("asked_user", True)
                            yield _sse({
                                "type": "question",
                                "call_id": call.tool_call_id,
                                "question": question,
                                "options": [str(o) for o in options],
                            })
                            yield _sse({"type": "awaiting_answer"})
                            return

                        yield _sse({"type": "done"})
                    except Exception as exc:  # noqa: BLE001 - report to client
                        logfire.exception("chat_stream_failed", session_id=session_id)
                        yield _sse({"type": "error", "message": str(exc)})

        return StreamingResponse(
            event_source(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    return router
