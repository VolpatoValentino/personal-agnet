import subprocess
from datetime import datetime

import logfire
from fastmcp import FastMCP

mcp = FastMCP("system")

@mcp.tool(name="current_time")
def get_current_time() -> str:
    """Get the current local time."""
    with logfire.span("mcp.system.current_time"):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

@mcp.tool(name="run_shell_command")
def run_shell_command(command: str) -> str:
    """Run a shell command and return its output."""
    with logfire.span("mcp.system.run_shell_command", command=command) as span:
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, check=True)
            span.set_attribute("exit_code", result.returncode)
            span.set_attribute("stdout_length", len(result.stdout))
            return result.stdout or "Command executed successfully with no output."
        except subprocess.CalledProcessError as e:
            logfire.warn(
                "shell command failed",
                command=command,
                exit_code=e.returncode,
                stderr=e.stderr,
            )
            return f"Error executing command:\n{e.stderr}"
