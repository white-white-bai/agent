"""批量录制 Agent 应用执行轨迹，输出可直接交给 eval_agent_traces.py 的 JSONL。"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import httpx

from agent_platform.agentapp.eval import parse_sse_events, trace_from_events


def _load_cases(path: str) -> list[dict[str, Any]]:
    text = Path(path).read_text(encoding="utf-8")
    if path.endswith(".jsonl"):
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    payload = json.loads(text)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("cases"), list):
        return payload["cases"]
    return [payload]


async def _record_one(
    client: httpx.AsyncClient,
    base_url: str,
    app_uuid: str,
    case: dict[str, Any],
    *,
    token: str,
    conversation_id: str,
) -> dict[str, Any]:
    case_id = str(case.get("id") or case.get("case_id") or "")
    if not case_id:
        raise ValueError("case 缺少 id")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    body = {
        "query": str(case.get("query") or ""),
        "inputs": case.get("inputs") or {},
        "conversation_id": str(case.get("conversation_id") or conversation_id or ""),
    }
    chunks: list[str] = []
    async with client.stream(
        "POST", f"{base_url.rstrip('/')}/admin/apps/{app_uuid}/agent/run", json=body, headers=headers
    ) as response:
        response.raise_for_status()
        async for chunk in response.aiter_text():
            chunks.append(chunk)
    events = parse_sse_events("".join(chunks))
    trace = trace_from_events(case_id, events)
    if trace.status == "completed" and not trace.answer:
        trace.status = "failed"
        trace.error = "SSE 未返回 final answer"
    return trace.to_dict()


async def _run(args: argparse.Namespace) -> int:
    cases = _load_cases(args.cases)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    async with httpx.AsyncClient(timeout=None) as client:
        for case in cases:
            trace = await _record_one(
                client,
                args.base_url,
                args.app_uuid,
                case,
                token=args.token,
                conversation_id=args.conversation_id,
            )
            await asyncio.to_thread(_append_trace, out, trace)
            written += 1
            print(f"[{written}/{len(cases)}] {trace['id']} {trace['status']} tools={trace['tool_calls']}")
    return 0


def _append_trace(out: Path, trace: dict[str, Any]) -> None:
    with out.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(trace, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="录制 Agent 应用轨迹为评测 JSONL")
    parser.add_argument("--base-url", default="http://127.0.0.1:8900")
    parser.add_argument("--app-uuid", required=True)
    parser.add_argument("--cases", required=True, help="JSONL/JSON，至少包含 id 与 query")
    parser.add_argument("--out", default="evals/recorded_traces.jsonl")
    parser.add_argument("--token", default="", help="管理端 Bearer token（开启鉴权时需要）")
    parser.add_argument("--conversation-id", default="", help="可选，固定会话 id（用于多轮/记忆评测）")
    return asyncio.run(_run(parser.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
