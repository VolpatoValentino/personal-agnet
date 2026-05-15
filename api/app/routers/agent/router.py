from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from api.app.routers._chat import build_chat_router
from api.app.routers._prompts import build_system_prompt

MODEL_NAME = "gemma-4-26B"

provider = OpenAIProvider(
    base_url="http://localhost:8080/v1",
    api_key="local",
)

model = OpenAIChatModel(MODEL_NAME, provider=provider)

AGENT = Agent(
    model,
    system_prompt=build_system_prompt("running locally via llama.cpp"),
)

ROUTER = build_chat_router(
    prefix="agent",
    agent=AGENT,
    span_name="local_agent.chat",
    span_attributes={"model": MODEL_NAME},
    operation_id="agent_chat_endpoint",
)
