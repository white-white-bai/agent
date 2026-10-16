"""中台管理端 API：应用注册表 / 图草稿-发布-回滚 / 护栏配置 / MCP Server / 知识库文档。"""
from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from pathlib import PurePath
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from agent_platform.api import graph_templates, services
from agent_platform.api.deps import (
    build_request_tracer,
    get_current_admin,
    get_engine_context,
    require_admin,
    require_permission,
)
from agent_platform.api.schemas import (
    AgentUpsertRequest,
    AppCreateRequest,
    AppUpdateRequest,
    DatasetUpsertRequest,
    DocumentTextRequest,
    GraphDraftRequest,
    GraphImportRequest,
    GraphPublishRequest,
    GraphRollbackRequest,
    McpServerCreateRequest,
    PromptUpsertRequest,
    RetrieveRequest,
    RunGraphRequest,
    RunNodeRequest,
    SegmentUpdateRequest,
    SensitiveWordCreateRequest,
    ToolTestRequest,
    ToolUpsertRequest,
)
from agent_platform.api.uploads import read_document, read_upload
from agent_platform.core import metrics
from agent_platform.core.accounts import AdminPrincipal
from agent_platform.core.config import get_settings
from agent_platform.engine.context import EngineContext
from agent_platform.engine.runtime import run_node, stream_graph
from agent_platform.graph.schema import AGENT_MODES, GraphDef
from agent_platform.importer import DifyImportError, convert, parse_dsl
from agent_platform.knowledge.embeddings import Embedder
from agent_platform.tools.mcp_bridge import call_declared_tool

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])

DSL_SUFFIXES = {".yml", ".yaml", ".json"}
DOCUMENT_SUFFIXES = {
    ".txt", ".md", ".markdown", ".mdx", ".csv",
    ".html", ".htm",
    ".pdf", ".docx", ".xlsx", ".xls",
}


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
    try:
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
    except services.AppIdConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
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

@router.get("/graph/templates", dependencies=[Depends(require_permission("graph:read"))])
def list_graph_templates() -> dict[str, Any]:
    """内置图模板列表（编辑器「插入流水线模板」用）。"""
    return {"data": graph_templates.list_templates()}


@router.get("/graph/templates/{template_key}", dependencies=[Depends(require_permission("graph:read"))])
def get_graph_template(template_key: str) -> dict[str, Any]:
    template = graph_templates.get_template(template_key)
    if template is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    return {"data": template}


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


@router.post("/apps/{app_uuid}/graph/import/file", dependencies=[Depends(require_permission("graph:write"))])
async def import_graph_file(
    app_uuid: str,
    file: UploadFile,
    llm_provider: str = Form(""),
    retriever: str = Form("builtin"),
    name: str = Form(""),
    save: bool = Form(True),
) -> dict[str, Any]:
    app_row = services.get_app_by_uuid(app_uuid)
    if app_row is None:
        raise HTTPException(status_code=404, detail="应用不存在")
    content = await read_upload(file, DSL_SUFFIXES)
    try:
        result = convert(
            parse_dsl(content),
            app_id=app_row.app_id,
            name=name or app_row.app_name,
            llm_provider=llm_provider,
            retriever=retriever,
        )
    except DifyImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if save:
        services.save_draft(app_uuid, result.definition)
    return {
        "data": {
            "app_uuid": app_uuid,
            "saved": save,
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


# --------------------------------------------------------------------------- 知识库

def _tenant(principal: AdminPrincipal, requested: str = "") -> str:
    return principal.scope_tenant(requested) or get_settings().default_tenant


def _iso(value: Any) -> str:
    return value.isoformat() if value is not None else ""


def _dataset_dict(row: Any, document_count: int = 0) -> dict[str, Any]:
    return {
        "uuid": row.uuid,
        "tenant_code": row.tenant_code,
        "name": row.name,
        "description": row.description,
        "embedding_model": row.embedding_model,
        "retrieval": row.retrieval or {},
        "document_count": document_count,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _document_dict(row: Any) -> dict[str, Any]:
    return {
        "uuid": row.uuid,
        "tenant_code": row.tenant_code,
        "dataset_id": row.dataset_id,
        "name": row.name,
        "file_type": row.file_type,
        "file_size": row.file_size,
        "char_count": row.char_count,
        "chunk_count": row.chunk_count,
        "status": row.status,
        "error": row.error,
        "metadata": row.doc_metadata or {},
        "created_by": row.created_by,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _segment_dict(row: Any) -> dict[str, Any]:
    return {
        "uuid": row.uuid,
        "document_uuid": row.document_uuid,
        "dataset_id": row.dataset_id,
        "position": row.position,
        "content": row.content,
        "enabled": row.enabled,
        "hit_count": row.hit_count,
        "created_at": _iso(row.created_at),
    }


def _get_dataset_or_404(dataset_uuid: str, principal: AdminPrincipal) -> Any:
    from agent_platform.knowledge import datasets as datasets_mod

    dataset = datasets_mod.get_dataset(dataset_uuid, principal.tenant_code)
    if dataset is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return dataset


@router.get("/datasets", dependencies=[Depends(require_permission("knowledge:read"))])
def list_datasets(tenant_code: str = "", principal: AdminPrincipal = Depends(get_current_admin)) -> dict[str, Any]:
    from agent_platform.knowledge import datasets as datasets_mod

    tenant = _tenant(principal, tenant_code)
    rows = datasets_mod.list_datasets(tenant)
    counts = datasets_mod.document_counts(tenant, [row.uuid for row in rows])
    return {"data": [_dataset_dict(row, counts.get(row.uuid, 0)) for row in rows]}


@router.post("/datasets", dependencies=[Depends(require_permission("knowledge:write"))])
def create_dataset(request: DatasetUpsertRequest, principal: AdminPrincipal = Depends(get_current_admin)) -> dict[str, Any]:
    from agent_platform.knowledge import datasets as datasets_mod

    if not request.name.strip():
        raise HTTPException(status_code=400, detail="知识库名称不能为空")
    row = datasets_mod.create_dataset(
        tenant_code=_tenant(principal, request.tenant_code),
        name=request.name.strip(),
        description=request.description,
        retrieval=request.retrieval,
        embedding_model=request.embedding_model,
    )
    return {"data": _dataset_dict(row)}


@router.get("/datasets/{dataset_uuid}", dependencies=[Depends(require_permission("knowledge:read"))])
def get_dataset(dataset_uuid: str, principal: AdminPrincipal = Depends(get_current_admin)) -> dict[str, Any]:
    from agent_platform.knowledge import datasets as datasets_mod

    dataset = _get_dataset_or_404(dataset_uuid, principal)
    counts = datasets_mod.document_counts(dataset.tenant_code, [dataset_uuid])
    return {"data": _dataset_dict(dataset, counts.get(dataset_uuid, 0))}


@router.put("/datasets/{dataset_uuid}", dependencies=[Depends(require_permission("knowledge:write"))])
def update_dataset(
    dataset_uuid: str, request: DatasetUpsertRequest, principal: AdminPrincipal = Depends(get_current_admin)
) -> dict[str, Any]:
    from agent_platform.knowledge import datasets as datasets_mod

    row = datasets_mod.update_dataset(
        dataset_uuid,
        name=request.name or None,
        description=request.description,
        retrieval=request.retrieval if request.retrieval else None,
        embedding_model=request.embedding_model or None,
        tenant_code=principal.tenant_code,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return {"data": _dataset_dict(row)}


@router.delete("/datasets/{dataset_uuid}", dependencies=[Depends(require_permission("knowledge:write"))])
def delete_dataset(dataset_uuid: str, principal: AdminPrincipal = Depends(get_current_admin)) -> dict[str, Any]:
    from agent_platform.knowledge import datasets as datasets_mod

    if not datasets_mod.delete_dataset(dataset_uuid, principal.tenant_code):
        raise HTTPException(status_code=404, detail="知识库不存在")
    return {"data": {"uuid": dataset_uuid, "is_deleted": 1}}


@router.get("/datasets/{dataset_uuid}/documents", dependencies=[Depends(require_permission("knowledge:read"))])
def list_dataset_documents(
    dataset_uuid: str,
    page: int = 1,
    size: int = 20,
    principal: AdminPrincipal = Depends(get_current_admin),
) -> dict[str, Any]:
    from agent_platform.knowledge import documents as documents_mod

    dataset = _get_dataset_or_404(dataset_uuid, principal)
    rows, total = documents_mod.list_documents(dataset.tenant_code, dataset_uuid, page, size)
    return {"data": {"items": [_document_dict(row) for row in rows], "total": total, "page": page, "size": size}}


@router.post("/datasets/{dataset_uuid}/documents", dependencies=[Depends(require_permission("knowledge:write"))])
async def create_dataset_document(
    dataset_uuid: str, request: DocumentTextRequest, principal: AdminPrincipal = Depends(get_current_admin)
) -> dict[str, Any]:
    from agent_platform.knowledge import documents as documents_mod
    from agent_platform.knowledge.ingest import ingest_document

    if not request.content.strip():
        raise HTTPException(status_code=400, detail="文档内容为空")
    dataset = _get_dataset_or_404(dataset_uuid, principal)
    document = documents_mod.create_document(
        tenant_code=dataset.tenant_code,
        dataset_id=dataset_uuid,
        name=request.name.strip() or "未命名文档",
        content=request.content,
        file_type="text",
        file_size=len(request.content.encode("utf-8")),
        status="pending",
        metadata=request.metadata,
        created_by=principal.username,
    )
    await ingest_document(document.uuid)
    return {"data": _document_dict(documents_mod.get_document(document.uuid))}


@router.post("/datasets/{dataset_uuid}/documents/upload", dependencies=[Depends(require_permission("knowledge:write"))])
async def upload_dataset_document(
    dataset_uuid: str,
    file: UploadFile,
    principal: AdminPrincipal = Depends(get_current_admin),
) -> dict[str, Any]:
    from agent_platform.knowledge import documents as documents_mod
    from agent_platform.knowledge.ingest import dispatch_ingest, ingest_document

    settings = get_settings()
    dataset = _get_dataset_or_404(dataset_uuid, principal)
    content = await read_document(file, DOCUMENT_SUFFIXES)
    if not content.strip():
        raise HTTPException(status_code=400, detail="文件内容为空")
    filename = file.filename or ""
    size = len(content.encode("utf-8"))
    document = documents_mod.create_document(
        tenant_code=dataset.tenant_code,
        dataset_id=dataset_uuid,
        name=PurePath(filename).stem or filename or "未命名文档",
        content=content,
        file_type=PurePath(filename).suffix.lower(),
        file_size=size,
        status="pending",
        metadata={"source": "upload", "filename": filename},
        created_by=principal.username,
    )
    threshold = settings.knowledge_async_threshold_bytes
    ingest = "sync"
    if threshold and size < threshold:
        await ingest_document(document.uuid)
    else:
        ingest = dispatch_ingest(document.uuid)
    return {"data": {**_document_dict(documents_mod.get_document(document.uuid)), "ingest": ingest}}


@router.delete("/documents/{document_uuid}", dependencies=[Depends(require_permission("knowledge:write"))])
def delete_document_endpoint(document_uuid: str, principal: AdminPrincipal = Depends(get_current_admin)) -> dict[str, Any]:
    from agent_platform.knowledge import documents as documents_mod

    if not documents_mod.delete_document(document_uuid, principal.tenant_code):
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"data": {"uuid": document_uuid, "is_deleted": 1}}


@router.post("/documents/{document_uuid}/reindex", dependencies=[Depends(require_permission("knowledge:write"))])
async def reindex_document(document_uuid: str, principal: AdminPrincipal = Depends(get_current_admin)) -> dict[str, Any]:
    from agent_platform.knowledge import documents as documents_mod
    from agent_platform.knowledge.ingest import dispatch_ingest, ingest_document

    settings = get_settings()
    document = documents_mod.get_document(document_uuid, principal.tenant_code)
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    documents_mod.update_document(document_uuid, status="pending", error="", tenant_code=principal.tenant_code)
    documents_mod.replace_segments(document_uuid, [])
    threshold = settings.knowledge_async_threshold_bytes
    size = len((document.content or "").encode("utf-8"))
    if threshold and size < threshold:
        await ingest_document(document_uuid)
        ingest = "sync"
    else:
        ingest = dispatch_ingest(document_uuid)
    row = documents_mod.get_document(document_uuid)
    return {"data": {**_document_dict(row), "ingest": ingest}}


@router.get("/documents/{document_uuid}/segments", dependencies=[Depends(require_permission("knowledge:read"))])
def list_document_segments(
    document_uuid: str,
    page: int = 1,
    size: int = 100,
    principal: AdminPrincipal = Depends(get_current_admin),
) -> dict[str, Any]:
    from agent_platform.knowledge import documents as documents_mod

    if documents_mod.get_document(document_uuid, principal.tenant_code) is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    rows, total = documents_mod.list_segments(document_uuid, principal.tenant_code, page, size)
    return {"data": {"items": [_segment_dict(row) for row in rows], "total": total, "page": page, "size": size}}


@router.put("/segments/{segment_uuid}", dependencies=[Depends(require_permission("knowledge:write"))])
async def update_segment(
    segment_uuid: str, request: SegmentUpdateRequest, principal: AdminPrincipal = Depends(get_current_admin)
) -> dict[str, Any]:
    from agent_platform.knowledge import documents as documents_mod

    embedding = None
    if request.content is not None:
        embedding = await Embedder(get_settings()).encode(request.content)
    row = documents_mod.update_segment(
        segment_uuid,
        content=request.content,
        embedding=embedding,
        enabled=request.enabled,
        tenant_code=principal.tenant_code,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="分段不存在")
    return {"data": _segment_dict(row)}


@router.delete("/segments/{segment_uuid}", dependencies=[Depends(require_permission("knowledge:write"))])
def delete_segment(segment_uuid: str, principal: AdminPrincipal = Depends(get_current_admin)) -> dict[str, Any]:
    from agent_platform.knowledge import documents as documents_mod

    if not documents_mod.delete_segment(segment_uuid, principal.tenant_code):
        raise HTTPException(status_code=404, detail="分段不存在")
    return {"data": {"uuid": segment_uuid, "is_deleted": 1}}


@router.post("/datasets/{dataset_uuid}/retrieve", dependencies=[Depends(require_permission("knowledge:read"))])
async def retrieve_dataset(
    dataset_uuid: str, request: RetrieveRequest, principal: AdminPrincipal = Depends(get_current_admin)
) -> dict[str, Any]:
    from agent_platform.knowledge.vector_store import build_builtin_searcher

    dataset = _get_dataset_or_404(dataset_uuid, principal)
    config = dataset.retrieval or {}
    top_k = request.top_k or int(config.get("top_k") or 5)
    threshold = request.score_threshold if request.score_threshold is not None else config.get("score_threshold")
    hits = await build_builtin_searcher(get_settings())(
        tenant_code=dataset.tenant_code,
        query=request.query,
        dataset_ids=[dataset_uuid],
        top_k=top_k,
        score_threshold=threshold,
        coarse_top_k=config.get("coarse_top_k"),
        hybrid=config.get("hybrid"),
        rerank=config.get("rerank"),
    )
    return {"data": {"query": request.query, "top_k": top_k, "hits": hits}}


# --------------------------------------------------------------------------- 模型 / 检索 provider

@router.get("/providers", dependencies=[Depends(require_permission("provider:read"))])
def list_providers() -> dict[str, Any]:
    settings = get_settings()
    return {
        "data": {
            # 来自 AP_LLM_MODELS 的 OpenAI 兼容模型清单（配置唯一来源是 settings，管理端只读回显）
            "llm": [
                {
                    "name": key,
                    "label": entry.get("label") or key,
                    "configured": bool(entry.get("base_url") and entry.get("api_key") and entry.get("model")),
                    "detail": entry.get("base_url", ""),
                }
                for key, entry in settings.llm_models.items()
            ],
            "retriever": [
                {
                    "name": "builtin",
                    "label": "内置向量库",
                    "configured": True,
                    "detail": f"dim={settings.embedding_dim}",
                },
                {
                    "name": "light_rag",
                    "label": "LightRAG",
                    "configured": bool(settings.light_rag_base_url),
                    "detail": settings.light_rag_base_url,
                },
                {
                    "name": "knowflow",
                    "label": "知流",
                    "configured": bool(settings.knowflow_base_url),
                    "detail": settings.knowflow_base_url,
                },
                {
                    "name": "knowledge_graph",
                    "label": "知识图谱",
                    "configured": bool(settings.knowledge_graph_base_url),
                    "detail": settings.knowledge_graph_base_url,
                },
            ],
            "embedding": {
                "name": "remote" if settings.embedding_base_url else "hash",
                "configured": bool(settings.embedding_base_url),
                "detail": settings.embedding_model or f"dim={settings.embedding_dim}",
            },
            "observability": {
                "name": "langfuse",
                "configured": bool(settings.langfuse_host and settings.langfuse_public_key),
                "detail": settings.langfuse_host,
            },
        }
    }


# --------------------------------------------------------------------------- 护栏配置（进程级开关，只读）

@router.get("/retrieval/config", dependencies=[Depends(require_permission("provider:read"))])
def get_retrieval_config() -> dict[str, Any]:
    """检索流水线配置（只读）：入库分块 / 粗召回 / 混合精召回 / 重排序。"""
    settings = get_settings()
    return {
        "data": {
            "chunk_chars": settings.document_chunk_chars,
            "chunk_overlap": settings.document_chunk_overlap,
            "document_max_bytes": settings.document_max_bytes,
            "coarse_top_k": settings.retrieval_coarse_top_k,
            "hybrid_enabled": settings.retrieval_hybrid_enabled,
            "lexical_top_k": settings.retrieval_lexical_top_k,
            "rrf_k": settings.retrieval_rrf_k,
            "rerank_enabled": settings.rerank_enabled,
            "rerank_base_url": settings.rerank_base_url,
            "rerank_model": settings.rerank_model,
            "rerank_top_k": settings.rerank_top_k,
        }
    }


@router.get("/guard/config", dependencies=[Depends(require_permission("guard:read"))])
def get_guard_config() -> dict[str, Any]:
    settings = get_settings()
    return {
        "data": {
            "enabled": settings.guard_enabled,
            "sensitive_enabled": settings.guard_sensitive_enabled,
            "quota_enabled": settings.guard_quota_enabled,
            "rate_enabled": settings.guard_rate_enabled,
            "round_enabled": settings.guard_round_enabled,
            "daily_token_quota": settings.guard_daily_token_quota,
            "rate_per_minute": settings.guard_rate_per_minute,
            "max_rounds": settings.guard_max_rounds,
            "default_reply": settings.guard_default_reply,
        }
    }


# --------------------------------------------------------------------------- 工具声明 / 智能体 / 提示词模板

def _tool_dict(row: Any) -> dict[str, Any]:
    return {
        "uuid": row.uuid,
        "tenant_code": row.tenant_code,
        "name": row.name,
        "label": row.label,
        "category": row.category,
        "server": row.server,
        "kind": row.kind,
        "http_method": row.http_method,
        "http_path": row.http_path,
        "params": row.params or [],
        "retry_attempts": row.retry_attempts,
        "retry_backoff_seconds": row.retry_backoff_seconds,
        "fallback": row.fallback or {},
        "is_builtin": row.is_builtin,
    }


def _agent_dict(row: Any) -> dict[str, Any]:
    return {
        "uuid": row.uuid,
        "tenant_code": row.tenant_code,
        "code": row.code,
        "label": row.label,
        "role": row.role,
        "mode": row.mode,
        "provider": row.provider,
        "system_prompt": row.system_prompt,
        "prompt_template": row.prompt_template,
        "cot": bool(row.cot),
        "tools": row.tools or [],
        "retriever": row.retriever or {},
        "pipeline": row.pipeline or [],
        "max_steps": row.max_steps,
        "reflection_rounds": row.reflection_rounds,
        "temperature": row.temperature,
        "max_tokens": row.max_tokens,
        "is_builtin": row.is_builtin,
    }


def _prompt_dict(row: Any) -> dict[str, Any]:
    return {
        "uuid": row.uuid,
        "tenant_code": row.tenant_code,
        "code": row.code,
        "label": row.label,
        "system_prompt": row.system_prompt,
        "examples": row.examples or [],
        "cot_hint": row.cot_hint,
        "is_builtin": row.is_builtin,
    }


@router.get("/tools", dependencies=[Depends(require_permission("tool:read"))])
def list_tools_endpoint(
    tenant_code: str = "", principal: AdminPrincipal = Depends(get_current_admin)
) -> dict[str, Any]:
    return {"data": [_tool_dict(row) for row in services.list_tools(principal.scope_tenant(tenant_code))]}


@router.post("/tools", dependencies=[Depends(require_permission("tool:write"))])
def create_tool_endpoint(
    request: ToolUpsertRequest, principal: AdminPrincipal = Depends(get_current_admin)
) -> dict[str, Any]:
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="工具名不能为空")
    if services.get_tool_by_name(name) is not None:
        raise HTTPException(status_code=409, detail="工具名已存在")
    tenant = principal.scope_tenant(request.tenant_code or get_settings().default_tenant)
    row = services.create_tool(
        tenant_code=tenant, name=name, **request.model_dump(exclude={"tenant_code", "name"})
    )
    return {"data": _tool_dict(row)}


@router.put("/tools/{tool_uuid}", dependencies=[Depends(require_permission("tool:write"))])
def update_tool_endpoint(tool_uuid: str, request: ToolUpsertRequest) -> dict[str, Any]:
    row = services.update_tool(
        tool_uuid, **request.model_dump(exclude={"tenant_code", "name"})
    )
    if row is None:
        raise HTTPException(status_code=404, detail="工具不存在")
    return {"data": _tool_dict(row)}


@router.delete("/tools/{tool_uuid}", dependencies=[Depends(require_permission("tool:write"))])
def delete_tool_endpoint(tool_uuid: str) -> dict[str, Any]:
    if not services.delete_tool(tool_uuid):
        raise HTTPException(status_code=404, detail="工具不存在")
    return {"data": {"uuid": tool_uuid, "is_deleted": 1}}


@router.post("/tools/{tool_uuid}/test", dependencies=[Depends(require_permission("tool:write"))])
async def test_tool_endpoint(
    tool_uuid: str, request: ToolTestRequest, principal: AdminPrincipal = Depends(get_current_admin)
) -> dict[str, Any]:
    """用给定参数实调一次（走完整治理链路），只回显结果不落库。"""
    row = services.get_tool(tool_uuid)
    if row is None:
        raise HTTPException(status_code=404, detail="工具不存在")
    tenant = principal.scope_tenant(request.tenant_code or row.tenant_code or get_settings().default_tenant)
    try:
        result = await call_declared_tool(get_settings(), row.name, request.args, server=row.server, tenant_code=tenant)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"工具调用失败: {exc}") from exc
    return {"data": {"name": row.name, "result": result}}


@router.get("/agents", dependencies=[Depends(require_permission("agent:read"))])
def list_agents_endpoint(
    tenant_code: str = "", principal: AdminPrincipal = Depends(get_current_admin)
) -> dict[str, Any]:
    return {"data": [_agent_dict(row) for row in services.list_agents(principal.scope_tenant(tenant_code))]}


@router.post("/agents", dependencies=[Depends(require_permission("agent:write"))])
def create_agent_endpoint(
    request: AgentUpsertRequest, principal: AdminPrincipal = Depends(get_current_admin)
) -> dict[str, Any]:
    code = request.code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="agent code 不能为空")
    if request.mode not in AGENT_MODES:
        raise HTTPException(status_code=400, detail=f"不支持的工作模式: {request.mode}")
    if services.get_agent_by_code(code) is not None:
        raise HTTPException(status_code=409, detail="agent code 已存在")
    tenant = principal.scope_tenant(request.tenant_code or get_settings().default_tenant)
    row = services.create_agent(
        tenant_code=tenant, code=code, **request.model_dump(exclude={"tenant_code", "code"})
    )
    return {"data": _agent_dict(row)}


@router.put("/agents/{agent_uuid}", dependencies=[Depends(require_permission("agent:write"))])
def update_agent_endpoint(agent_uuid: str, request: AgentUpsertRequest) -> dict[str, Any]:
    if request.mode not in AGENT_MODES:
        raise HTTPException(status_code=400, detail=f"不支持的工作模式: {request.mode}")
    row = services.update_agent(agent_uuid, **request.model_dump(exclude={"tenant_code", "code"}))
    if row is None:
        raise HTTPException(status_code=404, detail="智能体不存在")
    return {"data": _agent_dict(row)}


@router.delete("/agents/{agent_uuid}", dependencies=[Depends(require_permission("agent:write"))])
def delete_agent_endpoint(agent_uuid: str) -> dict[str, Any]:
    if not services.delete_agent(agent_uuid):
        raise HTTPException(status_code=404, detail="智能体不存在")
    return {"data": {"uuid": agent_uuid, "is_deleted": 1}}


@router.get("/prompts", dependencies=[Depends(require_permission("prompt:read"))])
def list_prompts_endpoint(
    tenant_code: str = "", principal: AdminPrincipal = Depends(get_current_admin)
) -> dict[str, Any]:
    return {"data": [_prompt_dict(row) for row in services.list_prompts(principal.scope_tenant(tenant_code))]}


@router.post("/prompts", dependencies=[Depends(require_permission("prompt:write"))])
def create_prompt_endpoint(
    request: PromptUpsertRequest, principal: AdminPrincipal = Depends(get_current_admin)
) -> dict[str, Any]:
    code = request.code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="模板 code 不能为空")
    if services.get_prompt_by_code(code) is not None:
        raise HTTPException(status_code=409, detail="模板 code 已存在")
    tenant = principal.scope_tenant(request.tenant_code or get_settings().default_tenant)
    row = services.create_prompt(
        tenant_code=tenant, code=code, **request.model_dump(exclude={"tenant_code", "code"})
    )
    return {"data": _prompt_dict(row)}


@router.put("/prompts/{prompt_uuid}", dependencies=[Depends(require_permission("prompt:write"))])
def update_prompt_endpoint(prompt_uuid: str, request: PromptUpsertRequest) -> dict[str, Any]:
    row = services.update_prompt(prompt_uuid, **request.model_dump(exclude={"tenant_code", "code"}))
    if row is None:
        raise HTTPException(status_code=404, detail="提示词模板不存在")
    return {"data": _prompt_dict(row)}


@router.delete("/prompts/{prompt_uuid}", dependencies=[Depends(require_permission("prompt:write"))])
def delete_prompt_endpoint(prompt_uuid: str) -> dict[str, Any]:
    if not services.delete_prompt(prompt_uuid):
        raise HTTPException(status_code=404, detail="提示词模板不存在")
    return {"data": {"uuid": prompt_uuid, "is_deleted": 1}}


# --------------------------------------------------------------------------- 监控看板

@router.get("/metrics/overview", dependencies=[Depends(require_permission("metrics:read"))])
def metrics_overview(
    tenant_code: str = "",
    app_uuid: str = "",
    days: int = 7,
    principal: AdminPrincipal = Depends(get_current_admin),
) -> dict[str, Any]:
    return {"data": metrics.overview(tenant_code=principal.scope_tenant(tenant_code), app_uuid=app_uuid, days=days)}


# --------------------------------------------------------------------------- 图运行（编排调试）

def _resolve_run_definition(app_uuid: str, definition: dict[str, Any] | None) -> GraphDef:
    raw = definition if definition else services.get_draft(app_uuid)
    if not raw:
        raise HTTPException(status_code=400, detail="图定义为空，请先保存草稿或传入 definition")
    try:
        return GraphDef.model_validate(raw)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=f"图定义非法: {exc}") from exc


@router.post("/apps/{app_uuid}/graph/run-node", dependencies=[Depends(require_permission("graph:write"))])
async def run_graph_node(
    app_uuid: str,
    request: RunNodeRequest,
    ctx: EngineContext = Depends(get_engine_context),
    principal: AdminPrincipal = Depends(get_current_admin),
) -> dict[str, Any]:
    """单节点运行：不做上游推导，直接把 inputs 当可用变量执行该节点。"""
    app_row = services.get_app_by_uuid(app_uuid)
    if app_row is None:
        raise HTTPException(status_code=404, detail="应用不存在")
    graph_def = _resolve_run_definition(app_uuid, request.definition)
    if graph_def.node(request.node_id) is None:
        raise HTTPException(status_code=404, detail="节点不存在")
    ctx.tenant_code = app_row.tenant_code
    tracer = build_request_tracer(
        principal.username,
        {"app_id": app_row.app_id, "node_id": request.node_id, "source": "editor-node-run"},
        name="node-run",
    )
    ctx.tracer = tracer
    try:
        result = await run_node(graph_def, request.node_id, request.inputs, ctx)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"节点执行失败: {exc}") from exc
    finally:
        tracer.flush()
    return {"data": result}


@router.post("/apps/{app_uuid}/graph/run", dependencies=[Depends(require_permission("graph:write"))])
async def run_graph_stream(
    app_uuid: str,
    request: RunGraphRequest,
    ctx: EngineContext = Depends(get_engine_context),
    principal: AdminPrincipal = Depends(get_current_admin),
) -> StreamingResponse:
    """整图运行：基于传入的图定义（缺省取草稿）流式跑一遍，事件 node_start/token/node_end/final/error。"""
    app_row = services.get_app_by_uuid(app_uuid)
    if app_row is None:
        raise HTTPException(status_code=404, detail="应用不存在")
    graph_def = _resolve_run_definition(app_uuid, request.definition)
    ctx.tenant_code = app_row.tenant_code
    tracer = build_request_tracer(
        principal.username,
        {"app_id": app_row.app_id, "source": "editor-graph-run"},
        name="graph-run",
    )
    ctx.tracer = tracer

    async def _events() -> AsyncIterator[str]:
        try:
            async for item in stream_graph(graph_def, request.inputs, ctx):
                yield f"data: {json.dumps(item, ensure_ascii=False, default=str)}\n\n"
        except Exception as exc:  # noqa: BLE001 - 流式接口要把错误作为事件回传，不能直接抛
            payload = {"type": "error", "message": str(exc)}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        finally:
            tracer.flush()

    return StreamingResponse(
        _events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
