import subprocess
from typing import Optional

import logfire
from fastmcp import FastMCP

mcp = FastMCP("git")

@mcp.tool(name="git_status")
def git_status(path: str) -> str:
    """Run 'git status' in the specified directory."""
    with logfire.span("mcp.git.git_status", path=path) as span:
        try:
            result = subprocess.run(
                ["git", "status"],
                cwd=path,
                capture_output=True,
                text=True,
                check=True,
            )
            span.set_attribute("stdout_length", len(result.stdout))
            return result.stdout
        except subprocess.CalledProcessError as e:
            logfire.warn("git status failed", path=path, exit_code=e.returncode, stderr=e.stderr)
            return f"Error running git status:\n{e.stderr}"
        except Exception as e:
            logfire.warn("git status crashed", path=path, error=str(e))
            return f"Error: {str(e)}"

@mcp.tool(name="git_diff")
def git_diff(path: Optional[str] = None) -> str:
    """Run 'git diff' in the current working directory. Optionally specify a file path."""
    command = ["git", "diff"]
    if path:
        command.append(path)

    with logfire.span("mcp.git.git_diff", path=path) as span:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True,
            )
            span.set_attribute("stdout_length", len(result.stdout))
            return result.stdout or "No differences found."
        except subprocess.CalledProcessError as e:
            logfire.warn("git diff failed", path=path, exit_code=e.returncode, stderr=e.stderr)
            return f"Error running git diff:\n{e.stderr}"
        except Exception as e:
            logfire.warn("git diff crashed", path=path, error=str(e))
            return f"Error: {str(e)}"
