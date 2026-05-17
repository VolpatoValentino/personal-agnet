from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from api.app.routers.chat import build_chat_router
from core.agent.prompts import build_system_prompt
from core.agent.intent_classifier import TurnContext
from core.skills import render_skills_for

MODEL_NAME = "gemma-4-26B"

provider = OpenAIProvider(
    base_url="http://localhost:8080/v1",
    api_key="local",
)

model = OpenAIChatModel(MODEL_NAME, provider=provider)

AGENT = Agent(
    model,
    deps_type=TurnContext,
    instructions=build_system_prompt("running locally via llama.cpp"),
)


@AGENT.instructions
def _skill_fragments(ctx: RunContext[TurnContext]) -> str:
    return render_skills_for(ctx.deps.intents)


ROUTER = build_chat_router(
    prefix="agent",
    agent=AGENT,
    span_name="local_agent.chat",
    span_attributes={"model": MODEL_NAME},
    operation_id="agent_chat_endpoint",
)
