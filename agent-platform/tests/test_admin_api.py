"""中台管理端 API：应用注册表 / 图草稿-发布-回滚 / 敏感词 / MCP Server / 文档。"""
from __future__ import annotations


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


# --------------------------------------------------------------------------- 文档


def test_document_crud(api_client):
    created = api_client.post(
        "/admin/documents",
        json={"tenant_code": "t", "dataset_id": "d1", "title": "常州政务", "content": "常州天气查询办事指南"},
    ).json()["data"]
    assert created["title"] == "常州政务" and created["dataset_id"] == "d1"

    rows = api_client.get("/admin/documents", params={"tenant_code": "t"}).json()["data"]
    assert rows[0]["content"] == "常州天气查询办事指南"

    assert api_client.delete(f"/admin/documents/{created['uuid']}").json()["data"]["is_deleted"] == 1
    assert api_client.delete(f"/admin/documents/{created['uuid']}").status_code == 404
    assert api_client.get("/admin/documents", params={"tenant_code": "t"}).json()["data"] == []
