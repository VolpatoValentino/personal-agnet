import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

from fastapi import FastAPI
import uvicorn

from personal_agent.memory.db import init_db
from personal_agent.observability import setup_logfire

# Import routers directly
from personal_agent.agents.local.router import ROUTER as local_router
from personal_agent.agents.google.router import ROUTER as google_router

load_dotenv()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Create memory tables before any request can hit them.
    await init_db()
    yield


APP = FastAPI(title="GenAI APP", version="1.0.0", lifespan=_lifespan)
setup_logfire("personal-agent-api", instrument_fastapi_app=APP, instrument_httpx=True)

APP.include_router(local_router)
APP.include_router(google_router)

@APP.get("/")
def index():
    content = {"status": "OK"}
    return content

if __name__ == "__main__":
    uvicorn.run(
        APP,
        host=os.getenv("API_HOST", "127.0.0.1"),
        port=int(os.getenv("API_PORT", "8000")),
    )
