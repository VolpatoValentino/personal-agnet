import pathlib
import subprocess
import os
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

PREFIX = "tools_streamable_http"
ROUTER = APIRouter(prefix=f"/{PREFIX}", tags=[PREFIX])

class CommandRequest(BaseModel):
    command: str

class PathRequest(BaseModel):
    path: str

class GitDiffRequest(BaseModel):
    path: Optional[str] = None

@ROUTER.post("/current_time", operation_id="get_current_time")
def get_current_time() -> str:
    """Get the current local time."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

@ROUTER.post("/run_shell_command", operation_id="run_shell_command")
def run_shell_command(request: CommandRequest) -> str:
    """Run a shell command and return its output."""
    try:
        result = subprocess.run(request.command, shell=True, capture_output=True, text=True, check=True)
        return result.stdout or "Command executed successfully with no output."
    except subprocess.CalledProcessError as e:
        return f"Error executing command:\n{e.stderr}"

@ROUTER.post("/read_file", operation_id="read_file")
def read_file(request: PathRequest) -> str:
    """Read the contents of a file at the specified path."""
    try:
        with open(request.path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {str(e)}"

@ROUTER.post("/list_directory", operation_id="list_directory")
def list_directory(request: PathRequest) -> str:
    """List the contents of a directory at the specified path."""
    try:
        items = os.listdir(request.path)
        return "\n".join(items) if items else "Directory is empty."
    except Exception as e:
        return f"Error listing directory: {str(e)}"

@ROUTER.post("/git_status", operation_id="git_status")
def git_status(request: PathRequest) -> str:
    """Run 'git status' in the specified directory."""
    try:
        result = subprocess.run(
            ["git", "status"], 
            cwd=request.path, 
            capture_output=True, 
            text=True, 
            check=True
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        return f"Error running git status:\n{e.stderr}"
    except Exception as e:
        return f"Error: {str(e)}"

@ROUTER.post("/git_diff", operation_id="git_diff")
def git_diff(request: GitDiffRequest) -> str:
    """Run 'git diff' in the current working directory. Optionally specify a file path."""
    command = ["git", "diff"]
    if request.path:
        command.append(request.path)
        
    try:
        result = subprocess.run(
            command, 
            capture_output=True, 
            text=True, 
            check=True
        )
        return result.stdout or "No differences found."
    except subprocess.CalledProcessError as e:
        return f"Error running git diff:\n{e.stderr}"
    except Exception as e:
        return f"Error: {str(e)}"

