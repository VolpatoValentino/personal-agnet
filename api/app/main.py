from fastapi import FastAPI
import uvicorn

from api.app.configs.constants import ROUTER_ATTRIBUTE
from api.app.utils.router_utils import get_routers, load_router

APP = FastAPI(title="GenAI APP", version="1.0.0")

for router in get_routers():
    if router != "agent":
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
    uvicorn.run(APP, host="0.0.0.0", port=8000)
