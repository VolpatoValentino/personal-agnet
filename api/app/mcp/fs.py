import os
import logfire
from fastmcp import FastMCP

mcp = FastMCP("fs")

@mcp.tool(name="read_file")
def read_file(path: str) -> str:
    """Read the contents of a file at the specified path."""
    with logfire.span("mcp.fs.read_file", path=path) as span:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            span.set_attribute("bytes_read", len(content))
            return content
        except Exception as e:
            logfire.warn("read_file failed", path=path, error=str(e))
            return f"Error reading file: {str(e)}"

@mcp.tool(name="list_directory")
def list_directory(path: str) -> str:
    """List the contents of a directory at the specified path."""
    with logfire.span("mcp.fs.list_directory", path=path) as span:
        try:
            items = os.listdir(path)
            span.set_attribute("item_count", len(items))
            return "\n".join(items) if items else "Directory is empty."
        except Exception as e:
            logfire.warn("list_directory failed", path=path, error=str(e))
            return f"Error listing directory: {str(e)}"
