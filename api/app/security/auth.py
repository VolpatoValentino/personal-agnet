"""Bearer-token auth for the agent's HTTP API.

Threat model: the API binds to `0.0.0.0` so the agent is reachable from
phone / laptop / work box on the same LAN. The token gates everything
the agent can do — that's a GitHub PAT, shell on the desktop, the lot.
Anyone on your home network (including IoT devices) shouldn't get
ambient access just because the desktop is on.

UX:
  - `AGENT_AUTH_TOKEN` set (non-empty) → enforced. Requests without
    `Authorization: Bearer <token>` get 401.
  - `AGENT_AUTH_TOKEN` unset / empty → **auth disabled** with a loud
    warning at startup. Useful for early dev; ship to the desktop with
    it set.

Generate a token with: `make generate-token` (or
`python -c 'import secrets; print(secrets.token_urlsafe(32))'`).
"""
from __future__ import annotations

import secrets

import logfire
from fastapi import Header, HTTPException, status

from api.app.configs.settings import SETTINGS


def _expected_token() -> str | None:
    """The configured token, or None if auth is disabled."""
    raw = (SETTINGS.agent_auth_token or "").strip()
    return raw or None


def auth_enabled() -> bool:
    return _expected_token() is not None


async def require_auth(authorization: str | None = Header(default=None)) -> None:
    """FastAPI dependency that enforces `Authorization: Bearer <token>`.

    Constant-time comparison via `secrets.compare_digest` so we don't leak
    the token length / prefix via timing.
    """
    expected = _expected_token()
    if expected is None:
        # Auth intentionally disabled — already warned at startup.
        return

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    provided = authorization[len("bearer ") :].strip()
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def log_startup_status() -> None:
    """Emit a one-line summary of the auth state at server startup.

    Designed to be noisy when auth is off (matches the threat model) and
    succinct when it's on. Surfaces in both Logfire and stderr.
    """
    if auth_enabled():
        logfire.info(
            "auth.enabled",
            message=(
                "AGENT_AUTH_TOKEN is set; bearer auth required for /agent and "
                "/google_agent routes."
            ),
        )
    else:
        # Loud — easy to miss WARN in dev otherwise.
        logfire.warn(
            "auth.DISABLED",
            message=(
                "AGENT_AUTH_TOKEN is NOT set — the API is wide open. "
                "Anyone who can reach this port (including LAN) can use the agent. "
                "Set AGENT_AUTH_TOKEN in .env before exposing this beyond localhost."
            ),
        )
