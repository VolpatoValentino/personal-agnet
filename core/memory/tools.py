from __future__ import annotations

from pydantic_ai import Agent, RunContext

from core.memory.facts import delete_fact, set_fact
from core.agent.intent_classifier import TurnContext


def attach_memory_tools(agent: Agent[TurnContext, str]) -> None:
    @agent.tool
    async def remember_fact(
        ctx: RunContext[TurnContext], key: str, value: str
    ) -> str:
        await set_fact(ctx.deps.user_id, key, value)
        return f"Remembered: {key} = {value}"

    @agent.tool
    async def forget_fact(ctx: RunContext[TurnContext], key: str) -> str:

        deleted = await delete_fact(ctx.deps.user_id, key)
        return f"Forgot {key}" if deleted else f"No fact named {key} was stored."
