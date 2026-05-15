import os
from typing import Iterable

from pydantic_ai.mcp import MCPServer, MCPServerStdio, MCPServerStreamableHTTP

from api.app.routers._router import ALL_TOOL_INTENTS, Intent

LOGFIRE_BASE_URL = "https://logfire-eu.pydantic.dev"
GITHUB_MCP_URL = "https://api.githubcopilot.com/mcp/"


def get_mcp_server() -> MCPServerStreamableHTTP:
    mcp_server_url = os.getenv("MCP_SERVER_URL", "http://localhost:8081/mcp")
    return MCPServerStreamableHTTP(
        url=mcp_server_url,
        timeout=None,
        read_timeout=60,
    )


def get_logfire_mcp_server() -> MCPServerStdio | None:
    """Return the Logfire MCP toolset, or None if LOGFIRE_READ_TOKEN is not set.

    Logfire's MCP is a stdio server distributed as the `logfire-mcp` package.
    We launch it via `uvx` so users don't need to add it as a project dependency.
    """
    token = os.getenv("LOGFIRE_READ_TOKEN")
    if not token:
        return None
    return MCPServerStdio(
        command="uvx",
        args=["--from", "logfire-mcp", "logfire-mcp"],
        env={
            "LOGFIRE_READ_TOKEN": token,
            "LOGFIRE_BASE_URL": os.getenv("LOGFIRE_BASE_URL", LOGFIRE_BASE_URL),
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
        },
        tool_prefix="logfire",
    )


def get_github_mcp_server() -> MCPServerStreamableHTTP | None:
    """Return GitHub's hosted MCP toolset, or None if no PAT is configured.

    Uses the official remote endpoint at api.githubcopilot.com/mcp/ — no
    local install required. The PAT needs scopes for whatever you want the
    agent to do (repo, issues, pull_requests, ...).

    Trim what's exposed with GITHUB_MCP_TOOLSETS (e.g. "repos,issues",
    or "repos/readonly"). Default is all toolsets, which means ~70 tools
    and a strong selection bias from the model — set this to just what you
    actually want the agent to reach for.
    """
    token = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")
    if not token:
        return None

    explicit_url = os.getenv("GITHUB_MCP_URL")
    if explicit_url:
        url = explicit_url
    else:
        toolsets = os.getenv("GITHUB_MCP_TOOLSETS", "").strip().strip("/")
        url = f"{GITHUB_MCP_URL}x/{toolsets}" if toolsets else GITHUB_MCP_URL

    return MCPServerStreamableHTTP(
        url=url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
        read_timeout=60,
        tool_prefix="github",
    )


_LOCAL_INTENTS = frozenset({Intent.FILESYSTEM, Intent.GIT_LOCAL})


def get_toolsets(intents: Iterable[Intent] | None = None) -> list[MCPServer]:
    """Return only the MCP toolsets relevant to the given intents.

    If `intents` is None, returns every configured toolset (pre-Layer-1
    behavior). If `intents == {Intent.CHAT}` (or empty), returns no
    toolsets — the main agent runs without any tool menu, which is the
    point of the router.
    """
    selected: frozenset[Intent] = (
        ALL_TOOL_INTENTS if intents is None else frozenset(intents)
    )
    # CHAT alone => no tools. Any other intent overrides CHAT.
    if not selected or selected == frozenset({Intent.CHAT}):
        return []

    toolsets: list[MCPServer] = []
    # The local MCP server bundles fs + git + system tools, so both
    # FILESYSTEM and GIT_LOCAL intents load it (no double-mount needed).
    if selected & _LOCAL_INTENTS:
        toolsets.append(get_mcp_server())

    if Intent.LOGFIRE in selected:
        logfire_mcp = get_logfire_mcp_server()
        if logfire_mcp is not None:
            toolsets.append(logfire_mcp)

    if Intent.GITHUB in selected:
        github_mcp = get_github_mcp_server()
        if github_mcp is not None:
            toolsets.append(github_mcp)

    return toolsets
