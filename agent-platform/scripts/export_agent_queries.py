"""从会话消息导出真实用户 query，供 record_agent_trace.py 批量录制轨迹。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from agent_platform.core.db import session_scope
from agent_platform.domain.models import Conversation, Message


def export_queries(
    tenant_code: str,
    *,
    app_uuid: str = "",
    limit: int = 100,
) -> list[dict[str, Any]]:
    size = max(int(limit or 100), 1)
    with session_scope() as session:
        stmt = (
            select(Message.query)
            .join(Conversation, Conversation.uuid == Message.conversation_uuid)
            .where(
                Conversation.tenant_code == tenant_code,
                Message.role == "user",
                Message.query != "",
            )
        )
        if app_uuid:
            stmt = stmt.where(Conversation.app_uuid == app_uuid)
        stmt = stmt.order_by(Message.id.desc()).limit(size * 5)
        seen: set[str] = set()
        queries: list[str] = []
        for query in session.scalars(stmt).all():
            text = str(query or "").strip()
            if text and text not in seen:
                seen.add(text)
                queries.append(text)
                if len(queries) >= size:
                    break
    return [{"id": f"q-{index:04d}", "query": text} for index, text in enumerate(queries, start=1)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从 ap_message 导出真实用户 query")
    parser.add_argument("--tenant-code", required=True)
    parser.add_argument("--app-uuid", default="")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--out", default="evals/queries.jsonl")
    args = parser.parse_args(argv)

    cases = export_queries(args.tenant_code, app_uuid=args.app_uuid, limit=args.limit)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case, ensure_ascii=False) + "\n")
    print(f"导出 {len(cases)} 条 query -> {out}")
    return 0 if cases else 1


if __name__ == "__main__":
    raise SystemExit(main())
