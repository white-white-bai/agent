"""兼容出口契约回归：云智 Envelope（{code,msg,data}）与 Dify 响应体。"""
from __future__ import annotations

import uuid

from agent_platform.api import services
from agent_platform.core.db import session_scope
from agent_platform.domain.models import Conversation

API_KEY = "key-1"
HEADERS = {"Api-Key": API_KEY}


def _seed_conversation(
    app_uuid: str, *, user: str = "alice", conversation_id: str = "conv-1", tenant: str = "t", name: str = "会话一"
):
    with session_scope() as session:
        row = Conversation(
            uuid=uuid.uuid4().hex,
            tenant_code=tenant,
            app_uuid=app_uuid,
            conversation_id=conversation_id,
            user_name=user,
            name=name,
        )
        session.add(row)
        session.flush()
    return row


def _seed_messages(app_uuid: str, conversation_id: str, count: int = 2) -> list[str]:
    conversation = services.get_conversation(conversation_id)
    ids = []
    for index in range(count):
        message_id = f"msg-{index + 1}"
        services.save_message(
            conversation,
            "assistant",
            query=f"q{index + 1}",
            answer=f"a{index + 1}",
            metadata={"retriever_resources": []},
            message_id=message_id,
        )
        ids.append(message_id)
    return ids


# --------------------------------------------------------------------------- 云智鉴权 / transfer


def test_oauth2_token_issues_envelope(api_client):
    response = api_client.post("/api/oauth2/token", json={"client_id": "cloud", "client_secret": "s"})
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 200 and body["msg"] == "success"
    assert body["data"]["token"] and body["data"]["expire"] > 0


def test_oauth2_token_rejects_empty_client(api_client):
    response = api_client.post("/api/oauth2/token", json={})
    assert response.status_code == 401


def test_cloud_conversations_returns_records_envelope(api_client, seed_app):
    app_uuid, _ = seed_app()
    _seed_conversation(app_uuid, user="alice")
    response = api_client.get("/api/transfer/one/chat-messages/conversations", params={"user": "alice"}, headers=HEADERS)
    body = response.json()
    assert body["code"] == 200
    assert body["data"]["total"] == 1
    item = body["data"]["records"][0]
    assert item["id"] == "conv-1" and item["status"] == "normal"


def test_cloud_conversations_rejects_bad_key(api_client):
    response = api_client.get("/api/transfer/one/chat-messages/conversations", headers={"Api-Key": "nope"})
    assert response.status_code == 401


def test_cloud_rename_conversation(api_client, seed_app):
    app_uuid, _ = seed_app()
    _seed_conversation(app_uuid)
    response = api_client.post(
        "/api/transfer/one/chat-messages/conversations/rename",
        params={"conversation_id": "conv-1"},
        json={"name": "新名字"},
        headers=HEADERS,
    )
    body = response.json()
    assert body["data"]["name"] == "新名字"


def test_cloud_rename_unknown_conversation(api_client, seed_app):
    seed_app()
    response = api_client.post(
        "/api/transfer/one/chat-messages/conversations/rename",
        params={"conversation_id": "missing"},
        json={"name": "x"},
        headers=HEADERS,
    )
    assert response.status_code == 404


def test_cloud_messages_returns_records(api_client, seed_app):
    app_uuid, _ = seed_app()
    _seed_conversation(app_uuid)
    _seed_messages(app_uuid, "conv-1", count=3)
    response = api_client.get(
        "/api/transfer/one/chat-messages/messages", params={"conversation_id": "conv-1"}, headers=HEADERS
    )
    body = response.json()
    assert body["data"]["total"] == 3
    assert body["data"]["records"][0]["conversation_id"] == "conv-1"
    assert body["data"]["records"][0]["metadata"] == {"retriever_resources": []}


def test_cloud_feedback_roundtrip(api_client, seed_app):
    app_uuid, _ = seed_app()
    _seed_conversation(app_uuid)
    _seed_messages(app_uuid, "conv-1", count=1)
    response = api_client.post(
        "/api/transfer/one/chat-messages/feedback",
        params={"message_id": "msg-1"},
        json={"rating": "like", "user": "alice"},
        headers=HEADERS,
    )
    body = response.json()
    assert body["data"] == {"message_id": "msg-1", "feedback": "like"}


def test_cloud_feedback_unknown_message(api_client, seed_app):
    seed_app()
    response = api_client.post(
        "/api/transfer/one/chat-messages/feedback", params={"message_id": "missing"}, json={}, headers=HEADERS
    )
    assert response.status_code == 404


def test_cloud_suggested_and_stop(api_client, seed_app):
    seed_app()
    suggested = api_client.get("/api/transfer/one/chat-messages/suggested", headers=HEADERS).json()
    assert suggested["data"] == {"data": []}
    stopped = api_client.post("/api/transfer/one/chat-messages/stop", params={"task_id": "t1"}).json()
    assert stopped["data"] == {"result": "success", "task_id": "t1"}


# --------------------------------------------------------------------------- 云智 open/dify


def test_cloud_app_list_shape(api_client, seed_app):
    seed_app(tenant_code="t", app_id="app-1", app_name="demo")
    body = api_client.post("/api/open/dify/difyApp", params={"tenant_code": "t"}).json()
    assert body["code"] == 200
    record = body["data"]["records"][0]
    assert record["thirdId"] == "app-1"
    assert record["appId"] == "app-1"
    assert record["apiKey"] == API_KEY
    assert record["tenantCode"] == "t"


def test_cloud_app_info_by_identifier(api_client, seed_app):
    seed_app(app_id="app-1")
    body = api_client.post("/api/open/dify/getDifyAppInfo", json={"appId": "app-1"}).json()
    assert body["data"]["appId"] == "app-1"


def test_cloud_app_info_missing_and_unknown(api_client, seed_app):
    seed_app()
    assert api_client.post("/api/open/dify/getDifyAppInfo", json={}).status_code == 400
    assert api_client.post("/api/open/dify/getDifyAppInfo", json={"appId": "ghost"}).status_code == 404


def test_cloud_list_conversation_direct_paging(api_client, seed_app):
    app_uuid, _ = seed_app()
    for index in range(3):
        _seed_conversation(app_uuid, conversation_id=f"conv-{index}", user="alice")
    body = api_client.post(
        "/api/open/dify/listConversationDirect",
        json={"appId": "app-1", "userName": "alice", "pageNum": 1, "pageSize": 2},
    ).json()
    assert body["data"]["total"] == 3
    assert body["data"]["current"] == 1 and body["data"]["size"] == 2
    assert len(body["data"]["records"]) == 2


def test_cloud_list_message_direct(api_client, seed_app):
    app_uuid, _ = seed_app()
    _seed_conversation(app_uuid)
    _seed_messages(app_uuid, "conv-1", count=2)
    body = api_client.post(
        "/api/open/dify/listConversationMessageDirect", json={"conversationId": "conv-1"}
    ).json()
    assert body["data"]["total"] == 2
    assert body["data"]["records"][0]["thirdId"].startswith("msg-")
    empty = api_client.post("/api/open/dify/listConversationMessageDirect", json={"conversationId": "ghost"}).json()
    assert empty["data"]["records"] == []


def test_cloud_list_feedback_direct(api_client, seed_app):
    app_uuid, _ = seed_app()
    _seed_conversation(app_uuid)
    _seed_messages(app_uuid, "conv-1", count=2)
    services.set_feedback("msg-1", "like", "alice")
    body = api_client.post(
        "/api/open/dify/listConversationMessageFeedbacksDirect", json={"conversationId": "conv-1"}
    ).json()
    assert body["data"]["total"] == 1
    assert body["data"]["records"][0]["feedback"] == "like"


def test_cloud_list_end_user(api_client, seed_app):
    app_uuid, _ = seed_app()
    _seed_conversation(app_uuid, conversation_id="conv-1", user="alice")
    _seed_conversation(app_uuid, conversation_id="conv-2", user="bob")
    body = api_client.post("/api/open/dify/listDifyEndUser", json={"appId": "app-1"}).json()
    assert [item["userName"] for item in body["data"]["records"]] == ["alice", "bob"]


def test_cloud_run_workflow_nested_envelope(api_client, seed_app):
    seed_app(app_id="app-1")
    body = api_client.post("/api/open/dify/runWorkflow", json={"appId": "app-1", "inputs": {"query": "你好"}}).json()
    assert body["code"] == 200
    payload = body["data"]["data"]["data"]
    assert payload["status"] == "succeeded"
    assert payload["outputs"]["answer"] == "echo:你好"
    assert payload["outputs"]["answer_text"] == "echo:你好"
    assert payload["outputs"]["status"] == "success"


def test_cloud_run_workflow_without_published_graph(api_client, seed_app):
    seed_app(app_id="app-1", published=False)
    body = api_client.post("/api/open/dify/runWorkflow", json={"appId": "app-1"}).json()
    payload = body["data"]["data"]["data"]
    assert payload["status"] == "failed"
    assert payload["error"] == "应用未发布图定义"


def test_cloud_parameters_envelope(api_client, seed_app):
    seed_app()
    body = api_client.get("/api/open/dify/parameters", params={"app_id": "app-1"}, headers=HEADERS).json()
    assert body["data"]["data"]["opening_statement"] == ""
    assert api_client.get("/api/open/dify/parameters", params={"app_id": "ghost"}, headers=HEADERS).status_code == 404


# --------------------------------------------------------------------------- 原始 Dify /v1


def test_dify_feedback_returns_result(api_client, seed_app):
    app_uuid, _ = seed_app()
    _seed_conversation(app_uuid)
    _seed_messages(app_uuid, "conv-1", count=1)
    response = api_client.post("/v1/messages/msg-1/feedbacks", json={"rating": "dislike"}, headers=HEADERS)
    assert response.json() == {"result": "success"}
    feedbacks = api_client.post(
        "/api/open/dify/listConversationMessageFeedbacksDirect", json={"conversationId": "conv-1"}
    ).json()
    assert feedbacks["data"]["records"][0]["feedback"] == "dislike"


def test_dify_suggested(api_client, seed_app):
    seed_app()
    body = api_client.get("/v1/messages/msg-1/suggested", headers=HEADERS).json()
    assert body == {"result": "success", "data": []}


def test_dify_rename_conversation(api_client, seed_app):
    app_uuid, _ = seed_app()
    _seed_conversation(app_uuid)
    body = api_client.post("/v1/conversations/conv-1/name", json={"name": "改名"}, headers=HEADERS).json()
    assert body["id"] == "conv-1" and body["name"] == "改名"


def test_dify_rename_auto_generate_uses_first_query(api_client, seed_app):
    app_uuid, _ = seed_app()
    _seed_conversation(app_uuid, name="")
    conversation = services.get_conversation("conv-1")
    services.save_message(conversation, "user", query="常州天气怎么样", message_id="msg-user")
    body = api_client.post("/v1/conversations/conv-1/name", json={"auto_generate": True}, headers=HEADERS).json()
    assert body["name"] == "常州天气怎么样"


def test_dify_conversations_pagination(api_client, seed_app):
    app_uuid, _ = seed_app()
    for index in range(3):
        _seed_conversation(app_uuid, conversation_id=f"conv-{index}")
    body = api_client.get("/v1/conversations", params={"limit": 2}, headers=HEADERS).json()
    assert body["limit"] == 2 and body["has_more"] is True and len(body["data"]) == 2
    assert body["data"][0]["inputs"] == {} and body["data"][0]["status"] == "normal"


def test_dify_messages_pagination(api_client, seed_app):
    app_uuid, _ = seed_app()
    _seed_conversation(app_uuid)
    _seed_messages(app_uuid, "conv-1", count=3)
    body = api_client.get("/v1/messages", params={"conversation_id": "conv-1", "limit": 2}, headers=HEADERS).json()
    assert body["has_more"] is True and len(body["data"]) == 2
    assert body["data"][0]["conversation_id"] == "conv-1"


def test_dify_parameters_shape(api_client, seed_app):
    seed_app()
    body = api_client.get("/v1/parameters", headers=HEADERS).json()
    assert body["opening_statement"] == ""
    assert body["user_input_form"] == []
    assert body["system_parameters"]["file_size_limit"] == 15
    assert body["retriever_resource"] == {"enabled": True}


def test_dify_workflow_run(api_client, seed_app):
    seed_app()
    body = api_client.post("/v1/workflows/run", json={"inputs": {"query": "hi"}}, headers=HEADERS).json()
    assert body["workflow_run_id"] and body["task_id"] == body["workflow_run_id"]
    assert body["data"]["status"] == "succeeded"
    assert body["data"]["outputs"]["answer"] == "echo:hi"
    assert body["data"]["error"] is None


def test_dify_workflow_run_requires_published_graph(api_client, seed_app):
    seed_app(published=False)
    response = api_client.post("/v1/workflows/run", json={"inputs": {}}, headers=HEADERS)
    assert response.status_code == 400


def test_dify_file_upload(api_client, seed_app):
    seed_app()
    response = api_client.post(
        "/v1/files/upload",
        files={"file": ("note.txt", b"hello", "text/plain")},
        params={"user": "alice"},
        headers=HEADERS,
    )
    body = response.json()
    assert body["name"] == "note.txt" and body["size"] == 5
    assert body["extension"] == "txt" and body["created_by"] == "alice"


def test_dify_endpoints_require_api_key(api_client):
    assert api_client.get("/v1/parameters").status_code == 401
    assert api_client.get("/v1/conversations", headers={"Api-Key": "bad"}).status_code == 401
