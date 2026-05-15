import os

from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from pydantic_ai.providers.google import GoogleProvider

from api.app.routers._chat import build_chat_router
from api.app.routers._prompts import build_system_prompt

INSTRUCTIONS = build_system_prompt("connected to Google AI Studio")

DEFAULT_MODEL = "gemini-2.5-flash"
SELECTED_MODEL = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
THINKING_BUDGET = int(os.getenv("GOOGLE_THINKING_BUDGET", "1000"))

AISTUDIO_PROVIDER = GoogleProvider(api_key=os.getenv("GEMINI_API_KEY"))
AISTUDIO_MODEL = GoogleModel(SELECTED_MODEL, provider=AISTUDIO_PROVIDER)

AGENT = Agent(
    AISTUDIO_MODEL,
    model_settings=GoogleModelSettings(
        google_thinking_config={"thinking_budget": THINKING_BUDGET},
    ),
    instructions=INSTRUCTIONS,
)

ROUTER = build_chat_router(
    prefix="google_agent",
    agent=AGENT,
    span_name="google_agent.chat",
    span_attributes={"model": SELECTED_MODEL, "thinking_budget": THINKING_BUDGET},
    operation_id="google_agent_chat_endpoint",
)
