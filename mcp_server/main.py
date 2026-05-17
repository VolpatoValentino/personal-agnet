from dotenv import load_dotenv

import os
from fastmcp import FastMCP

from core.observability import setup_logfire

from mcp_server.system import mcp as system_mcp
from mcp_server.fs import mcp as fs_mcp
from mcp_server.git import mcp as git_mcp


load_dotenv()
setup_logfire("personal-agent-mcp")
MCP_SERVER = FastMCP("main_mcp")

MCP_SERVER.add_provider(system_mcp)
MCP_SERVER.add_provider(fs_mcp)
MCP_SERVER.add_provider(git_mcp)

if __name__ == "__main__":
    MCP_SERVER.run(
        transport="streamable-http",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", 8081))
    )
