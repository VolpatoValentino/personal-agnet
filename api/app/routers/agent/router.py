import pathlib
from fastapi import APIRouter
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.mcp import MCPServerStreamableHTTP

PREFIX = "agent"
ROUTER = APIRouter(prefix=f"/{PREFIX}", tags=[PREFIX])

# Define connection to local llama-server
provider = OpenAIProvider(
    base_url='http://localhost:8080/v1',
    api_key='local'
)

model = OpenAIChatModel(
    'gemma-4-26B',
    provider=provider
)

# Connect to our local MCP Server running on port 8081
# FastMCP's streamable-http transport defaults to serving on the /mcp path
MCP_SERVER = MCPServerStreamableHTTP(
    timeout=60, url="http://localhost:8081/mcp"
)

# Create the agent with the HTTP MCP Server
AGENT = Agent(
    model,
    system_prompt=(
        "You are a helpful personal agent running locally on the user's PC. "
        "You have access to tools via MCP to help the user. "
        "Use them when necessary to fulfill the user's requests."
    ),
    toolsets=[MCP_SERVER]
)

class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    reply: str

@ROUTER.post("/chat", operation_id="agent_chat_endpoint")
async def chat_endpoint(request: ChatRequest):
    result = await AGENT.run(request.message)
    return ChatResponse(reply=result.output)
