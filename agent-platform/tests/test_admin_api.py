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
        2, {"id": "http_1", "data": {"type": "http-request", "title": "HTTP"}}
    )
    data = api_client.post(f"/admin/apps/{created['uuid']}/graph/import", json={"dsl": dsl}).json()["data"]
    assert data["stats"] == {"total": 4, "converted": 3, "degraded": 1}
    assert any("http-request" in item for item in data["warnings"])


def test_import_graph_rejects_bad_dsl_and_missing_app(api_client):
    created = _create_app(api_client)
    bad = api_client.post(f"/admin/apps/{created['uuid']}/graph/import", json={"dsl": {"app": {}}})
    assert bad.status_code == 400
    assert api_client.post("/admin/apps/ghost/graph/import", json={"dsl": _dify_dsl()}).status_code == 404
