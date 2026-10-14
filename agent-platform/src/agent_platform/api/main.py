"""FastAPI 入口。"""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header
from fastapi.responses import StreamingResponse

from agent_platform.api import accounts, admin, compat, compat_api, services
from agent_platform.api.deps import (
    build_request_tracer,
    get_concurrency_limiter,
    get_engine_context,
    get_guard_chain,
    get_idempotency_store,
)
from agent_platform.api.schemas import ChatMessagesRequest
from agent_platform.core import accounts as accounts_core
from agent_platform.core.concurrency import ConcurrencyLimiter
from agent_platform.core.config import get_settings
from agent_platform.core.db import init_db
from agent_platform.core.guards import GuardChain
from agent_platform.core.idempotency import IdempotencyStore
from agent_platform.core.security import AuthError, resolve_api_key
from agent_platform.engine.context import EngineContext
from agent_platform.engine.runtime import stream_graph


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()
    if get_settings().admin_auth_enabled:
        accounts_core.seed()
    yield


app = FastAPI(title="agent-platform", version="0.1.0", lifespan=lifespan)
app.include_router(admin.router)
app.include_router(accounts.router)
app.include_router(compat_api.router)
app.include_router(compat_api.router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


def _resolve_api_key(api_key_header: str | None, authorization: str | None) -> str:
    try:
        return resolve_api_key(api_key_header, authorization)
    except AuthError:
        return ""


IN_FLIGHT_REPLY = "相同请求正在处理中，请稍后重试"
CONCURRENCY_REPLY = "当前请求过多，请稍后重试"


async def _replay_stream(payload: dict[str, Any]) -> AsyncIterator[str]:
    conversation_id = payload.get("conversation_id", "")
    message_id = payload.get("message_id", "")
    answer = payload.get("answer", "")
    resources = payload.get("retriever_resources") or []
    if answer:
        yield compat.sse(compat.message_event(conversation_id, message_id, answer))
    yield compat.sse(compat.message_end_event(conversation_id, message_id, answer, resources))


async def _chat_stream(
    request: ChatMessagesRequest,
    api_key: str,
    ctx: EngineContext,
    guards: GuardChain,
    idempotency: IdempotencyStore | None = None,
    limiter: ConcurrencyLimiter | None = None,
    idempotency_header: str = "",
) -> AsyncIterator[str]:
    app_record = services.get_app_by_key(api_key)
    if app_record is None:
        yield compat.default_reply()
        return

    graph_def = services.get_published_graph(app_record.uuid)
    if graph_def is None:
        yield compat.default_reply()
        return

    ctx.tenant_code = app_record.tenant_code

    idem_key = ""
    slot_held = False
    stored = False
    try:
        if idempotency is not None:
            idem_key = idempotency.key_for(
                app_uuid=app_record.uuid,
                user=request.user,
                conversation_id=request.conversation_id,
                query=request.query,
                explicit=request.idempotency_key or idempotency_header,
            )
            outcome = idempotency.acquire(idem_key)
            if outcome.replay is not None:
                async for chunk in _replay_stream(outcome.replay):
                    yield chunk
                return
            if outcome.in_flight:
                yield compat.sse(compat.error_event(IN_FLIGHT_REPLY))
                return

        if limiter is not None:
            if not await limiter.acquire_with_wait(app_record.uuid):
                yield compat.sse(compat.error_event(CONCURRENCY_REPLY))
                return
            slot_held = limiter.enabled

        conversation = services.get_or_create_conversation(app_record, request.user, request.conversation_id)
        history = services.load_history(conversation, get_settings().history_window)
        services.save_message(conversation, "user", query=request.query)
        message_id = uuid.uuid4().hex

        decision = guards.pre_check(
            tenant_code=app_record.tenant_code,
            app_uuid=app_record.uuid,
            user=request.user,
            query=request.query,
            conversation=conversation,
        )
        if not decision.allowed:
            services.save_message(
                conversation, "assistant", query=request.query, answer=decision.reply, message_id=message_id
            )
            yield compat.sse(compat.message_end_event(conversation.conversation_id, message_id, decision.reply))
            return

        tracer = build_request_tracer(request.user, {"app_id": app_record.app_id})
        ctx.tracer = tracer
        inputs = {**request.inputs, "query": request.query}
        if history:
            inputs["history"] = history
        answer = ""
        resources: list[dict] = []
        try:
            async for item in stream_graph(graph_def, inputs, ctx, thread_id=conversation.conversation_id):
                if item["type"] == "token":
                    answer += item["content"]
                    yield compat.sse(
                        compat.message_event(conversation.conversation_id, message_id, item["content"])
                    )
                elif item["type"] == "final":
                    answer = item.get("answer") or answer
                    resources = (item.get("state", {}).get("variables", {}) or {}).get("chunks", []) or []
        except Exception as exc:  # noqa: BLE001
            yield compat.sse(compat.error_event(str(exc)))
            return
        finally:
            tracer.flush()

        trimmed = compat.trim_retriever_resources(resources)
        services.save_message(
            conversation,
            "assistant",
            query=request.query,
            answer=answer,
            metadata={"retriever_resources": trimmed},
            message_id=message_id,
        )
        if idempotency is not None and idem_key:
            idempotency.complete(
                idem_key,
                {
                    "conversation_id": conversation.conversation_id,
                    "message_id": message_id,
                    "answer": answer,
                    "retriever_resources": trimmed,
                },
            )
            stored = True
        yield compat.sse(compat.message_end_event(conversation.conversation_id, message_id, answer, resources))
    finally:
        if slot_held:
            limiter.release(app_record.uuid)
        if idem_key and not stored:
            idempotency.release(idem_key)


@app.post("/v1/chat-messages")
@app.post("/api/transfer/one/chat-messages")
async def chat_messages(
    request: ChatMessagesRequest,
    ctx: EngineContext = Depends(get_engine_context),
    guards: GuardChain = Depends(get_guard_chain),
    idempotency: IdempotencyStore = Depends(get_idempotency_store),
    limiter: ConcurrencyLimiter = Depends(get_concurrency_limiter),
    api_key_header: str | None = Header(default=None, alias="Api-Key"),
    authorization: str | None = Header(default=None),
    idempotency_key: str = Header(default="", alias="Idempotency-Key"),
) -> StreamingResponse:
    api_key = _resolve_api_key(api_key_header, authorization)
    return StreamingResponse(
        _chat_stream(request, api_key, ctx, guards, idempotency, limiter, idempotency_key),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
