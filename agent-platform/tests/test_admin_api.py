"""中台管理端 API：应用注册表 / 图草稿-发布-回滚 / 敏感词 / MCP Server / 文档 / provider。"""
from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any

import httpx

from agent_platform.api import admin as admin_mod
from agent_platform.core.config import get_settings
from agent_platform.tools import mcp_bridge as bridge_mod


def _patch_tool_http(monkeypatch, handler) -> None:
    real = httpx.AsyncClient
    monkeypatch.setattr(
        bridge_mod.httpx, "AsyncClient", lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs)
    )


def _create_app(api_client, **overrides):
    payload = {"tenant_code": "t", "app_id": "app-1", "api_key": "key-1", "app_name": "demo"}
    payload.update(overrides)
    response = api_client.post("/admin/apps", json=payload)
    assert response.status_code == 200
    return response.json()["data"]


# --------------------------------------------------------------------------- 应用注册表


def test_create_app_generates_identifiers(api_client):
    data = _create_app(api_client, app_id="", api_key="")
    assert data["app_id"] and data["api_key"]
    assert data["tenant_code"] == "t" and data["app_name"] == "demo"


def test_create_app_uses_default_tenant(api_client):
    data = _create_app(api_client, tenant_code="")
    assert data["tenant_code"] == "changzhou"


def test_list_and_get_app(api_client):
    created = _create_app(api_client)
    listing = api_client.get("/admin/apps", params={"tenant_code": "t"}).json()["data"]
    assert [row["uuid"] for row in listing] == [created["uuid"]]
    assert api_client.get("/admin/apps", params={"tenant_code": "other"}).json()["data"] == []
    got = api_client.get(f"/admin/apps/{created['uuid']}").json()["data"]
    assert got["api_key"] == "key-1"
    assert api_client.get("/admin/apps/ghost").status_code == 404


def test_update_and_delete_app(api_client):
    created = _create_app(api_client)
    updated = api_client.put(
        f"/admin/apps/{created['uuid']}",
        json={"app_name": "改名", "suggested_questions": ["你好"]},
    ).json()["data"]
    assert updated["app_name"] == "改名" and updated["suggested_questions"] == ["你好"]
    assert api_client.put("/admin/apps/ghost", json={"app_name": "x"}).status_code == 404

    assert api_client.delete(f"/admin/apps/{created['uuid']}").json()["data"]["is_deleted"] == 1
    assert api_client.get(f"/admin/apps/{created['uuid']}").status_code == 404
    assert api_client.delete(f"/admin/apps/{created['uuid']}").status_code == 404


def test_create_app_conflicts_on_active_app_id(api_client):
    _create_app(api_client)
    response = api_client.post(
        "/admin/apps", json={"tenant_code": "t", "app_id": "app-1", "api_key": "key-2", "app_name": "dup"}
    )
    assert response.status_code == 409
    assert "app-1" in response.json()["detail"]


def test_recreate_after_delete_revives_same_app(api_client):
    created = _create_app(api_client)
    assert api_client.delete(f"/admin/apps/{created['uuid']}").status_code == 200

    revived = _create_app(api_client, api_key="key-2", app_name="重建")
    assert revived["uuid"] == created["uuid"]
    assert revived["is_deleted"] == 0
    assert revived["api_key"] == "key-2" and revived["app_name"] == "重建"
    rows = api_client.get("/admin/apps", params={"tenant_code": "t"}).json()["data"]
    assert [row["uuid"] for row in rows] == [created["uuid"]]


def test_recreate_after_delete_rejected_for_other_tenant(api_client):
    created = _create_app(api_client)
    api_client.delete(f"/admin/apps/{created['uuid']}")
    response = api_client.post("/admin/apps", json={"tenant_code": "other", "app_id": "app-1", "api_key": "key-2"})
    assert response.status_code == 409
    assert "租户" in response.json()["detail"]


# --------------------------------------------------------------------------- 图草稿 / 发布 / 回滚


def test_empty_graph_returns_blank_draft(api_client):
    created = _create_app(api_client)
    body = api_client.get(f"/admin/apps/{created['uuid']}/graph").json()["data"]
    assert body["status"] == "draft" and body["definition"] == {}


def test_save_draft_requires_app(api_client, graph_def):
    assert api_client.put("/admin/apps/ghost/graph/draft", json={"definition": graph_def}).status_code == 404


def test_publish_empty_draft_rejected(api_client):
    created = _create_app(api_client)
    response = api_client.post(f"/admin/apps/{created['uuid']}/graph/publish", json={})
    assert response.status_code == 400
    assert "草稿为空" in response.json()["detail"]


def test_publish_invalid_definition_rejected(api_client):
    created = _create_app(api_client)
    response = api_client.post(
        f"/admin/apps/{created['uuid']}/graph/publish", json={"definition": {"nodes": "oops"}}
    )
    assert response.status_code == 400
    assert "图定义非法" in response.json()["detail"]


def test_graph_draft_publish_versions_rollback(api_client, graph_def):
    created = _create_app(api_client)
    app_uuid = created["uuid"]

    draft = api_client.put(f"/admin/apps/{app_uuid}/graph/draft", json={"definition": graph_def}).json()["data"]
    assert draft["status"] == "draft" and draft["definition"]["nodes"]

    first = api_client.post(
        f"/admin/apps/{app_uuid}/graph/publish", json={"note": "初版", "created_by": "tester"}
    ).json()["data"]
    assert first["version"] == 1 and first["note"] == "初版"
    assert first["created_by"] == "tester"

    variant = {**graph_def, "nodes": [*graph_def["nodes"], {"id": "noop", "type": "end"}]}
    api_client.put(f"/admin/apps/{app_uuid}/graph/draft", json={"definition": variant})
    second = api_client.post(f"/admin/apps/{app_uuid}/graph/publish", json={}).json()["data"]
    assert second["version"] == 2

    versions = api_client.get(f"/admin/apps/{app_uuid}/graph/versions").json()["data"]
    assert [row["version"] for row in versions] == [2, 1]

    rolled = api_client.post(f"/admin/apps/{app_uuid}/graph/rollback", json={"version": 1}).json()["data"]
    assert rolled["version"] == 1
    restored = api_client.get(f"/admin/apps/{app_uuid}/graph").json()["data"]
    assert restored["status"] == "published"
    assert len(restored["definition"]["nodes"]) == len(graph_def["nodes"])

    assert api_client.post(f"/admin/apps/{app_uuid}/graph/rollback", json={"version": 9}).status_code == 404


# --------------------------------------------------------------------------- 敏感词


def test_sensitive_word_crud(api_client):
    created = api_client.post("/admin/sensitive-words", json={"word": "违禁"}).json()["data"]
    assert created["tenant_code"] == "changzhou"
    rows = api_client.get("/admin/sensitive-words", params={"tenant_code": "changzhou"}).json()["data"]
    assert [row["word"] for row in rows] == ["违禁"]
    assert api_client.delete(f"/admin/sensitive-words/{created['id']}").json()["data"]["id"] == created["id"]
    assert api_client.delete(f"/admin/sensitive-words/{created['id']}").status_code == 404


# --------------------------------------------------------------------------- MCP Server


def test_mcp_server_crud(api_client):
    created = api_client.post(
        "/admin/mcp-servers",
        json={"tenant_code": "t", "name": "weather", "url": "https://mcp.local", "kind": "mcp"},
    ).json()["data"]
    assert created["name"] == "weather" and created["kind"] == "mcp"
    rows = api_client.get("/admin/mcp-servers", params={"tenant_code": "t"}).json()["data"]
    assert rows[0]["url"] == "https://mcp.local"
    assert api_client.delete(f"/admin/mcp-servers/{created['uuid']}").json()["data"]["is_deleted"] == 1
    assert api_client.delete(f"/admin/mcp-servers/{created['uuid']}").status_code == 404


# --------------------------------------------------------------------------- 知识库 / 文档 / 分段


def _create_dataset(api_client, *, tenant_code="t", name="知识库") -> dict:
    response = api_client.post("/admin/datasets", json={"tenant_code": tenant_code, "name": name})
    assert response.status_code == 200
    return response.json()["data"]


def test_dataset_crud(api_client):
    created = _create_dataset(api_client)
    assert created["name"] == "知识库" and created["uuid"]
    assert api_client.post("/admin/datasets", json={"tenant_code": "t", "name": "  "}).status_code == 400

    rows = api_client.get("/admin/datasets", params={"tenant_code": "t"}).json()["data"]
    assert [row["uuid"] for row in rows] == [created["uuid"]]
    assert rows[0]["document_count"] == 0

    updated = api_client.put(
        f"/admin/datasets/{created['uuid']}", json={"name": "改名", "retrieval": {"top_k": 3}}
    ).json()["data"]
    assert updated["name"] == "改名" and updated["retrieval"] == {"top_k": 3}

    assert api_client.delete(f"/admin/datasets/{created['uuid']}").json()["data"]["is_deleted"] == 1
    assert api_client.delete(f"/admin/datasets/{created['uuid']}").status_code == 404
    assert api_client.get("/admin/datasets", params={"tenant_code": "t"}).json()["data"] == []
    assert api_client.get("/admin/datasets/ghost").status_code == 404


def test_document_text_ingest_list_segments_and_delete(api_client):
    dataset = _create_dataset(api_client)
    created = api_client.post(
        f"/admin/datasets/{dataset['uuid']}/documents",
        json={"name": "常州政务", "content": "常州天气查询办事指南"},
    ).json()["data"]
    assert created["name"] == "常州政务" and created["dataset_id"] == dataset["uuid"]
    assert created["status"] == "ready" and created["chunk_count"] == 1

    listing = api_client.get(f"/admin/datasets/{dataset['uuid']}/documents").json()["data"]
    assert listing["total"] == 1 and listing["items"][0]["uuid"] == created["uuid"]

    segments = api_client.get(f"/admin/documents/{created['uuid']}/segments").json()["data"]
    assert segments["total"] == 1 and segments["items"][0]["content"] == "常州天气查询办事指南"

    assert api_client.post(
        f"/admin/datasets/{dataset['uuid']}/documents", json={"content": "   "}
    ).status_code == 400
    assert api_client.post("/admin/datasets/ghost/documents", json={"content": "x"}).status_code == 404

    assert api_client.delete(f"/admin/documents/{created['uuid']}").json()["data"]["is_deleted"] == 1
    assert api_client.delete(f"/admin/documents/{created['uuid']}").status_code == 404
    assert api_client.get(f"/admin/datasets/{dataset['uuid']}/documents").json()["data"]["total"] == 0


def test_segment_update_toggle_and_delete(api_client):
    dataset = _create_dataset(api_client)
    document = api_client.post(
        f"/admin/datasets/{dataset['uuid']}/documents", json={"name": "d", "content": "常州天气"}
    ).json()["data"]
    segment = api_client.get(f"/admin/documents/{document['uuid']}/segments").json()["data"]["items"][0]

    updated = api_client.put(
        f"/admin/segments/{segment['uuid']}", json={"content": "上海天气", "enabled": 0}
    ).json()["data"]
    assert updated["content"] == "上海天气" and updated["enabled"] == 0

    assert api_client.delete(f"/admin/segments/{segment['uuid']}").json()["data"]["is_deleted"] == 1
    assert api_client.delete(f"/admin/segments/{segment['uuid']}").status_code == 404
    assert api_client.put("/admin/segments/ghost", json={"enabled": 1}).status_code == 404


def test_dataset_retrieve_hit_test(api_client):
    dataset = _create_dataset(api_client)
    base = f"/admin/datasets/{dataset['uuid']}"
    api_client.post(f"{base}/documents", json={"name": "指南", "content": "常州天气查询办事指南"})
    other = api_client.post(f"{base}/documents", json={"name": "其它", "content": "汽车置换补贴标准"}).json()["data"]

    hits = api_client.post(f"{base}/retrieve", json={"query": "常州天气"}).json()["data"]["hits"]
    assert hits and hits[0]["document_name"] == "指南"
    assert {"content", "document_name", "dataset_id", "position", "score"} <= set(hits[0])

    # 停用分段后不再被召回
    segment = api_client.get(f"/admin/documents/{other['uuid']}/segments").json()["data"]["items"][0]
    api_client.put(f"/admin/segments/{segment['uuid']}", json={"enabled": 0})
    disabled = api_client.post(f"{base}/retrieve", json={"query": "汽车置换"}).json()["data"]["hits"]
    assert all(hit["document_name"] != "其它" for hit in disabled)

    assert api_client.post("/admin/datasets/ghost/retrieve", json={"query": "x"}).status_code == 404


def test_dataset_stores_index_method_and_chunk_config(api_client):
    created = _create_dataset(api_client)
    assert created["index_method"] == "high_quality" and created["chunk_config"] == {}

    updated = api_client.put(
        f"/admin/datasets/{created['uuid']}",
        json={"name": "改名", "index_method": "economy", "chunk_config": {"max_chars": 300, "qa_mode": True}},
    ).json()["data"]
    assert updated["index_method"] == "economy"
    assert updated["chunk_config"]["max_chars"] == 300 and updated["chunk_config"]["qa_mode"] is True


def test_preview_chunks_from_text(api_client):
    response = api_client.post(
        "/admin/knowledge/preview",
        data={"text": "第一段。\n\n第二段。", "chunk_config": json.dumps({"max_chars": 100})},
    )
    data = response.json()["data"]
    assert data["total"] == 1 and data["chunks"][0]["content"] == "第一段。\n\n第二段。"
    assert data["char_count"] == len("第一段。\n\n第二段。")

    assert api_client.post("/admin/knowledge/preview", data={"text": "  "}).status_code == 400
    assert api_client.post(
        "/admin/knowledge/preview", data={"text": "x", "chunk_config": "{oops"}
    ).status_code == 400


def test_preview_chunks_from_upload(api_client):
    response = api_client.post(
        "/admin/knowledge/preview",
        files={"file": ("a.md", "甲。\n\n乙。".encode(), "text/markdown")},
        data={"chunk_config": json.dumps({"max_chars": 100})},
    )
    assert response.status_code == 200
    assert response.json()["data"]["total"] == 1


def test_upload_document_honours_chunk_config_override(api_client):
    dataset = _create_dataset(api_client)
    body = ("甲" * 30 + "\n\n" + "乙" * 30).encode("utf-8")
    response = _upload(
        api_client,
        f"/admin/datasets/{dataset['uuid']}/documents/upload",
        "a.md",
        body,
        chunk_config=json.dumps({"max_chars": 10}),
    )
    data = response.json()["data"]
    assert data["chunk_config"]["max_chars"] == 10
    segments = api_client.get(f"/admin/documents/{data['uuid']}/segments").json()["data"]
    assert segments["total"] == 6


def test_create_document_with_chunk_config(api_client):
    dataset = _create_dataset(api_client)
    created = api_client.post(
        f"/admin/datasets/{dataset['uuid']}/documents",
        json={"name": "d", "content": "甲" * 25, "chunk_config": {"max_chars": 10}},
    ).json()["data"]
    assert created["chunk_config"]["max_chars"] == 10 and created["chunk_count"] == 3


def test_upload_rejects_bad_chunk_config(api_client):
    dataset = _create_dataset(api_client)
    response = _upload(
        api_client, f"/admin/datasets/{dataset['uuid']}/documents/upload", "a.md", b"hello", chunk_config="{oops"
    )
    assert response.status_code == 400 and "chunk_config" in response.json()["detail"]


# --------------------------------------------------------------------------- Dify 导入


def _dify_dsl():
    return {
        "app": {"id": "dify-app", "name": "Dify 应用"},
        "workflow": {
            "graph": {
                "nodes": [
                    {
                        "id": "start",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {"type": "start", "title": "开始", "variables": [{"variable": "query", "type": "text-input"}]},
                    },
                    {
                        "id": "llm_1",
                        "type": "custom",
                        "position": {"x": 100, "y": 0},
                        "data": {"type": "llm", "title": "大模型", "model": {"name": "gpt-4o"}, "prompt_template": []},
                    },
                    {
                        "id": "answer_1",
                        "type": "custom",
                        "position": {"x": 200, "y": 0},
                        "data": {"type": "answer", "title": "回答", "answer": "答：{{#llm_1.text#}}"},
                    },
                ],
                "edges": [
                    {"id": "e1", "source": "start", "target": "llm_1"},
                    {"id": "e2", "source": "llm_1", "target": "answer_1"},
                ],
            }
        },
    }


def test_import_graph_from_object_and_save(api_client):
    created = _create_app(api_client, app_id="app-import")
    response = api_client.post(f"/admin/apps/{created['uuid']}/graph/import", json={"dsl": _dify_dsl()})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["saved"] is True
    assert data["stats"] == {"total": 3, "converted": 3, "degraded": 0}
    assert data["definition"]["app_id"] == "app-import"
    assert data["definition"]["name"] == "demo"
    assert [node["id"] for node in data["definition"]["nodes"]] == ["start1", "llm2", "answer3"]

    draft = api_client.get(f"/admin/apps/{created['uuid']}/graph").json()["data"]["definition"]
    assert draft["nodes"][2]["id"] == "answer3"
    assert api_client.post(f"/admin/apps/{created['uuid']}/graph/publish", json={}).status_code == 200


def test_import_graph_from_content_without_saving(api_client):
    import json

    created = _create_app(api_client)
    response = api_client.post(
        f"/admin/apps/{created['uuid']}/graph/import",
        json={"content": json.dumps(_dify_dsl()), "save": False, "name": "覆盖名"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["saved"] is False
    assert data["definition"]["name"] == "覆盖名"
    assert api_client.get(f"/admin/apps/{created['uuid']}/graph").json()["data"]["definition"] == {}


def test_import_graph_reports_degraded_nodes(api_client):
    created = _create_app(api_client)
    dsl = _dify_dsl()
    dsl["workflow"]["graph"]["nodes"].insert(
        2, {"id": "de_1", "data": {"type": "document-extractor", "title": "文档提取"}}
    )
    data = api_client.post(f"/admin/apps/{created['uuid']}/graph/import", json={"dsl": dsl}).json()["data"]
    assert data["stats"] == {"total": 4, "converted": 3, "degraded": 1}
    assert any("document-extractor" in item for item in data["warnings"])


def test_import_graph_rejects_bad_dsl_and_missing_app(api_client):
    created = _create_app(api_client)
    bad = api_client.post(f"/admin/apps/{created['uuid']}/graph/import", json={"dsl": {"app": {}}})
    assert bad.status_code == 400
    assert api_client.post("/admin/apps/ghost/graph/import", json={"dsl": _dify_dsl()}).status_code == 404


def _upload(api_client, path, filename, raw, **form):
    return api_client.post(path, files={"file": (filename, raw, "application/octet-stream")}, data=form)


def test_import_graph_from_yaml_file(api_client):
    import yaml

    created = _create_app(api_client, app_id="app-file")
    raw = yaml.safe_dump(_dify_dsl(), allow_unicode=True).encode("utf-8")
    response = _upload(api_client, f"/admin/apps/{created['uuid']}/graph/import/file", "app.yml", raw)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["saved"] is True
    assert data["stats"] == {"total": 3, "converted": 3, "degraded": 0}
    draft = api_client.get(f"/admin/apps/{created['uuid']}/graph").json()["data"]["definition"]
    assert [node["id"] for node in draft["nodes"]] == ["start1", "llm2", "answer3"]


def test_import_graph_from_json_file_without_saving(api_client):
    import json

    created = _create_app(api_client)
    raw = json.dumps(_dify_dsl(), ensure_ascii=False).encode("utf-8")
    response = _upload(
        api_client, f"/admin/apps/{created['uuid']}/graph/import/file", "app.json", raw, save="false", name="文件名"
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["saved"] is False and data["definition"]["name"] == "文件名"
    assert api_client.get(f"/admin/apps/{created['uuid']}/graph").json()["data"]["definition"] == {}


def test_import_graph_file_rejects_bad_suffix_bad_content_and_missing_app(api_client):
    created = _create_app(api_client)
    path = f"/admin/apps/{created['uuid']}/graph/import/file"
    bad_suffix = _upload(api_client, path, "app.txt", b"{}")
    assert bad_suffix.status_code == 400 and "不支持" in bad_suffix.json()["detail"]
    bad_content = _upload(api_client, path, "app.json", b'{"app": {}}')
    assert bad_content.status_code == 400
    assert _upload(api_client, "/admin/apps/ghost/graph/import/file", "app.json", b"{}").status_code == 404


def test_import_graph_file_rejects_oversized_upload(api_client, monkeypatch):
    monkeypatch.setenv("AP_UPLOAD_MAX_BYTES", "16")
    get_settings.cache_clear()
    try:
        created = _create_app(api_client)
        response = _upload(api_client, f"/admin/apps/{created['uuid']}/graph/import/file", "app.json", b"x" * 64)
        assert response.status_code == 413
    finally:
        get_settings.cache_clear()


def test_upload_document_chunks_into_segments(api_client, monkeypatch):
    # 显式固定分块字符数：默认 800 时正文仅 758 字（40×17 + 39 个 "\n\n"），不足两块，用例会失真
    monkeypatch.setenv("AP_DOCUMENT_CHUNK_CHARS", "200")
    get_settings.cache_clear()
    try:
        dataset = _create_dataset(api_client)
        body = ("常州政务大厅工作时间为周一至周五。\n\n" * 40).encode("utf-8")
        response = _upload(api_client, f"/admin/datasets/{dataset['uuid']}/documents/upload", "guide.md", body)
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["name"] == "guide" and data["file_type"] == ".md"
        assert data["chunk_count"] >= 2 and data["status"] == "ready" and data["ingest"] == "sync"

        segments = api_client.get(f"/admin/documents/{data['uuid']}/segments").json()["data"]
        assert segments["total"] == data["chunk_count"]
        assert api_client.get(
            f"/admin/datasets/{dataset['uuid']}/documents"
        ).json()["data"]["items"][0]["chunk_count"] == data["chunk_count"]
    finally:
        get_settings.cache_clear()


def test_upload_document_async_over_threshold(api_client, monkeypatch):
    # 直接改 settings 实例：走 env+cache_clear 时，异步入库的后台任务可能在 env 还原前
    # 重新填充缓存，把 threshold 泄漏给后续用例（曾导致 xlsx 上传被判为异步、chunk_count 为 0）。
    monkeypatch.setattr(get_settings(), "knowledge_async_threshold_bytes", 8)
    dataset = _create_dataset(api_client)
    response = _upload(
        api_client, f"/admin/datasets/{dataset['uuid']}/documents/upload", "big.md", b"x" * 64
    )
    assert response.status_code == 200
    data = response.json()["data"]
    # 未配 Redis 时走进程内后台任务：返回时可能已 ready，也可能仍 pending
    assert data["ingest"] == "scheduled" and data["status"] in ("pending", "ready")


def test_upload_document_decodes_gbk(api_client):
    dataset = _create_dataset(api_client)
    body = "常州天气查询办事指南".encode("gb18030")
    response = _upload(api_client, f"/admin/datasets/{dataset['uuid']}/documents/upload", "guide.txt", body)
    assert response.status_code == 200
    segments = api_client.get(
        f"/admin/documents/{response.json()['data']['uuid']}/segments"
    ).json()["data"]
    assert segments["items"][0]["content"] == "常州天气查询办事指南"


def test_upload_document_rejects_bad_suffix_and_empty_file(api_client):
    dataset = _create_dataset(api_client)
    path = f"/admin/datasets/{dataset['uuid']}/documents/upload"
    assert _upload(api_client, path, "a.exe", b"x").status_code == 400
    empty = _upload(api_client, path, "a.txt", b"   \n\n  ")
    assert empty.status_code == 400 and "为空" in empty.json()["detail"]
    assert _upload(api_client, "/admin/datasets/ghost/documents/upload", "a.txt", b"x").status_code == 404


# --------------------------------------------------------------------------- provider / 护栏配置


def test_list_providers_reports_configured_flags(api_client, monkeypatch):
    # 直接改缓存实例上的字段：字典类配置从 .env 读，monkeypatch.setenv 盖不住（pydantic-settings 的坑）
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_models", {})
    data = api_client.get("/admin/providers").json()["data"]
    assert data["llm"] == []
    assert [row["name"] for row in data["retriever"]] == ["builtin", "light_rag", "knowflow", "knowledge_graph"]
    assert data["retriever"][0]["configured"] is True
    assert data["embedding"]["name"] == "hash"
    assert data["observability"]["configured"] is False

    monkeypatch.setattr(
        settings,
        "llm_models",
        {
            "deepseek": {
                "label": "DeepSeek",
                "base_url": "https://api.deepseek.com/v1",
                "api_key": "sk-x",
                "model": "deepseek-chat",
            }
        },
    )
    monkeypatch.setattr(settings, "knowflow_base_url", "http://knowflow.internal")
    monkeypatch.setattr(settings, "embedding_base_url", "http://embed.internal")
    monkeypatch.setattr(settings, "embedding_model", "bge-m3")
    data = api_client.get("/admin/providers").json()["data"]
    assert data["llm"] == [
        {
            "name": "deepseek",
            "label": "DeepSeek",
            "configured": True,
            "detail": "https://api.deepseek.com/v1",
        }
    ]
    assert data["retriever"][2]["configured"] is True and data["retriever"][1]["configured"] is False
    assert data["embedding"] == {"name": "remote", "configured": True, "detail": "bge-m3"}


def _xlsx_bytes() -> bytes:
    import io

    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["地区", "数量"])
    sheet.append(["常州", 3])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_upload_document_accepts_xlsx(api_client):
    dataset = _create_dataset(api_client)
    response = _upload(
        api_client, f"/admin/datasets/{dataset['uuid']}/documents/upload", "表格.xlsx", _xlsx_bytes()
    )
    assert response.status_code == 200
    assert response.json()["data"]["chunk_count"] >= 1
    segments = api_client.get(
        f"/admin/documents/{response.json()['data']['uuid']}/segments"
    ).json()["data"]
    assert any("常州" in item["content"] for item in segments["items"])


def test_upload_document_rejects_unsupported_suffix(api_client):
    dataset = _create_dataset(api_client)
    response = _upload(api_client, f"/admin/datasets/{dataset['uuid']}/documents/upload", "app.exe", b"x")
    assert response.status_code == 400
    assert "不支持的文件类型" in response.json()["detail"]


def test_upload_document_enforces_configured_size_limit(api_client, monkeypatch):
    monkeypatch.setenv("AP_DOCUMENT_MAX_BYTES", "32")
    get_settings.cache_clear()
    try:
        dataset = _create_dataset(api_client)
        response = _upload(api_client, f"/admin/datasets/{dataset['uuid']}/documents/upload", "big.txt", b"x" * 128)
        assert response.status_code == 413
    finally:
        get_settings.cache_clear()


def test_upload_document_reports_parse_failure(api_client):
    dataset = _create_dataset(api_client)
    response = _upload(
        api_client, f"/admin/datasets/{dataset['uuid']}/documents/upload", "bad.pdf", b"definitely not a pdf"
    )
    assert response.status_code == 400
    assert "解析失败" in response.json()["detail"]


def test_get_retrieval_config_endpoint(api_client, monkeypatch):
    for key, value in (
        ("AP_RETRIEVAL_COARSE_TOP_K", "20"),
        ("AP_RETRIEVAL_HYBRID_ENABLED", "true"),
        ("AP_RERANK_ENABLED", "true"),
        ("AP_RERANK_BASE_URL", "https://rerank.local"),
        ("AP_RERANK_MODEL", "bge-reranker"),
    ):
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    try:
        data = api_client.get("/admin/retrieval/config").json()["data"]
        assert data["coarse_top_k"] == 20
        assert data["hybrid_enabled"] is True
        assert data["rerank_enabled"] is True
        assert data["rerank_base_url"] == "https://rerank.local"
        assert data["rerank_model"] == "bge-reranker"
        assert data["document_max_bytes"] == 15 * 1024 * 1024
    finally:
        get_settings.cache_clear()


# --------------------------------------------------------------------------- 工具 / 智能体 / 提示词

def test_builtin_agents_prompts_tools_are_seeded(api_client):
    agents = {row["code"] for row in api_client.get("/admin/agents").json()["data"]}
    assert {"gov.intent", "gov.retrieval", "gov.generate", "gov.compliance"} <= agents
    prompts = {row["code"] for row in api_client.get("/admin/prompts").json()["data"]}
    assert {"fewshot.gov_intent", "fewshot.gov_answer"} <= prompts
    tools = {row["name"] for row in api_client.get("/admin/tools").json()["data"]}
    assert {"gov.business.query", "gov.guide.search", "gov.form.validate"} <= tools


def test_tool_crud_and_test_endpoint(api_client, monkeypatch):
    created = api_client.post(
        "/admin/tools",
        json={
            "name": "gov.test.echo",
            "label": "示例工具",
            "server": "demo",
            "kind": "http",
            "http_path": "/tools/echo",
            "params": [{"name": "keyword", "type": "string", "required": True}],
        },
    )
    assert created.status_code == 200
    row = created.json()["data"]
    assert row["name"] == "gov.test.echo"
    assert row["params"][0]["required"] is True

    assert api_client.post("/admin/tools", json={"name": "gov.test.echo"}).status_code == 409
    assert api_client.post("/admin/tools", json={"name": "  "}).status_code == 400

    missing = api_client.post(f"/admin/tools/{row['uuid']}/test", json={"args": {}})
    assert missing.status_code == 400
    assert "参数校验失败" in missing.json()["detail"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    _patch_tool_http(monkeypatch, handler)
    monkeypatch.setattr(get_settings(), "tool_servers", {"demo": {"url": "https://demo.local", "kind": "http"}})
    ok = api_client.post(f"/admin/tools/{row['uuid']}/test", json={"args": {"keyword": "x"}})
    assert ok.status_code == 200
    assert ok.json()["data"]["result"] == {"ok": True}

    updated = api_client.put(f"/admin/tools/{row['uuid']}", json={"name": "x", "label": "改名"})
    assert updated.json()["data"]["label"] == "改名"

    assert api_client.delete(f"/admin/tools/{row['uuid']}").json()["data"]["is_deleted"] == 1
    assert api_client.put(f"/admin/tools/{row['uuid']}", json={"name": "x"}).status_code == 404


def test_agent_crud_and_mode_validation(api_client):
    created = api_client.post(
        "/admin/agents",
        json={"code": "local.custom", "label": "自定义", "mode": "react", "system_prompt": "hi", "cot": True},
    )
    assert created.status_code == 200
    row = created.json()["data"]
    assert row["cot"] is True and row["mode"] == "react"

    bad = api_client.post("/admin/agents", json={"code": "local.bad", "mode": "ghost"})
    assert bad.status_code == 400
    assert "不支持的工作模式" in bad.json()["detail"]

    auto = api_client.post("/admin/agents", json={"code": "local.auto", "mode": "autonomous"})
    assert auto.status_code == 200
    assert auto.json()["data"]["mode"] == "autonomous"

    assert api_client.post("/admin/agents", json={"code": "local.custom"}).status_code == 409

    updated = api_client.put(f"/admin/agents/{row['uuid']}", json={"code": "x", "mode": "deep_search", "label": "改名"})
    assert updated.json()["data"]["mode"] == "deep_search"
    assert api_client.put(f"/admin/agents/{row['uuid']}", json={"code": "x", "mode": "ghost"}).status_code == 400

    assert api_client.delete(f"/admin/agents/{row['uuid']}").json()["data"]["is_deleted"] == 1


def test_prompt_crud(api_client):
    created = api_client.post(
        "/admin/prompts",
        json={
            "code": "fewshot.custom",
            "label": "自定义模板",
            "system_prompt": "sys",
            "examples": [{"input": "i", "output": "o"}],
            "cot_hint": "hint",
        },
    )
    assert created.status_code == 200
    row = created.json()["data"]
    assert row["examples"][0]["input"] == "i"

    assert api_client.post("/admin/prompts", json={"code": "fewshot.custom"}).status_code == 409

    updated = api_client.put(f"/admin/prompts/{row['uuid']}", json={"code": "x", "label": "改"})
    assert updated.json()["data"]["label"] == "改"

    assert api_client.delete(f"/admin/prompts/{row['uuid']}").json()["data"]["is_deleted"] == 1
    assert api_client.delete(f"/admin/prompts/{row['uuid']}").status_code == 404


def test_graph_templates_endpoint(api_client):
    listing = api_client.get("/admin/graph/templates").json()["data"]
    assert any(item["key"] == "pipeline.gov_consult" for item in listing)
    template = api_client.get("/admin/graph/templates/pipeline.gov_consult").json()["data"]
    types = [node["type"] for node in template["definition"]["nodes"]]
    assert types.count("agent") == 4
    assert api_client.get("/admin/graph/templates/ghost").status_code == 404


# --------------------------------------------------------------------------- 图运行（编排调试）

RUN_GRAPH = {
    "nodes": [
        {"id": "start1", "type": "start"},
        {"id": "llm2", "type": "llm", "config": {"user_prompt": "{{ query }}", "output_var": "text"}},
        {"id": "answer3", "type": "answer", "config": {"template": "{{ text }}"}},
        {"id": "end4", "type": "end"},
    ],
    "edges": [
        {"source": "start1", "target": "llm2"},
        {"source": "llm2", "target": "answer3"},
        {"source": "answer3", "target": "end4"},
    ],
}


def test_run_node_executes_a_single_node(api_client):
    created = _create_app(api_client)
    response = api_client.post(
        f"/admin/apps/{created['uuid']}/graph/run-node",
        json={"node_id": "llm2", "definition": RUN_GRAPH, "inputs": {"query": "常州"}},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["node_id"] == "llm2" and data["node_type"] == "llm"
    assert data["output"] == "echo:常州"
    assert data["variables"]["text"] == "echo:常州"


def test_run_node_falls_back_to_answer_for_terminal_nodes(api_client):
    created = _create_app(api_client)
    response = api_client.post(
        f"/admin/apps/{created['uuid']}/graph/run-node",
        json={"node_id": "answer3", "definition": RUN_GRAPH, "inputs": {"query": "常州", "text": "现成文本"}},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["answer"] == "现成文本"
    assert data["output"] == "现成文本"


def test_run_node_reports_missing_app_and_node(api_client):
    created = _create_app(api_client)
    missing_node = api_client.post(
        f"/admin/apps/{created['uuid']}/graph/run-node",
        json={"node_id": "ghost", "definition": RUN_GRAPH, "inputs": {}},
    )
    assert missing_node.status_code == 404
    missing_app = api_client.post(
        "/admin/apps/ghost/graph/run-node", json={"node_id": "llm2", "definition": RUN_GRAPH}
    )
    assert missing_app.status_code == 404


def test_run_node_surfaces_execution_errors(api_client):
    created = _create_app(api_client)
    graph = {
        "nodes": [
            {"id": "start1", "type": "start"},
            {"id": "llm2", "type": "llm", "config": {"user_prompt": "{{ missing_var }}"}},
        ]
    }
    response = api_client.post(
        f"/admin/apps/{created['uuid']}/graph/run-node",
        json={"node_id": "llm2", "definition": graph, "inputs": {}},
    )
    assert response.status_code == 400
    assert "节点执行失败" in response.json()["detail"]


def test_run_node_requires_a_definition_or_draft(api_client):
    created = _create_app(api_client)
    response = api_client.post(f"/admin/apps/{created['uuid']}/graph/run-node", json={"node_id": "llm2"})
    assert response.status_code == 400
    assert "图定义为空" in response.json()["detail"]


def test_run_node_rejects_invalid_definition(api_client):
    created = _create_app(api_client)
    response = api_client.post(
        f"/admin/apps/{created['uuid']}/graph/run-node",
        json={"node_id": "llm2", "definition": {"nodes": [{"id": "x", "type": "not-a-type"}]}},
    )
    assert response.status_code == 400
    assert "图定义非法" in response.json()["detail"]


def test_run_graph_streams_node_and_final_events(api_client):
    created = _create_app(api_client)
    response = api_client.post(
        f"/admin/apps/{created['uuid']}/graph/run", json={"definition": RUN_GRAPH, "inputs": {"query": "常州"}}
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    types = [event["type"] for event in events]
    assert "node_start" in types
    assert types[-1] == "final"
    assert [event["node"] for event in events if event["type"] == "node_start"][:1] == ["start1"]
    final = events[-1]
    assert final["answer"] == "echo:常州"
    assert final["state"]["variables"]["text"] == "echo:常州"


def test_run_graph_requires_an_existing_app(api_client):
    response = api_client.post("/admin/apps/ghost/graph/run", json={"definition": RUN_GRAPH, "inputs": {}})
    assert response.status_code == 404


class _RecordingSpan:
    def __init__(self, ends: list) -> None:
        self._ends = ends

    def end(self, output: Any = None, error: str = "") -> None:
        self._ends.append({"output": output, "error": error})


class _RecordingTracer:
    """记录 span 的假 tracer：验证编辑器运行链路也埋点。"""

    enabled = True

    def __init__(self) -> None:
        self.spans: list[tuple[str, str]] = []
        self.ends: list[dict] = []
        self.flushed = 0

    @contextmanager
    def node_span(self, node_id: str, node_type: str, payload: Any = None) -> Any:
        self.spans.append((node_id, node_type))
        span = _RecordingSpan(self.ends)
        try:
            yield span
        except Exception as exc:
            span.end(error=str(exc))
            raise

    def flush(self) -> None:
        self.flushed += 1


def test_run_node_records_trace_span(api_client, monkeypatch):
    tracer = _RecordingTracer()
    monkeypatch.setattr(admin_mod, "build_request_tracer", lambda user, metadata, **kwargs: tracer)
    created = _create_app(api_client)
    response = api_client.post(
        f"/admin/apps/{created['uuid']}/graph/run-node",
        json={"node_id": "llm2", "definition": RUN_GRAPH, "inputs": {"query": "常州"}},
    )
    assert response.status_code == 200
    assert tracer.spans == [("llm2", "llm")]
    assert tracer.ends == [{"output": {"query": "常州", "llm2": "echo:常州", "text": "echo:常州"}, "error": ""}]
    assert tracer.flushed == 1


def test_run_graph_records_trace_spans(api_client, monkeypatch):
    tracer = _RecordingTracer()
    monkeypatch.setattr(admin_mod, "build_request_tracer", lambda user, metadata, **kwargs: tracer)
    created = _create_app(api_client)
    response = api_client.post(
        f"/admin/apps/{created['uuid']}/graph/run",
        json={"definition": RUN_GRAPH, "inputs": {"query": "常州"}},
    )
    assert response.status_code == 200
    assert [item[0] for item in tracer.spans] == ["start1", "llm2", "answer3", "end4"]
    assert [item[1] for item in tracer.spans] == ["start", "llm", "answer", "end"]
    assert tracer.flushed == 1


def test_run_node_still_reports_errors_with_tracing(api_client, monkeypatch):
    tracer = _RecordingTracer()
    monkeypatch.setattr(admin_mod, "build_request_tracer", lambda user, metadata, **kwargs: tracer)
    created = _create_app(api_client)
    graph = {
        "nodes": [
            {"id": "start1", "type": "start"},
            {"id": "llm2", "type": "llm", "config": {"user_prompt": "{{ missing_var }}"}},
        ]
    }
    response = api_client.post(
        f"/admin/apps/{created['uuid']}/graph/run-node",
        json={"node_id": "llm2", "definition": graph, "inputs": {}},
    )
    assert response.status_code == 400
    assert tracer.spans == [("llm2", "llm")]
    assert tracer.flushed == 1


def test_get_guard_config_returns_effective_switches(api_client, monkeypatch):
    monkeypatch.setenv("AP_GUARD_ENABLED", "false")
    monkeypatch.setenv("AP_GUARD_MAX_ROUNDS", "5")
    get_settings.cache_clear()
    try:
        data = api_client.get("/admin/guard/config").json()["data"]
        assert data["enabled"] is False
        assert data["max_rounds"] == 5
        assert data["sensitive_enabled"] is False and data["rate_enabled"] is False
        assert data["default_reply"] == ""
    finally:
        get_settings.cache_clear()
