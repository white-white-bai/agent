"""兼容出口：SSE（Dify / 云智 事件格式）。"""
from __future__ import annotations

import json
from typing import Any

DEFAULT_REPLY = "智能客服为您解答政务服务领域的问题，超出领域的问题不在能力之内哦！"


def sse(payload: dict[str, Any]) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


def message_event(conversation_id: str, message_id: str, answer: str) -> dict[str, Any]:
    return {
        "event": "message",
        "conversation_id": conversation_id,
        "message_id": message_id,
        "answer": answer,
    }


def message_end_event(
    conversation_id: str, message_id: str, answer: str = "", retriever_resources: list | None = None
) -> dict[str, Any]:
    return {
        "event": "message_end",
        "conversation_id": conversation_id,
        "message_id": message_id,
        "answer": answer,
        "metadata": {"retriever_resources": retriever_resources or []},
    }


def error_event(message: str) -> dict[str, Any]:
    return {"event": "error", "message": message}


def default_reply() -> str:
    return sse(message_end_event("", "", DEFAULT_REPLY))
