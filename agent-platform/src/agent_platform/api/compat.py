"""兼容出口：SSE 事件（Dify / 云智）与响应 Envelope。"""
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


def agent_message_event(conversation_id: str, message_id: str, answer: str) -> dict[str, Any]:
    return {
        "event": "agent_message",
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
        "metadata": {"retriever_resources": trim_retriever_resources(retriever_resources or [])},
    }


def error_event(message: str) -> dict[str, Any]:
    return {"event": "error", "message": message}


def default_reply() -> str:
    return sse(message_end_event("", "", DEFAULT_REPLY))


def trim_retriever_resources(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """裁剪检索资源，仅保留 DifyUtil.trimMessageEndMetadata 依赖的字段。"""
    trimmed: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        trimmed.append(
            {
                "position": item.get("position", index + 1),
                "dataset_id": item.get("dataset_id", ""),
                "document_name": item.get("document_name", ""),
                "content": item.get("content", ""),
            }
        )
    return trimmed


# --------------------------------------------------------------------------- 通用 Envelope

def ok(data: Any = None) -> dict[str, Any]:
    """云智通用成功响应。"""
    return {"code": 200, "msg": "success", "data": data}


def fail(msg: str, code: int = 500) -> dict[str, Any]:
    return {"code": code, "msg": msg, "data": None}


def records(items: list[Any], total: int, current: int = 1, size: int = 20) -> dict[str, Any]:
    """云智直读库分页响应（data.records）。"""
    return ok({"records": items, "total": total, "current": current, "size": size})


def cloud_parameters(opening_statement: str, suggested_questions: list[str]) -> dict[str, Any]:
    """getCloudParameters：{code, data:{data:{opening_statement, suggested_questions}}}。"""
    return ok({"data": {"opening_statement": opening_statement, "suggested_questions": suggested_questions}})


def workflow_result(outputs: dict[str, Any], status: str = "succeeded", error: str = "") -> dict[str, Any]:
    """runWorkflow 嵌套 Envelope：data.data.data.{status, outputs, error}。"""
    return ok({"data": {"data": {"status": status, "outputs": outputs, "error": error}}})


# --------------------------------------------------------------------------- Dify 列表

def dify_list(items: list[Any], has_more: bool, limit: int = 20) -> dict[str, Any]:
    return {"data": items, "has_more": has_more, "limit": limit}


def dify_message_item(message: Any) -> dict[str, Any]:
    metadata = message.answer_metadata or {}
    return {
        "id": message.message_id,
        "conversation_id": "",
        "parent_message_id": message.parent_message_id or "",
        "query": message.query,
        "answer": message.answer,
        "feedback": message.feedback,
        "created_at": int(message.created_at.timestamp()) if message.created_at else 0,
        "metadata": {"retriever_resources": metadata.get("retriever_resources", [])},
    }


def dify_conversation_item(conversation: Any) -> dict[str, Any]:
    return {
        "id": conversation.conversation_id,
        "name": conversation.name,
        "inputs": {},
        "status": "normal",
        "introduction": "",
        "created_at": int(conversation.created_at.timestamp()) if conversation.created_at else 0,
        "updated_at": int(conversation.updated_at.timestamp()) if conversation.updated_at else 0,
    }
