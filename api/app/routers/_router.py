from __future__ import annotations

import os
from enum import Enum
from typing import Iterable

import logfire
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider


class Intent(str, Enum):
    CHAT = "chat"
    FILESYSTEM = "filesystem"
    GIT_LOCAL = "git_local"
    GITHUB = "github"
    LOGFIRE = "logfire"


ALL_TOOL_INTENTS: frozenset[Intent] = frozenset(
    {Intent.FILESYSTEM, Intent.GIT_LOCAL, Intent.GITHUB, Intent.LOGFIRE}
)


class RouteDecision(BaseModel):
    intents: list[Intent] = Field(
        description=(
            "Minimal set of intents that cover the user's current message. "
            "Use ['chat'] alone for greetings, capability questions, or "
            "anything that doesn't require tools."
        ),
        min_length=1,
    )
    reason: str = Field(description="One short sentence explaining the choice.")


_ROUTER_INSTRUCTIONS = (
    "You are an intent classifier for a personal-agent system. Read the user's "
    "CURRENT message and pick the smallest set of intents needed to answer it. "
    "You do not answer the user; you only classify.\n"
    "\n"
    "Intents:\n"
    "  - chat: greetings, capability questions ('what can you do'), thanks, "
    "casual conversation, explanations the agent can give without touching "
    "any files, repos, or external services. If you pick chat, do NOT pick "
    "any other intent.\n"
    "  - filesystem: read files, list directories, inspect local file content.\n"
    "  - git_local: inspect or modify the user's LOCAL git working copy — "
    "status, diff, commit, push, log, branch operations. Also pick this for "
    "running tests, builds, or any shell command on the local machine.\n"
    "  - github: act on github.com via the API — list/create issues or pull "
    "requests, read remote repo contents, releases, workflow runs, search "
    "code on github.com. Pick this ONLY when the user explicitly names "
    "GitHub, a PR, an issue, a repository, a release, or 'remote'.\n"
    "  - logfire: query the user's own application traces, spans, metrics, "
    "or logs in Pydantic Logfire.\n"
    "\n"
    "Rules:\n"
    "  - Default to ['chat'] when in doubt.\n"
    "  - 'commit my changes' → ['git_local'] (NOT github, even if a push is "
    "involved — that's still local git).\n"
    "  - 'what's on my calendar' / 'send an email' → ['chat'] (no such tools "
    "exist; the agent will explain it can't).\n"
    "  - Multiple intents only when the message clearly spans them, e.g. "
    "'diff my changes and open a PR' → ['git_local', 'github'].\n"
    "\n"
    "Continuation rule (IMPORTANT for multi-turn): the input may include a "
    "PREVIOUS USER MESSAGE and PREVIOUS INTENTS section. If the CURRENT "
    "message is a short follow-up to that prior turn — confirmations ('yes', "
    "'ok', 'go ahead', 'do it', 'proceed'), nudges ('?', 'so?', 'and?', "
    "'continue', 'next'), or any clarification that does not introduce a "
    "new topic — INHERIT the previous intents. The user is still on the "
    "previous task, and the agent needs the same tools to finish it. Only "
    "switch to ['chat'] for follow-ups when the user is clearly closing the "
    "thread ('thanks', 'never mind', 'ok cool').\n"
    "\n"
    "Output only the JSON — no prose."
)


def _build_router_agent() -> Agent | None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    model_name = os.getenv("ROUTER_MODEL", "gemini-2.5-flash")
    model = GoogleModel(model_name, provider=GoogleProvider(api_key=api_key))
    return Agent(
        model,
        output_type=RouteDecision,
        instructions=_ROUTER_INSTRUCTIONS,
    )


_ROUTER_AGENT: Agent | None = _build_router_agent()


def _fallback_decision(reason: str) -> RouteDecision:
    return RouteDecision(intents=list(ALL_TOOL_INTENTS), reason=reason)


def _build_router_input(
    message: str,
    prior_message: str | None,
    prior_intents: Iterable[Intent] | None,
) -> str:
    if not prior_message:
        return f"CURRENT USER MESSAGE: {message}"
    intents_label = (
        ", ".join(i.value for i in prior_intents) if prior_intents else "chat"
    )
    prior_preview = prior_message if len(prior_message) <= 400 else prior_message[:400] + "..."
    return (
        f"PREVIOUS USER MESSAGE: {prior_preview}\n"
        f"PREVIOUS INTENTS: {intents_label}\n"
        f"\nCURRENT USER MESSAGE: {message}"
    )


async def classify(
    message: str,
    *,
    prior_message: str | None = None,
    prior_intents: Iterable[Intent] | None = None,
) -> RouteDecision:
    """Classify `message` into a `RouteDecision`. Never raises.

    Pass `prior_message` and `prior_intents` so the router can carry intent
    forward across short follow-ups like "yes", "?", "continue". Falls back
    to enabling every tool intent if the router can't run, so the system
    degrades to pre-Layer-1 behavior rather than locking the user out.
    """
    if _ROUTER_AGENT is None:
        return _fallback_decision("router disabled (no GEMINI_API_KEY)")

    router_input = _build_router_input(message, prior_message, prior_intents)

    with logfire.span(
        "intent_router.classify",
        message_length=len(message),
        has_prior=prior_message is not None,
    ) as span:
        try:
            result = await _ROUTER_AGENT.run(router_input)
            decision = result.output
            span.set_attribute("intents", [i.value for i in decision.intents])
            span.set_attribute("reason", decision.reason)
            return decision
        except Exception as exc:  # noqa: BLE001 - degrade gracefully
            logfire.warn("intent_router.failed", error=str(exc))
            return _fallback_decision(f"router error: {exc}")


def intent_set(intents: Iterable[Intent]) -> frozenset[Intent]:
    return frozenset(intents)
