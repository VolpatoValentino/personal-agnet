from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
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


@dataclass
class TurnContext:
    """Per-turn context threaded into the agent as `deps`.

    The `@agent.instructions` decorator reads `intents` to decide which
    skill fragments to inject into the system prompt for this turn.
    """
    intents: list[Intent] = field(default_factory=lambda: [Intent.CHAT])


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


# --- regex classifier (used when ROUTER_PROVIDER=regex; local-friendly) ----

# Tight casual whitelist. If the message matches one of these AND has no
# tool keywords, classify as CHAT alone.
_CASUAL_RE = re.compile(
    r"^\s*(?:"
    r"hi+|hello+|hey+|yo|sup|"
    r"thanks?|thank you|ty|"
    r"good\s+(?:morning|afternoon|evening|night)|"
    r"bye+|goodbye|see you|cya|"
    r"ok(?:ay)?|cool|nice|got it|gotcha|"
    r"yes|yeah|yep|sure|"
    r"no|nope|nah|"
    r"what can you do|who are you|what are you|help"
    r")[\s!?.]*$",
    re.IGNORECASE,
)

# Per-intent keyword patterns. Each pattern matches anywhere in the message
# at word boundaries.
_INTENT_PATTERNS: dict[Intent, re.Pattern[str]] = {
    Intent.GITHUB: re.compile(
        r"\b(?:github|gh|pull request|\bpr\b|\bprs\b|\bissue\b|\bissues\b|"
        r"release|releases|workflow run|remote repo|github\.com|"
        r"repository on github)\b",
        re.IGNORECASE,
    ),
    Intent.GIT_LOCAL: re.compile(
        r"\b(?:git|commit|commits|\bdiff\b|\bpush\b|\bpull\b|\bmerge\b|"
        r"\brebase\b|\bstash\b|branch|branches|checkout|"
        r"status|\blog\b|\brun\b|\btest\b|\btests\b|\bbuild\b|"
        r"deploy|\buv run\b|\bnpm\b|\bpnpm\b|\bmake\b|"
        r"shell|terminal|run shell|run command|"
        r"working (?:copy|tree)|staged|unstaged)\b",
        re.IGNORECASE,
    ),
    Intent.FILESYSTEM: re.compile(
        # Keep verbs file-specific. Avoid bare "open" — it collides with
        # "open a PR". Path/code-fence detection (below) covers most
        # implicit FS cases anyway.
        r"\b(?:read\s+the\s+file|read\s+\S+\.\w+|show me\s+(?:the\s+)?(?:file|contents)|"
        r"inspect|look at\s+(?:the\s+)?(?:file|code)|"
        r"\bcat\b|\bls\b|list (?:the\s+)?(?:files|directory|folder|contents)|"
        r"\bfind\b\s+(?:files?|in\s+)|grep|"
        r"contents? of|what'?s in (?:the\s+)?(?:file|directory|folder)|"
        r"directory|folder)\b",
        re.IGNORECASE,
    ),
    Intent.LOGFIRE: re.compile(
        r"\b(?:logfire|trace|traces|\bspan\b|\bspans\b|telemetry|"
        r"observability|otel)\b",
        re.IGNORECASE,
    ),
}

# Path or code-fence detection — strong signal for FILESYSTEM at minimum.
_PATH_RE = re.compile(
    r"(?:[./~][\w./-]+|\b\w+\.(?:py|ts|js|tsx|jsx|md|toml|yml|yaml|json|sh|go|rs|java|css|html)\b)"
)
_FENCE_RE = re.compile(r"`[^`]+`|```")

# Continuation tokens — short follow-ups that should inherit prior intents.
# Matched against messages <= 40 chars: any continuation keyword inside the
# message triggers, so multi-word phrases like "yes go ahead" or "ok do it"
# work without enumerating every combination.
_CONTINUATION_RE = re.compile(
    r"\b(?:"
    r"yes|yeah|yep|sure|go ahead|do it|proceed|continue|"
    r"more|next|"
    r"so|and"
    r")\b|^\s*\?+\s*$",
    re.IGNORECASE,
)

# Closing tokens — short follow-ups that drop intent (back to CHAT).
_CLOSING_RE = re.compile(
    r"^\s*(?:"
    r"thanks?|thank you|ty|"
    r"never mind|nvm|forget it|"
    r"ok(?:ay)? cool|cool|nice|got it|gotcha|done|"
    r"bye+|goodbye|see you|cya"
    r")[\s!?.]*$",
    re.IGNORECASE,
)


def _regex_classify(
    message: str,
    *,
    prior_message: str | None = None,
    prior_intents: Iterable[Intent] | None = None,
) -> RouteDecision:
    """Regex/keyword classifier — no LLM round-trip.

    Decision order:
      1. Empty / whitespace → CHAT.
      2. Closing token after a prior tool turn → CHAT.
      3. Continuation token after a prior tool turn → inherit prior intents.
      4. Casual whitelist with no tool keywords → CHAT.
      5. Match per-intent patterns. Multiple matches yield multiple intents.
      6. Path/code-fence with no other match → FILESYSTEM.
      7. No match → return ALL_TOOL_INTENTS so the user isn't locked out.
    """
    text = (message or "").strip()
    if not text:
        return RouteDecision(intents=[Intent.CHAT], reason="empty message")

    prior_tool_intents = [
        i for i in (prior_intents or []) if i != Intent.CHAT
    ]

    # Short follow-ups
    if _CLOSING_RE.match(text):
        return RouteDecision(intents=[Intent.CHAT], reason="closing follow-up")
    if (
        len(text) <= 40
        and prior_tool_intents
        and _CONTINUATION_RE.search(text)
    ):
        return RouteDecision(
            intents=prior_tool_intents,
            reason="continuation; inheriting prior intents",
        )

    matched: list[Intent] = []
    # Order matters for "minimal set" preference: github before git_local so
    # "open a PR" doesn't also light up git_local on bare "push".
    for intent in (Intent.GITHUB, Intent.GIT_LOCAL, Intent.LOGFIRE, Intent.FILESYSTEM):
        if _INTENT_PATTERNS[intent].search(text):
            matched.append(intent)

    if not matched and (_PATH_RE.search(text) or _FENCE_RE.search(text)):
        matched.append(Intent.FILESYSTEM)

    if matched:
        return RouteDecision(
            intents=matched,
            reason=f"regex matched: {', '.join(i.value for i in matched)}",
        )

    if _CASUAL_RE.match(text):
        return RouteDecision(intents=[Intent.CHAT], reason="casual whitelist")

    # No signal at all. Fall back to enabling every tool intent — better to
    # over-attach than to strand the user.
    return RouteDecision(
        intents=list(ALL_TOOL_INTENTS),
        reason="regex: no keyword match; defaulting to all tool intents",
    )


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


_ROUTER_PROVIDER = os.getenv("ROUTER_PROVIDER", "gemini").lower()


async def classify(
    message: str,
    *,
    prior_message: str | None = None,
    prior_intents: Iterable[Intent] | None = None,
) -> RouteDecision:
    """Classify `message` into a `RouteDecision`. Never raises.

    Pass `prior_message` and `prior_intents` so the router can carry intent
    forward across short follow-ups like "yes", "?", "continue".

    Modes (selected via ROUTER_PROVIDER env var):
      - "gemini" (default): LLM-based classifier using Gemini. Most
        accurate but adds one network round-trip per turn.
      - "regex": pure keyword/regex matcher. No model call. Recommended
        for local-only dev (saves a llama.cpp round-trip per turn).

    Falls back to enabling every tool intent if the configured router
    can't run, so the system degrades gracefully rather than locking the
    user out.
    """
    if _ROUTER_PROVIDER == "regex":
        with logfire.span(
            "intent_router.classify",
            mode="regex",
            message_length=len(message),
            has_prior=prior_message is not None,
        ) as span:
            decision = _regex_classify(
                message,
                prior_message=prior_message,
                prior_intents=prior_intents,
            )
            span.set_attribute("intents", [i.value for i in decision.intents])
            span.set_attribute("reason", decision.reason)
            return decision

    if _ROUTER_AGENT is None:
        return _fallback_decision("router disabled (no GEMINI_API_KEY)")

    router_input = _build_router_input(message, prior_message, prior_intents)

    with logfire.span(
        "intent_router.classify",
        mode="gemini",
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
