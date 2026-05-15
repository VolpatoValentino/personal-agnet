import os

from dotenv import load_dotenv

from fastapi import FastAPI
import uvicorn

from api.app.configs.constants import ROUTER_ATTRIBUTE
from api.app.observability import setup_logfire
from api.app.utils.router_utils import get_routers, load_router

load_dotenv()
APP = FastAPI(title="GenAI APP", version="1.0.0")
setup_logfire("personal-agent-api", instrument_fastapi_app=APP, instrument_httpx=True)

for router in get_routers():
    if router not in ("agent", "google_agent"):
        continue
    router_module = load_router(router)

    if not getattr(router_module, ROUTER_ATTRIBUTE):
        continue

    APP.include_router(router_module.ROUTER)

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
