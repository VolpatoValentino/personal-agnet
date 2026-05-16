"""Defines the `ask_user` deferred tool.

The agent calls this when it needs a discrete decision from the user.
Because it's a *deferred* tool (declared via `DeferredToolset`), the agent
run pauses with a `DeferredToolRequests` output. The chat factory ships the
question over SSE, waits for the user's answer, and resumes the run via
`deferred_tool_results=`.

Only one ask_user call per turn is supported; the instructions tell the
model not to queue multiple.
"""
from __future__ import annotations

from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import DeferredToolset

ASK_USER_TOOL_NAME = "ask_user"

_ASK_USER_TOOL_DEFINITION = ToolDefinition(
    name=ASK_USER_TOOL_NAME,
    description=(
        "Ask the user a single discrete-choice question and wait for their "
        "answer. Use ONLY when you genuinely need a decision the user must "
        "make and the answer cannot be inferred (which approach to take, "
        "yes/no for an irreversible operation, picking between named "
        "alternatives). Do not use for greetings, acknowledgements, or to "
        "ask the user to paste data you can read yourself. Call at most "
        "once per response. The user's selected option string is returned."
    ),
    parameters_json_schema={
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The question to show the user, one short sentence.",
            },
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
                "maxItems": 4,
                "description": (
                    "Between 2 and 4 mutually exclusive options. Each should "
                    "be a short phrase the user can pick from."
                ),
            },
        },
        "required": ["question", "options"],
    },
)

ASK_USER_TOOLSET = DeferredToolset(tool_defs=[_ASK_USER_TOOL_DEFINITION])
