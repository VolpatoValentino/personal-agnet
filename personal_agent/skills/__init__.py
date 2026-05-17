"""Per-intent skill fragments injected into the agent's instructions at run time.

Layout under this package:

    skills/
      shared/      → loaded whenever ANY tool intent is selected
      filesystem/  → loaded when Intent.FILESYSTEM is selected
      git_local/   → loaded when Intent.GIT_LOCAL is selected
      github/      → loaded when Intent.GITHUB is selected
      logfire/     → loaded when Intent.LOGFIRE is selected

Each subdir contains `*.md` files; their content is concatenated with `---`
separators. Files are read once at import time and cached.

A casual turn (intents == [CHAT]) gets ZERO skill content — the base prompt
is enough.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Iterable

from personal_agent.agents.intent_classifier import Intent

_SKILLS_DIR = Path(__file__).parent
_SHARED = "shared"


def _read_skills(name: str) -> list[str]:
    """Return all `*.md` files under skills/<name>/ as a list of strings."""
    subdir = _SKILLS_DIR / name
    if not subdir.is_dir():
        return []
    return [p.read_text(encoding="utf-8").strip() for p in sorted(subdir.glob("*.md"))]


# Cache: load once at import time.
_BY_INTENT: dict[str, list[str]] = {
    _SHARED: _read_skills(_SHARED),
    Intent.FILESYSTEM.value: _read_skills(Intent.FILESYSTEM.value),
    Intent.GIT_LOCAL.value: _read_skills(Intent.GIT_LOCAL.value),
    Intent.GITHUB.value: _read_skills(Intent.GITHUB.value),
    Intent.LOGFIRE.value: _read_skills(Intent.LOGFIRE.value),
}


def render_skills_for(intents: Iterable[Intent]) -> str:
    """Concatenate skill fragments relevant to `intents`.

    Returns an empty string if `intents` is empty, is only CHAT, or no
    matching skill files exist. Result is cached per unique intent set so
    the rendered string is byte-stable across turns — important for
    llama.cpp's KV-cache reuse to hit on the prefix.
    """
    return _render_cached(frozenset(intents))


@lru_cache(maxsize=64)
def _render_cached(intent_set: frozenset[Intent]) -> str:
    if not intent_set or intent_set == {Intent.CHAT}:
        return ""

    pieces: list[str] = []
    # Shared skills apply to any tool intent.
    pieces.extend(_BY_INTENT.get(_SHARED, []))
    # Iterate intents in enum-declaration order so the output is stable
    # regardless of insertion order in the caller.
    for intent in Intent:
        if intent == Intent.CHAT or intent not in intent_set:
            continue
        pieces.extend(_BY_INTENT.get(intent.value, []))

    if not pieces:
        return ""
    return "\n\n---\n\n".join(pieces)
