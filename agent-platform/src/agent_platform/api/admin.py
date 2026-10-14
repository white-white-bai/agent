"""中台管理端 API：应用注册表 / 图草稿-发布-回滚 / 护栏配置 / MCP Server / 知识库文档。"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from agent_platform.api import services
from agent_platform.api.deps import get_current_admin, require_admin, require_permission
from agent_platform.api.schemas import (
    AppCreateRequest,
    AppUpdateRequest,
    DocumentCreateRequest,
    GraphDraftRequest,
    GraphImportRequest,
    GraphPublishRequest,
    GraphRollbackRequest,
    McpServerCreateRequest,
    SensitiveWordCreateRequest,
)
from agent_platform.core.accounts import AdminPrincipal
from agent_platform.core.config import get_settings
from agent_platform.importer import DifyImportError, convert, parse_dsl
from agent_platform.knowledge.embeddings import Embedder
from agent_platform.knowledge.vector_store import add_document, delete_document

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _app_dict(row: Any) -> dict[str, Any]:
    return {
        "uuid": row.uuid,
        "tenant_code": row.tenant_code,
        "app_id": row.app_id,
        "api_key": row.api_key,
        "app_name": row.app_name,
        "app_type": row.app_type,
        "icon": row.icon,
        "opening_statement": row.opening_statement,
        "suggested_questions": row.suggested_questions or [],
        "app_info": row.app_info or {},
        "is_deleted": row.is_deleted,
    }


def _version_dict(row: Any) -> dict[str, Any]:
    return {
        "uuid": row.uuid,
        "version": row.version,
        "note": row.note,
        "created_by": row.created_by,
        "definition": row.definition,
    }


# --------------------------------------------------------------------------- 应用注册表

@router.get("/apps", dependencies=[Depends(require_permission("app:read"))])
def list_apps(tenant_code: str = "", principal: AdminPrincipal = Depends(get_current_admin)) -> dict[str, Any]:
    return {"data": [_app_dict(row) for row in services.list_apps(principal.scope_tenant(tenant_code))]}


@router.post("/apps", dependencies=[Depends(require_permission("app:write"))])
def create_app(request: AppCreateRequest, principal: AdminPrincipal = Depends(get_current_admin)) -> dict[str, Any]:
    settings = get_settings()
    tenant_code = principal.scope_tenant(request.tenant_code or settings.default_tenant)
    app_id = request.app_id or uuid.uuid4().hex
    api_key = request.api_key or uuid.uuid4().hex
    row = services.create_app(
        tenant_code=tenant_code,
        app_id=app_id,
        api_key=api_key,
        app_name=request.app_name,
        app_type=request.app_type,
        icon=request.icon,
        opening_statement=request.opening_statement,
        suggested_questions=request.suggested_questions,
        app_info=request.app_info,
    )
    return {"data": _app_dict(row)}


@router.get("/apps/{app_uuid}", dependencies=[Depends(require_permission("app:read"))])
def get_app(app_uuid: str) -> dict[str, Any]:
    row = services.get_app_by_uuid(app_uuid)
    if row is None:
        raise HTTPException(status_code=404, detail="应用不存在")
    return {"data": _app_dict(row)}


@router.put("/apps/{app_uuid}", dependencies=[Depends(require_permission("app:write"))])
def update_app(app_uuid: str, request: AppUpdateRequest) -> dict[str, Any]:
    row = services.update_app(app_uuid, **request.model_dump(exclude_unset=True))
    if row is None:
        raise HTTPException(status_code=404, detail="应用不存在")
    return {"data": _app_dict(row)}


@router.delete("/apps/{app_uuid}", dependencies=[Depends(require_permission("app:write"))])
def delete_app(app_uuid: str) -> dict[str, Any]:
    if not services.delete_app(app_uuid):
        raise HTTPException(status_code=404, detail="应用不存在")
    return {"data": {"uuid": app_uuid, "is_deleted": 1}}


# --------------------------------------------------------------------------- 图草稿 / 发布 / 回滚

@router.get("/apps/{app_uuid}/graph", dependencies=[Depends(require_permission("graph:read"))])
def get_graph(app_uuid: str) -> dict[str, Any]:
    definition = services.get_draft(app_uuid)
    graph = services.get_graph_by_app_uuid(app_uuid)
    return {
        "data": {
            "app_uuid": app_uuid,
            "status": getattr(graph, "status", "draft"),
            "definition": definition or {},
        }
    }


@router.put("/apps/{app_uuid}/graph/draft", dependencies=[Depends(require_permission("graph:write"))])
def save_graph_draft(app_uuid: str, request: GraphDraftRequest) -> dict[str, Any]:
    if services.get_app_by_uuid(app_uuid) is None:
        raise HTTPException(status_code=404, detail="应用不存在")
    graph = services.save_draft(app_uuid, request.definition)
    return {"data": {"app_uuid": app_uuid, "status": graph.status, "definition": graph.draft}}


@router.post("/apps/{app_uuid}/graph/publish", dependencies=[Depends(require_permission("graph:write"))])
def publish_graph(app_uuid: str, request: GraphPublishRequest) -> dict[str, Any]:
    try:
        version = services.publish_draft(
            app_uuid, note=request.note, created_by=request.created_by, definition=request.definition
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"图定义非法: {exc}") from exc
    if version is None:
        raise HTTPException(status_code=400, detail="草稿为空，无法发布")
    return {"data": _version_dict(version)}


@router.get("/apps/{app_uuid}/graph/versions", dependencies=[Depends(require_permission("graph:read"))])
def list_graph_versions(app_uuid: str) -> dict[str, Any]:
    return {"data": [_version_dict(row) for row in services.list_versions(app_uuid)]}


@router.post("/apps/{app_uuid}/graph/rollback", dependencies=[Depends(require_permission("graph:write"))])
def rollback_graph(app_uuid: str, request: GraphRollbackRequest) -> dict[str, Any]:
    version = services.rollback(app_uuid, request.version)
    if version is None:
        raise HTTPException(status_code=404, detail="版本不存在")
    return {"data": _version_dict(version)}


@router.post("/apps/{app_uuid}/graph/import", dependencies=[Depends(require_permission("graph:write"))])
def import_graph(app_uuid: str, request: GraphImportRequest) -> dict[str, Any]:
    app_row = services.get_app_by_uuid(app_uuid)
    if app_row is None:
        raise HTTPException(status_code=404, detail="应用不存在")
    try:
        dsl = request.dsl if request.dsl is not None else parse_dsl(request.content)
        result = convert(
            dsl,
            app_id=app_row.app_id,
            name=request.name or app_row.app_name,
            llm_provider=request.llm_provider,
            retriever=request.retriever,
        )
    except DifyImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if request.save:
        services.save_draft(app_uuid, result.definition)
    return {
        "data": {
            "app_uuid": app_uuid,
            "saved": request.save,
            "stats": result.stats,
            "warnings": result.warnings,
            "definition": result.definition,
        }
    }


# --------------------------------------------------------------------------- 护栏：敏感词

@router.get("/sensitive-words", dependencies=[Depends(require_permission("guard:read"))])
def list_sensitive_words(tenant_code: str = "", principal: AdminPrincipal = Depends(get_current_admin)) -> dict[str, Any]:
    return {
        "data": [
            {"id": row.id, "tenant_code": row.tenant_code, "word": row.word}
            for row in services.list_sensitive_words(principal.scope_tenant(tenant_code))
        ]
    }


@router.post("/sensitive-words", dependencies=[Depends(require_permission("guard:write"))])
def create_sensitive_word(
    request: SensitiveWordCreateRequest, principal: AdminPrincipal = Depends(get_current_admin)
) -> dict[str, Any]:
    tenant_code = principal.scope_tenant(request.tenant_code or get_settings().default_tenant)
    row = services.add_sensitive_word(tenant_code, request.word)
    return {"data": {"id": row.id, "tenant_code": row.tenant_code, "word": row.word}}


@router.delete("/sensitive-words/{word_id}", dependencies=[Depends(require_permission("guard:write"))])
def delete_sensitive_word(word_id: int) -> dict[str, Any]:
    if not services.delete_sensitive_word(word_id):
        raise HTTPException(status_code=404, detail="敏感词不存在")
    return {"data": {"id": word_id}}


# --------------------------------------------------------------------------- MCP Server 注册

@router.get("/mcp-servers", dependencies=[Depends(require_permission("mcp:read"))])
def list_mcp_servers(
    tenant_code: str = "", principal: AdminPrincipal = Depends(get_current_admin)
) -> dict[str, Any]:
    return {
        "data": [
            {
                "uuid": row.uuid,
                "tenant_code": row.tenant_code,
                "name": row.name,
                "kind": row.kind,
                "url": row.url,
                "headers": row.headers or {},
            }
            for row in services.list_mcp_servers(principal.scope_tenant(tenant_code))
        ]
    }


@router.post("/mcp-servers", dependencies=[Depends(require_permission("mcp:write"))])
def create_mcp_server(
    request: McpServerCreateRequest, principal: AdminPrincipal = Depends(get_current_admin)
) -> dict[str, Any]:
    row = services.create_mcp_server(
        tenant_code=principal.scope_tenant(request.tenant_code or get_settings().default_tenant),
        name=request.name,
        url=request.url,
        kind=request.kind,
        headers=request.headers,
    )
    return {"data": {"uuid": row.uuid, "name": row.name, "kind": row.kind, "url": row.url}}


@router.delete("/mcp-servers/{server_uuid}", dependencies=[Depends(require_permission("mcp:write"))])
def delete_mcp_server(server_uuid: str) -> dict[str, Any]:
    if not services.delete_mcp_server(server_uuid):
        raise HTTPException(status_code=404, detail="MCP Server 不存在")
    return {"data": {"uuid": server_uuid, "is_deleted": 1}}


# --------------------------------------------------------------------------- 知识库文档

@router.get("/documents", dependencies=[Depends(require_permission("knowledge:read"))])
def list_documents(
    tenant_code: str = "", dataset_id: str = "", principal: AdminPrincipal = Depends(get_current_admin)
) -> dict[str, Any]:
    from agent_platform.knowledge.vector_store import list_documents as _list

    rows = _list(principal.scope_tenant(tenant_code) or get_settings().default_tenant, dataset_id)
    return {
        "data": [
            {
                "uuid": row.uuid,
                "tenant_code": row.tenant_code,
                "dataset_id": row.dataset_id,
                "title": row.title,
                "content": row.content,
                "metadata": row.doc_metadata or {},
            }
            for row in rows
        ]
    }


@router.post("/documents", dependencies=[Depends(require_permission("knowledge:write"))])
async def create_document(
    request: DocumentCreateRequest, principal: AdminPrincipal = Depends(get_current_admin)
) -> dict[str, Any]:
    settings = get_settings()
    embedder = Embedder(settings)
    embedding = await embedder.encode(request.content)
    row = add_document(
        tenant_code=principal.scope_tenant(request.tenant_code or settings.default_tenant),
        dataset_id=request.dataset_id,
        title=request.title,
        content=request.content,
        embedding=embedding,
        metadata=request.metadata,
    )
    return {"data": {"uuid": row.uuid, "title": row.title, "dataset_id": row.dataset_id}}


@router.delete("/documents/{document_uuid}", dependencies=[Depends(require_permission("knowledge:write"))])
def delete_document_endpoint(document_uuid: str) -> dict[str, Any]:
    if not delete_document(document_uuid):
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"data": {"uuid": document_uuid, "is_deleted": 1}}
