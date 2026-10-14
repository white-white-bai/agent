"""兼容出口路由：云智封装层（/api/oauth2/token、/api/transfer/one/*、/api/open/dify/*）+ 原始 Dify /v1/*。"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, UploadFile

from agent_platform.api import compat, services
from agent_platform.api.deps import get_engine_context
from agent_platform.api.schemas import (
    DirectQueryRequest,
    FeedbackRequest,
    RenameRequest,
    TokenRequest,
    WorkflowRunRequest,
)
from agent_platform.core.security import AuthError, check_client, issue_token, resolve_api_key
from agent_platform.engine.context import EngineContext
from agent_platform.engine.runtime import run_graph

router = APIRouter(tags=["compat"])


def _headers(api_key_header: str | None, authorization: str | None, *, require_token: bool = False) -> str:
    try:
        return resolve_api_key(api_key_header, authorization, require_token=require_token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _require_app(api_key: str) -> Any:
    app_record = services.get_app_by_key(api_key)
    if app_record is None:
        raise HTTPException(status_code=401, detail="无效的 Api-Key")
    return app_record


def _app_by_identifier(identifier: str) -> Any:
    if not identifier:
        raise HTTPException(status_code=400, detail="缺少 appId")
    app_record = services.get_app_by_app_id(identifier) or services.get_app_by_uuid(identifier)
    if app_record is None:
        raise HTTPException(status_code=404, detail="应用不存在")
    return app_record


def _paginate(items: list[Any], page: int, size: int) -> list[Any]:
    start = max(page - 1, 0) * size
    return items[start : start + size]


# --------------------------------------------------------------------------- 云智鉴权

@router.post("/api/oauth2/token")
def oauth2_token(request: TokenRequest) -> dict[str, Any]:
    if not check_client(request.client_id, request.client_secret):
        raise HTTPException(status_code=401, detail="client 鉴权失败")
    token, expire = issue_token(request.client_id)
    return compat.ok({"token": token, "expire": expire})


# --------------------------------------------------------------------------- 云智 transfer

@router.get("/api/transfer/one/chat-messages/conversations")
def cloud_conversations(
    user: str = "",
    limit: int = 20,
    api_key_header: str | None = Header(default=None, alias="Api-Key"),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    app_record = _require_app(_headers(api_key_header, authorization, require_token=True))
    rows = services.list_conversations(app_record.uuid, user, limit=limit)
    total = services.count_conversations(app_record.uuid, user)
    return compat.records([compat.dify_conversation_item(row) for row in rows], total, size=limit)


@router.post("/api/transfer/one/chat-messages/conversations/rename")
def cloud_rename_conversation(
    request: RenameRequest,
    conversation_id: str = "",
    api_key_header: str | None = Header(default=None, alias="Api-Key"),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_app(_headers(api_key_header, authorization, require_token=True))
    row = services.rename_conversation(conversation_id, request.name, request.auto_generate)
    if row is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return compat.ok(compat.dify_conversation_item(row))


@router.get("/api/transfer/one/chat-messages/messages")
def cloud_messages(
    conversation_id: str = "",
    user: str = "",
    limit: int = 20,
    api_key_header: str | None = Header(default=None, alias="Api-Key"),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_app(_headers(api_key_header, authorization, require_token=True))
    rows = services.list_messages(conversation_id, limit=limit)
    total = services.count_messages(conversation_id)
    items = []
    for row in rows:
        item = compat.dify_message_item(row)
        item["conversation_id"] = conversation_id
        items.append(item)
    return compat.records(items, total, size=limit)


@router.post("/api/transfer/one/chat-messages/feedback")
def cloud_feedback(
    request: FeedbackRequest,
    message_id: str = "",
    api_key_header: str | None = Header(default=None, alias="Api-Key"),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_app(_headers(api_key_header, authorization, require_token=True))
    row = services.set_feedback(message_id, request.rating, request.user)
    if row is None:
        raise HTTPException(status_code=404, detail="消息不存在")
    return compat.ok({"message_id": message_id, "feedback": row.feedback})


@router.get("/api/transfer/one/chat-messages/suggested")
def cloud_suggested(
    message_id: str = "",
    api_key_header: str | None = Header(default=None, alias="Api-Key"),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    app_record = _require_app(_headers(api_key_header, authorization, require_token=True))
    return compat.ok({"data": app_record.suggested_questions or []})


@router.post("/api/transfer/one/chat-messages/stop")
def cloud_stop(task_id: str = "") -> dict[str, Any]:
    return compat.ok({"result": "success", "task_id": task_id})


# --------------------------------------------------------------------------- 云智 open/dify

@router.post("/api/open/dify/difyApp")
def cloud_app_list(tenant_code: str = "") -> dict[str, Any]:
    rows = services.list_apps(tenant_code)
    return compat.records(
        [
            {
                "id": row.app_id,
                "thirdId": row.app_id,
                "appId": row.app_id,
                "apiKey": row.api_key,
                "appName": row.app_name,
                "appType": row.app_type,
                "icon": row.icon,
                "tenantCode": row.tenant_code,
            }
            for row in rows
        ],
        len(rows),
        size=len(rows) or 1,
    )


@router.post("/api/open/dify/getDifyAppInfo")
def cloud_app_info(request: DirectQueryRequest) -> dict[str, Any]:
    app_record = _app_by_identifier(request.app_identifier)
    return compat.ok(
        {
            "appId": app_record.app_id,
            "apiKey": app_record.api_key,
            "appName": app_record.app_name,
            "appType": app_record.app_type,
            "icon": app_record.icon,
            "opening_statement": app_record.opening_statement,
            "suggested_questions": app_record.suggested_questions or [],
        }
    )


@router.post("/api/open/dify/listConversationDirect")
def cloud_list_conversation_direct(request: DirectQueryRequest) -> dict[str, Any]:
    app_record = _app_by_identifier(request.app_identifier)
    rows = services.list_conversations(app_record.uuid, request.user_identifier)
    total = services.count_conversations(app_record.uuid, request.user_identifier)
    page_rows = _paginate(rows, request.page, request.page_size)
    items = [
        {
            "id": row.conversation_id,
            "thirdId": row.conversation_id,
            "conversationId": row.conversation_id,
            "name": row.name,
            "userName": row.user_name,
            "appId": app_record.app_id,
            "createdAt": row.created_at.isoformat() if row.created_at else "",
            "updatedAt": row.updated_at.isoformat() if row.updated_at else "",
        }
        for row in page_rows
    ]
    return compat.records(items, total, request.page, request.page_size)


@router.post("/api/open/dify/listConversationMessageDirect")
def cloud_list_message_direct(request: DirectQueryRequest) -> dict[str, Any]:
    conversation = services.get_conversation(request.conversation_identifier)
    if conversation is None:
        return compat.records([], 0, request.page, request.page_size)
    rows = services.list_messages(conversation.conversation_id)
    total = len(rows)
    items = [
        {
            "id": row.message_id,
            "thirdId": row.message_id,
            "conversationId": conversation.conversation_id,
            "query": row.query,
            "answer": row.answer,
            "role": row.role,
            "tokens": row.tokens,
            "createdAt": row.created_at.isoformat() if row.created_at else "",
        }
        for row in _paginate(rows, request.page, request.page_size)
    ]
    return compat.records(items, total, request.page, request.page_size)


@router.post("/api/open/dify/listConversationMessageFeedbacksDirect")
def cloud_list_feedback_direct(request: DirectQueryRequest) -> dict[str, Any]:
    conversation = services.get_conversation(request.conversation_identifier)
    if conversation is None:
        return compat.records([], 0, request.page, request.page_size)
    feedbacks = [row for row in services.list_messages(conversation.conversation_id) if row.feedback]
    items = [
        {
            "id": row.message_id,
            "thirdId": row.message_id,
            "messageId": row.message_id,
            "feedback": row.feedback,
        }
        for row in _paginate(feedbacks, request.page, request.page_size)
    ]
    return compat.records(items, len(feedbacks), request.page, request.page_size)


@router.post("/api/open/dify/listDifyEndUser")
def cloud_list_end_user(request: DirectQueryRequest) -> dict[str, Any]:
    app_record = _app_by_identifier(request.app_identifier)
    names = {row.user_name for row in services.list_conversations(app_record.uuid) if row.user_name}
    items = [{"id": name, "thirdId": name, "userName": name} for name in sorted(names)]
    return compat.records(_paginate(items, request.page, request.page_size), len(items), request.page, request.page_size)


@router.post("/api/open/dify/runWorkflow")
async def cloud_run_workflow(
    request: dict[str, Any],
    ctx: EngineContext = Depends(get_engine_context),
) -> dict[str, Any]:
    app_record = _app_by_identifier(request.get("appId") or request.get("app_id") or "")
    graph_def = services.get_published_graph(app_record.uuid)
    if graph_def is None:
        return compat.workflow_result({}, status="failed", error="应用未发布图定义")
    inputs = request.get("inputs") or {}
    state = await run_graph(graph_def, inputs, ctx)
    answer = state.get("answer", "")
    llm_name = inputs.get("llm_name", "")
    outputs = {
        "status": "success",
        "answer": answer,
        "llm_name": llm_name,
        "resolved_model": llm_name or "cloud_gateway",
        "error_code": "",
        "error_message": "",
        **{k: v for k, v in state.get("variables", {}).items() if not k.startswith("_")},
        "answer_text": answer,
    }
    return compat.workflow_result(outputs)


@router.get("/api/open/dify/parameters")
def cloud_parameters(
    app_id: str = "",
    api_key_header: str | None = Header(default=None, alias="Api-Key"),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    api_key = _headers(api_key_header, authorization)
    app_record = services.get_app_by_app_id(app_id) if app_id else services.get_app_by_key(api_key)
    if app_record is None:
        raise HTTPException(status_code=404, detail="应用不存在")
    return compat.cloud_parameters(app_record.opening_statement, app_record.suggested_questions or [])


# --------------------------------------------------------------------------- 原始 Dify /v1

@router.post("/v1/messages/{message_id}/feedbacks")
def dify_feedback(
    message_id: str,
    request: FeedbackRequest,
    api_key_header: str | None = Header(default=None, alias="Api-Key"),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_app(_headers(api_key_header, authorization))
    row = services.set_feedback(message_id, request.rating, request.user)
    if row is None:
        raise HTTPException(status_code=404, detail="消息不存在")
    return {"result": "success"}


@router.get("/v1/messages/{message_id}/suggested")
def dify_suggested(
    message_id: str,
    user: str = "",
    api_key_header: str | None = Header(default=None, alias="Api-Key"),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    app_record = _require_app(_headers(api_key_header, authorization))
    return {"result": "success", "data": app_record.suggested_questions or []}


@router.post("/v1/conversations/{conversation_id}/name")
def dify_rename(
    conversation_id: str,
    request: RenameRequest,
    api_key_header: str | None = Header(default=None, alias="Api-Key"),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_app(_headers(api_key_header, authorization))
    row = services.rename_conversation(conversation_id, request.name, request.auto_generate)
    if row is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return compat.dify_conversation_item(row)


@router.get("/v1/conversations")
def dify_conversations(
    user: str = "",
    last_id: str = "",
    limit: int = 20,
    api_key_header: str | None = Header(default=None, alias="Api-Key"),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    app_record = _require_app(_headers(api_key_header, authorization))
    rows = services.list_conversations(app_record.uuid, user, limit=limit + 1)
    has_more = len(rows) > limit
    items = [compat.dify_conversation_item(row) for row in rows[:limit]]
    if last_id:
        items = [item for item in items if item["id"] != last_id]
    return compat.dify_list(items, has_more, limit)


@router.get("/v1/messages")
def dify_messages(
    conversation_id: str = "",
    user: str = "",
    first_id: str = "",
    limit: int = 20,
    api_key_header: str | None = Header(default=None, alias="Api-Key"),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_app(_headers(api_key_header, authorization))
    rows = services.list_messages(conversation_id, limit=limit + 1, first_id=first_id)
    has_more = len(rows) > limit
    items = []
    for row in rows[:limit]:
        item = compat.dify_message_item(row)
        item["conversation_id"] = conversation_id
        items.append(item)
    return compat.dify_list(items, has_more, limit)


@router.get("/v1/parameters")
def dify_parameters(
    api_key_header: str | None = Header(default=None, alias="Api-Key"),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    app_record = _require_app(_headers(api_key_header, authorization))
    return {
        "opening_statement": app_record.opening_statement,
        "suggested_questions": app_record.suggested_questions or [],
        "suggested_questions_after_answer": {"enabled": False},
        "speech_to_text": {"enabled": False},
        "retriever_resource": {"enabled": True},
        "user_input_form": [],
        "file_upload": {"image": {"enabled": False}, "enabled": False},
        "system_parameters": {"audio_file_size_limit": 50, "file_size_limit": 15, "image_file_size_limit": 10},
    }


@router.post("/v1/workflows/run")
async def dify_workflow_run(
    request: WorkflowRunRequest,
    ctx: EngineContext = Depends(get_engine_context),
    api_key_header: str | None = Header(default=None, alias="Api-Key"),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    app_record = _require_app(_headers(api_key_header, authorization))
    graph_def = services.get_published_graph(app_record.uuid)
    if graph_def is None:
        raise HTTPException(status_code=400, detail="应用未发布图定义")
    state = await run_graph(graph_def, request.inputs, ctx)
    run_id = uuid.uuid4().hex
    return {
        "workflow_run_id": run_id,
        "task_id": run_id,
        "data": {
            "id": run_id,
            "workflow_id": app_record.uuid,
            "status": "succeeded",
            "outputs": {"answer": state.get("answer", ""), **state.get("variables", {})},
            "error": None,
            "elapsed_time": 0.0,
            "total_tokens": 0,
            "created_at": 0,
            "finished_at": 0,
        },
    }


@router.post("/v1/files/upload")
async def dify_file_upload(
    file: UploadFile,
    user: str = "",
    api_key_header: str | None = Header(default=None, alias="Api-Key"),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_app(_headers(api_key_header, authorization))
    content = await file.read()
    return {
        "id": uuid.uuid4().hex,
        "name": file.filename or "",
        "size": len(content),
        "extension": (file.filename or "").rsplit(".", 1)[-1] if file.filename else "",
        "mime_type": file.content_type or "application/octet-stream",
        "created_by": user,
        "created_at": 0,
    }
