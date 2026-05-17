"""FastAPI entrypoint for the personal-agent HTTP API.

Lifespan hook:
  - Creates SQLite memory tables (idempotent).
  - Logs whether bearer auth is enabled (loud warn if not — see security/auth.py).
  - Logs the LAN URL the API is listening on.

All chat routes are gated by `require_auth` (no-op when AGENT_AUTH_TOKEN is empty).
The root `/` route is intentionally unauthenticated so health probes and basic
reachability checks work without a token.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Depends, FastAPI
import logfire
import uvicorn

from api.app.configs.settings import SETTINGS
from api.app.security.auth import auth_enabled, log_startup_status, require_auth
from core.entity.db import init_db
from core.observability import setup_logfire

# Import the per-provider routers (these define their own /agent and
# /google_agent route prefixes).
from core.agent.local import ROUTER as local_router
from core.agent.google import ROUTER as google_router

load_dotenv()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    await init_db()
    log_startup_status()
    logfire.info(
        "api.listening",
        host=SETTINGS.api_host,
        port=SETTINGS.api_port,
        auth_enabled=auth_enabled(),
        message=(
            f"Agent API listening on http://{SETTINGS.api_host}:{SETTINGS.api_port} — "
            f"auth {'on' if auth_enabled() else 'OFF'}."
        ),
    )
    yield


APP = FastAPI(title="GenAI APP", version="1.0.0", lifespan=_lifespan)
setup_logfire("personal-agent-api", instrument_fastapi_app=APP, instrument_httpx=True)

# Bearer-auth applies to the agent chat routes — not to `/` (health probe).
APP.include_router(local_router, dependencies=[Depends(require_auth)])
APP.include_router(google_router, dependencies=[Depends(require_auth)])


@APP.get("/")
def index() -> dict:
    return {"status": "OK", "auth_required": auth_enabled()}


if __name__ == "__main__":
    uvicorn.run(APP, host=SETTINGS.api_host, port=SETTINGS.api_port)
