"""FastAPI 入口。"""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header
from fastapi.responses import StreamingResponse

from agent_platform.api import compat, services
from agent_platform.api.schemas import ChatMessagesRequest
from agent_platform.core.config import get_settings
from agent_platform.core.db import init_db
from agent_platform.engine.context import EngineContext
from agent_platform.engine.runtime import stream_graph
from agent_platform.knowledge.retrievers import build_retriever
from agent_platform.models.factory import build_llm_invoker
from agent_platform.tools.mcp_bridge import build_tool_invoker


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


def get_engine_context() -> EngineContext:
    settings = get_settings()
    return EngineContext(
        llm=build_llm_invoker(settings),
        retriever=build_retriever(settings),
        tools=build_tool_invoker(settings),
    )


app = FastAPI(title="agent-platform", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


def _resolve_api_key(api_key_header: str | None, authorization: str | None) -> str:
    if api_key_header:
        return api_key_header
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


async def _chat_stream(request: ChatMessagesRequest, api_key: str, ctx: EngineContext) -> AsyncIterator[str]:
    app_record = services.get_app_by_key(api_key)
    if app_record is None:
        yield compat.default_reply()
        return

    graph_def = services.get_published_graph(app_record.uuid)
    if graph_def is None:
        yield compat.default_reply()
        return

    conversation = services.get_or_create_conversation(app_record, request.user, request.conversation_id)
    services.save_message(conversation, "user", query=request.query)
    message_id = uuid.uuid4().hex

    inputs = {**request.inputs, "query": request.query}
    answer = ""
    try:
        async for item in stream_graph(graph_def, inputs, ctx, thread_id=conversation.conversation_id):
            if item["type"] == "token":
                answer += item["content"]
                yield compat.sse(compat.message_event(conversation.conversation_id, message_id, item["content"]))
            elif item["type"] == "final":
                answer = item.get("answer") or answer
    except Exception as exc:  # noqa: BLE001
        yield compat.sse(compat.error_event(str(exc)))
        return

    services.save_message(conversation, "assistant", query=request.query, answer=answer)
    yield compat.sse(compat.message_end_event(conversation.conversation_id, message_id, answer))


@app.post("/v1/chat-messages")
@app.post("/api/transfer/one/chat-messages")
async def chat_messages(
    request: ChatMessagesRequest,
    ctx: EngineContext = Depends(get_engine_context),
    api_key_header: str | None = Header(default=None, alias="Api-Key"),
    authorization: str | None = Header(default=None),
) -> StreamingResponse:
    api_key = _resolve_api_key(api_key_header, authorization)
    return StreamingResponse(
        _chat_stream(request, api_key, ctx),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
