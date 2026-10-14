"""请求/响应 schema（兼容云智 / Dify）。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatMessagesRequest(BaseModel):
    query: str = ""
    inputs: dict[str, Any] = Field(default_factory=dict)
    user: str = ""
    conversation_id: str = ""
    response_mode: str = "streaming"
    files: list[dict[str, Any]] = Field(default_factory=list)


class OpeningInfo(BaseModel):
    opening_statement: str = ""
    opening_questions: list[str] = Field(default_factory=list)
