"""外部 HITL 审批回调：校验签名 token 后恢复图运行或 Agent 应用。

该路由不依赖管理端登录；token 绑定 kind/app/thread/interrupt，并有过期时间。
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from langgraph.types import Command
from pydantic import BaseModel, Field, ValidationError

from agent_platform.agentapp.runtime import pending_agent_interrupt, resume_agent
from agent_platform.api import services
from agent_platform.api.deps import get_checkpointer, get_engine_context
from agent_platform.core.config import get_settings
from agent_platform.core.hitl_tokens import (
    HitlTokenError,
    approval_links,
    graph_interrupt_id,
    verify_action_token,
)
from agent_platform.core.notifications import notify_hitl
from agent_platform.engine.context import EngineContext
from agent_platform.engine.runtime import stream_graph
from agent_platform.graph.schema import GraphDef

router = APIRouter(prefix="/webhooks/hitl", tags=["hitl-webhook"])
_LOCKS: dict[str, asyncio.Lock] = {}


class HitlCallbackRequest(BaseModel):
    token: str
    edits: dict[str, Any] = Field(default_factory=dict)


def _lock(key: str) -> asyncio.Lock:
    lock = _LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _LOCKS[key] = lock
    return lock


async def _resume_graph(
    payload: dict[str, Any], decision: str, edits: dict[str, Any], ctx: EngineContext
) -> dict[str, Any]:
    thread_id = str(payload["thread_id"])
    run = services.get_run(thread_id)
    if run is None:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    if run.status != "interrupted":
        raise HTTPException(status_code=409, detail="当前运行不在等待审批状态")
    interrupt_id = str(payload["interrupt_id"])
    if graph_interrupt_id(run.interrupt_payload or {}) != interrupt_id:
        raise HTTPException(status_code=409, detail="审批已失效：中断 id 不匹配")
    if not services.claim_hitl_action(
        "graph", thread_id, interrupt_id, decision, tenant_code=run.tenant_code
    ):
        raise HTTPException(status_code=409, detail="审批已使用")
    if not services.claim_run(thread_id, "webhook"):
        raise HTTPException(status_code=409, detail="当前运行已被其他请求恢复")
    try:
        graph_def = GraphDef.model_validate(run.graph_definition or {})
    except ValidationError as exc:
        services.update_run(thread_id, status="failed", if_status=("running",))
        raise HTTPException(status_code=400, detail=f"运行图定义非法: {exc}") from exc
    ctx.tenant_code = run.tenant_code
    ctx.hitl_enabled = True
    ctx.resolve_subgraph = services.snapshot_resolver(run.subgraph_snapshot or [])
    command = Command(resume={interrupt_id: {"action": decision, **edits}})
    status = "completed"
    answer = ""
    try:
        async for item in stream_graph(
            graph_def,
            {},
            ctx,
            checkpointer=get_checkpointer(),
            thread_id=thread_id,
            resume=command,
            allow_interrupt=True,
        ):
            if item.get("type") == "interrupt":
                status = "interrupted"
                services.update_run(
                    thread_id, status=status, interrupt_payload=item, if_status=("running",)
                )
                settings = get_settings()
                await notify_hitl(
                    "graph.interrupt",
                    {
                        "thread_id": thread_id,
                        "app_uuid": payload["app_uuid"],
                        "resume_endpoint": f"/admin/runs/{thread_id}/resume",
                        "interrupt": item,
                        "approval": approval_links(
                            kind="graph",
                            app_uuid=payload["app_uuid"],
                            thread_id=thread_id,
                            interrupt_id=graph_interrupt_id(item),
                            settings=settings,
                        ),
                    },
                    settings,
                )
            elif item.get("type") == "error":
                status = "failed"
                services.update_run(
                    thread_id, status="failed", if_status=("running", "interrupted")
                )
            elif item.get("type") == "final":
                answer = str(item.get("answer") or answer)
    except Exception as exc:  # 回调接口把失败落到运行状态
        services.update_run(thread_id, status="failed", if_status=("running", "interrupted"))
        raise HTTPException(status_code=500, detail=f"恢复运行失败: {exc}") from exc
    finally:
        if status == "completed":
            services.update_run(thread_id, status="completed", if_status=("running",))
    return {"kind": "graph", "thread_id": thread_id, "status": status, "answer": answer}


async def _resume_agent_app(
    payload: dict[str, Any], decision: str, edits: dict[str, Any], ctx: EngineContext
) -> dict[str, Any]:
    app_uuid = str(payload["app_uuid"])
    thread_id = str(payload["thread_id"])
    app_row = services.get_app_by_uuid(app_uuid)
    if app_row is None:
        raise HTTPException(status_code=404, detail="应用不存在")
    agent_def = services.get_published_agent(app_uuid)
    if agent_def is None:
        raise HTTPException(status_code=404, detail="应用未发布 Agent 定义")
    ctx.tenant_code = app_row.tenant_code
    ctx.hitl_enabled = True
    checkpointer = get_checkpointer()
    pending = await pending_agent_interrupt(
        agent_def, ctx, checkpointer=checkpointer, thread_id=thread_id, tenant_code=app_row.tenant_code
    )
    if pending is None:
        raise HTTPException(status_code=409, detail="当前会话不在等待审批状态")
    if str(pending.get("interrupt_id") or "") != str(payload["interrupt_id"]):
        raise HTTPException(status_code=409, detail="审批已失效：中断 id 不匹配")
    if not services.claim_hitl_action(
        "agent", thread_id, str(payload["interrupt_id"]), decision, tenant_code=app_row.tenant_code
    ):
        raise HTTPException(status_code=409, detail="审批已使用")
    answer = ""
    status = "completed"
    async for item in resume_agent(
        agent_def,
        {"decision": decision, "edits": edits},
        ctx,
        checkpointer=checkpointer,
        thread_id=thread_id,
        tenant_code=app_row.tenant_code,
        app_uuid=app_uuid,
    ):
        if item.get("type") == "agent_interrupt":
            status = "interrupted"
            settings = get_settings()
            await notify_hitl(
                "agent.interrupt",
                {
                    "thread_id": thread_id,
                    "app_uuid": app_uuid,
                    "resume_endpoint": f"/admin/apps/{app_uuid}/agent/resume",
                    "interrupt": item,
                    "approval": approval_links(
                        kind="agent",
                        app_uuid=app_uuid,
                        thread_id=thread_id,
                        interrupt_id=str(item.get("interrupt_id") or ""),
                        settings=settings,
                    ),
                },
                settings,
            )
        elif item.get("type") == "final":
            answer = str(item.get("answer") or answer)
    return {"kind": "agent", "thread_id": thread_id, "status": status, "answer": answer}


@router.post("/{decision}")
async def hitl_callback(
    decision: str,
    request: HitlCallbackRequest,
    ctx: EngineContext = Depends(get_engine_context),
) -> dict[str, Any]:
    if decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="decision 只能是 approve 或 reject")
    settings = get_settings()
    try:
        payload = verify_action_token(request.token, settings.hitl_webhook_secret)
    except HitlTokenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    key = f"{payload['kind']}:{payload['thread_id']}"
    async with _lock(key):
        if payload["kind"] == "graph":
            data = await _resume_graph(payload, decision, request.edits, ctx)
        else:
            data = await _resume_agent_app(payload, decision, request.edits, ctx)
    return {"data": data}
