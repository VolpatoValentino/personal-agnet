from typing import Optional
from pydantic import BaseModel

class ChatAnswer(BaseModel):
    call_id: str
    value: str


class ChatRequest(BaseModel):
    """A chat turn.

    The client sends either a fresh user `message` OR an `answer` to a
    pending `ask_user` deferred tool call from a prior turn (identified by
    its `call_id`). Sending both is allowed and treated as: answer first,
    then a follow-up message — but in practice the CLI sends one at a time.
    """

    message: Optional[str] = None
    session_id: Optional[str] = None
    answer: Optional[ChatAnswer] = None


class ChatResponse(BaseModel):
    reply: str
    session_id: str

class CommandRequest(BaseModel):
    command: str

class PathRequest(BaseModel):
    path: str

class GitDiffRequest(BaseModel):
    path: Optional[str] = None
