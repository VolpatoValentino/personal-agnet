import asyncio
import os
from fastapi import FastAPI
from fastmcp import FastMCP
from fastmcp.server.providers.openapi import MCPType, RouteMap

from api.app.configs.constants import ROUTER_ATTRIBUTE
from api.app.utils.router_utils import get_routers, load_router

APP = FastAPI(title="FastAPI MCP Server", version="1.0.0")

for router in get_routers():
    if router != "tools_streamable_http":
        continue
    router_module = load_router(router)

    if not getattr(router_module, ROUTER_ATTRIBUTE):
        continue

    APP.include_router(router_module.ROUTER)

PATHS = {
    "/tools_streamable_http/current_time": True,
    "/tools_streamable_http/run_shell_command": True,
    "/tools_streamable_http/read_file": True,
    "/tools_streamable_http/list_directory": True,
    "/tools_streamable_http/git_status": True,
    "/tools_streamable_http/git_diff": True,
}

MCP_SERVER = FastMCP.from_fastapi(
    app=APP,
    route_maps=[
        RouteMap(
            methods=["POST"],
            pattern=rf"{path}.*",
            mcp_type=MCPType.TOOL if allowed else MCPType.EXCLUDE,
        )
        for path, allowed in PATHS.items()
    ],
)

@APP.get("/")
def index():
    content = {"status": "OK"}
    return content

if __name__ == "__main__":
    asyncio.run(
        MCP_SERVER.run_async(
            transport="streamable-http",
            host=os.getenv("HOST", "0.0.0.0"),
            port=int(os.getenv("PORT", 8081)),
            uvicorn_config={
                "workers": int(os.getenv("APP_WORKERS", 1)),
            },
        )
    )
