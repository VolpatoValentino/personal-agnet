import os
import subprocess
from typing import Optional

import logfire
from fastmcp import FastMCP

mcp = FastMCP("git")


def _resolve_cwd(path: Optional[str]) -> str:
    """Pick the working directory for a git call.

    If `path` names an existing directory, run there. Otherwise use the
    agent's configured working directory (AGENT_WORKING_DIRECTORY) or fall
    back to the MCP server's cwd.
    """
    if path and os.path.isdir(path):
        return path
    return os.getenv("AGENT_WORKING_DIRECTORY") or os.getcwd()


@mcp.tool(name="git_status")
def git_status(path: Optional[str] = None) -> str:
    """Run 'git status' in the given directory (defaults to the agent's working directory)."""
    cwd = _resolve_cwd(path)
    with logfire.span("mcp.git.git_status", path=path, cwd=cwd) as span:
        try:
            result = subprocess.run(
                ["git", "status"],
                cwd=cwd,
                capture_output=True,
                text=True,
                check=True,
            )
            span.set_attribute("stdout_length", len(result.stdout))
            return result.stdout
        except subprocess.CalledProcessError as e:
            logfire.warn("git status failed", path=path, cwd=cwd, exit_code=e.returncode, stderr=e.stderr)
            return f"Error running git status:\n{e.stderr}"
        except Exception as e:
            logfire.warn("git status crashed", path=path, cwd=cwd, error=str(e))
            return f"Error: {str(e)}"


@mcp.tool(name="git_diff")
def git_diff(path: Optional[str] = None) -> str:
    """Run 'git diff' in the agent's working directory.

    If `path` is a file, runs `git diff -- <path>` for just that file.
    If `path` is a directory or omitted, runs `git diff` over the whole repo.
    """
    cwd = _resolve_cwd(path if path and os.path.isdir(path) else None)
    command = ["git", "diff"]
    if path and not os.path.isdir(path):
        command += ["--", path]

    with logfire.span("mcp.git.git_diff", path=path, cwd=cwd) as span:
        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                check=True,
            )
            span.set_attribute("stdout_length", len(result.stdout))
            return result.stdout or "No differences found."
        except subprocess.CalledProcessError as e:
            logfire.warn("git diff failed", path=path, cwd=cwd, exit_code=e.returncode, stderr=e.stderr)
            return f"Error running git diff:\n{e.stderr}"
        except Exception as e:
            logfire.warn("git diff crashed", path=path, cwd=cwd, error=str(e))
            return f"Error: {str(e)}"
