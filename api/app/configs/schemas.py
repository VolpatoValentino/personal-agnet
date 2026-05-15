from typing import Optional
from pydantic import BaseModel

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None

class ChatResponse(BaseModel):
    reply: str
    session_id: str

class CommandRequest(BaseModel):
    command: str

class PathRequest(BaseModel):
    path: str

class GitDiffRequest(BaseModel):
    path: Optional[str] = None
