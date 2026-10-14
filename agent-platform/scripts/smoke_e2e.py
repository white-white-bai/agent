"""内网冒烟：真 MySQL + 真云智网关 + 真实模型，跑通两条兼容链路并断言 SSE / Envelope 形状。

    python scripts/smoke_e2e.py                      # 进程内 ASGI（读 .env，连真 MySQL/云智）
    python scripts/smoke_e2e.py --base-url http://127.0.0.1:8900
    python scripts/smoke_e2e.py --app-id smoke-e2e --api-key <存量 key>

会以固定 app_id（默认 smoke-e2e）建/复用应用并发布一次图定义，每次运行新增一个图版本；只应在开发/测试库执行。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from typing import Any

import httpx

GRAPH_DEFINITION: dict[str, Any] = {
    "nodes": [
        {"id": "start", "type": "start"},
        {"id": "llm", "type": "llm", "config": {"user_prompt": "{{ query }}", "output_var": "text"}},
        {"id": "answer", "type": "answer", "config": {"template": "{{ text }}"}},
        {"id": "end", "type": "end"},
    ],
    "edges": [
        {"source": "start", "target": "llm"},
        {"source": "llm", "target": "answer"},
        {"source": "answer", "target": "end"},
    ],
}


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.skips: list[str] = []

    def ok(self, name: str, detail: str = "") -> None:
        print(f"[ok]   {name}" + (f"  {detail}" if detail else ""))

    def fail(self, name: str, detail: str) -> None:
        print(f"[FAIL] {name}  {detail}")
        self.failures.append(name)

    def skip(self, name: str, detail: str) -> None:
        print(f"[skip] {name}  {detail}")
        self.skips.append(name)

    def expect(self, name: str, condition: bool, detail: str = "") -> bool:
        if condition:
            self.ok(name, detail)
        else:
            self.fail(name, detail)
        return condition


def parse_sse(text: str) -> list[dict[str, Any]]:
    events = []
    for line in text.splitlines():
        if line.startswith("data:"):
            events.append(json.loads(line[5:].strip()))
    return events


def _event(events: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for item in events:
        if item.get("event") == name:
            return item
    return None


async def run_smoke(args: argparse.Namespace) -> int:
    report = Report()
    in_process = not args.base_url
    if in_process:
        from agent_platform.api.main import app as asgi_app
        from agent_platform.core.config import get_settings
        from agent_platform.core.db import init_db

        init_db()
        settings = get_settings()
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=asgi_app), base_url="http://smoke", timeout=args.timeout
        )
        tenant = args.tenant or settings.default_tenant
        check_idempotency = settings.idempotency_ttl_seconds > 0
        if not check_idempotency:
            report.skip("幂等重放", "AP_IDEMPOTENCY_TTL_SECONDS<=0，幂等已关闭")
    else:
        client = httpx.AsyncClient(base_url=args.base_url, timeout=args.timeout)
        tenant = args.tenant or "changzhou"
        check_idempotency = args.check_idempotency
        if not check_idempotency:
            report.skip("幂等重放", "远端模式需显式 --check-idempotency")

    async with client:
        async def get(path: str, **kw: Any) -> httpx.Response:
            return await client.get(path, **kw)

        async def post(path: str, **kw: Any) -> httpx.Response:
            return await client.post(path, **kw)

        response = await get("/healthz")
        report.expect("健康检查", response.status_code == 200 and response.json().get("status") == "ok")

        token = ""
        response = await post(
            "/api/oauth2/token",
            json={"grant_type": "client_credentials", "client_id": args.client_id, "client_secret": ""},
        )
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        if report.expect(
            "云智 oauth2 token",
            response.status_code == 200 and body.get("code") == 200 and bool((body.get("data") or {}).get("token")),
            str(body)[:200],
        ):
            token = body["data"]["token"]

        api_key = args.api_key
        app_uuid = ""
        if api_key:
            listing = (await get("/admin/apps", params={"tenant_code": tenant})).json()["data"]
            for row in listing:
                if row["api_key"] == api_key:
                    app_uuid = row["uuid"]
                    break
            report.expect("复用存量应用", bool(app_uuid), f"app_uuid={app_uuid}")
        else:
            listing = (await get("/admin/apps", params={"tenant_code": tenant})).json()["data"]
            existing = next((row for row in listing if row["app_id"] == args.app_id), None)
            if existing is None:
                response = await post(
                    "/admin/apps",
                    json={
                        "tenant_code": tenant,
                        "app_id": args.app_id,
                        "app_name": "smoke-e2e",
                        "opening_statement": "",
                        "suggested_questions": [],
                    },
                )
                existing = response.json().get("data") or {}
            app_uuid = existing.get("uuid", "")
            api_key = existing.get("api_key", "")
            report.expect("注册/复用应用", bool(app_uuid and api_key), f"app_id={args.app_id} app_uuid={app_uuid}")

        if app_uuid and api_key:
            response = await client.put(f"/admin/apps/{app_uuid}/graph/draft", json={"definition": GRAPH_DEFINITION})
            report.expect(
                "保存图草稿", response.status_code == 200 and bool(response.json()["data"].get("definition")),
                f"status={response.status_code}",
            )
            response = await post(f"/admin/apps/{app_uuid}/graph/publish", json={"note": "smoke"})
            report.expect(
                "发布图版本", response.status_code == 200 and response.json()["data"].get("version", 0) >= 1,
                f"status={response.status_code}",
            )
        if not (app_uuid and api_key):
            print("\n应用不可用，跳过运行链路。")
            return 1

        headers = {"Api-Key": api_key}
        query = f"冒烟测试 {uuid.uuid4().hex[:6]}"
        conversation_id = ""

        response = await post("/v1/chat-messages", json={"query": query, "user": "smoke"}, headers=headers)
        events = parse_sse(response.text) if response.status_code == 200 else []
        end = _event(events, "message_end")
        if report.expect(
            "原始 Dify /v1/chat-messages",
            response.status_code == 200
            and response.headers.get("content-type", "").startswith("text/event-stream")
            and end is not None
            and bool(end.get("conversation_id"))
            and bool(end.get("message_id")),
            f"status={response.status_code} events={[e.get('event') for e in events]}",
        ):
            conversation_id = end["conversation_id"]
            report.expect("message_end 带 metadata", isinstance(end.get("metadata"), dict), str(end.get("metadata"))[:120])

        response = await post("/api/transfer/one/chat-messages", json={"query": query, "user": "smoke"}, headers=headers)
        events = parse_sse(response.text) if response.status_code == 200 else []
        cloud_end = _event(events, "message_end")
        report.expect(
            "云智 /api/transfer/one/chat-messages",
            response.status_code == 200 and cloud_end is not None and bool(cloud_end.get("answer")),
            f"status={response.status_code} events={[e.get('event') for e in events]}",
        )

        if check_idempotency:
            key = f"smoke-{uuid.uuid4().hex}"
            replay_headers = {**headers, "Idempotency-Key": key}
            payload = {"query": f"幂等冒烟 {uuid.uuid4().hex[:6]}", "user": "smoke"}
            first = parse_sse((await post("/v1/chat-messages", json=payload, headers=replay_headers)).text)
            second = parse_sse((await post("/v1/chat-messages", json=payload, headers=replay_headers)).text)
            report.expect(
                "幂等重放命中首次结果",
                _event(first, "message_end") == _event(second, "message_end") and _event(first, "message_end") is not None,
                f"first={_event(first, 'message_end')} second={_event(second, 'message_end')}",
            )

        auth = {"Api-Key": api_key, "Authorization": f"Bearer {token}"} if token else headers
        response = await get(
            "/api/transfer/one/chat-messages/conversations", params={"user": "smoke", "limit": 20}, headers=auth
        )
        body = response.json()
        report.expect(
            "云智会话分页 Envelope",
            response.status_code == 200
            and body.get("code") == 200
            and isinstance((body.get("data") or {}).get("records"), list)
            and isinstance((body.get("data") or {}).get("total"), int),
            str(body)[:200],
        )

        response = await post(
            "/api/open/dify/listConversationDirect",
            json={"appId": args.app_id, "userName": "smoke", "pageNum": 1, "pageSize": 20},
        )
        body = response.json()
        report.expect(
            "listConversationDirect Envelope",
            response.status_code == 200 and body.get("code") == 200 and isinstance((body.get("data") or {}).get("records"), list),
            str(body)[:200],
        )

        if conversation_id:
            response = await get(
                "/api/transfer/one/chat-messages/messages",
                params={"conversation_id": conversation_id, "limit": 20},
                headers=auth,
            )
            body = response.json()
            report.expect(
                "云智消息分页 Envelope",
                response.status_code == 200 and body.get("code") == 200 and len((body.get("data") or {}).get("records", [])) >= 1,
                str(body)[:200],
            )

        try:
            response = await post(
                "/v1/workflows/run", json={"inputs": {"query": "工作流冒烟"}, "user": "smoke"}, headers=headers
            )
            body = response.json() if response.status_code == 200 else {}
        except Exception as exc:  # noqa: BLE001
            body = {"error": f"{type(exc).__name__}: {exc}"}
        nested = (body.get("data") or {}).get("data") or {}
        report.expect(
            "工作流三重嵌套 Envelope",
            nested.get("status") == "succeeded" and isinstance(nested.get("outputs"), dict),
            str(body)[:200],
        )

    print()
    if report.skips:
        print(f"跳过 {len(report.skips)} 项：{', '.join(report.skips)}")
    if report.failures:
        print(f"失败 {len(report.failures)} 项：{', '.join(report.failures)}")
        return 1
    print("冒烟全部通过。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="agent 中台内网端到端冒烟")
    parser.add_argument("--base-url", default="", help="远端服务地址；留空则进程内启动 ASGI（读 .env）")
    parser.add_argument("--app-id", default="smoke-e2e", help="应用 app_id（存在则复用）")
    parser.add_argument("--api-key", default="", help="直接用存量应用的 api_key，跳过建应用")
    parser.add_argument("--tenant", default="", help="租户/区域 code，默认取 AP_DEFAULT_TENANT")
    parser.add_argument("--client-id", default="smoke", help="云智 oauth2 client_id")
    parser.add_argument("--timeout", type=float, default=120.0, help="单请求超时（秒）")
    parser.add_argument("--check-idempotency", action="store_true", help="远端模式下也校验幂等重放")
    args = parser.parse_args()
    try:
        return asyncio.run(run_smoke(args))
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] 冒烟执行中断  {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
