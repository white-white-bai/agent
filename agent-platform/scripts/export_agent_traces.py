"""把 ap_agent_trace 中的生产轨迹导出为 eval_agent_traces.py 可读取的 JSONL。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_platform.core.agent_trace import export_traces


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导出 Agent 生产轨迹为评测轨迹")
    parser.add_argument("--tenant-code", required=True)
    parser.add_argument("--app-uuid", default="")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--status", default="")
    parser.add_argument("--out", default="evals/traces.jsonl")
    args = parser.parse_args(argv)

    traces = export_traces(
        args.tenant_code,
        app_uuid=args.app_uuid,
        days=args.days,
        limit=args.limit,
        status=args.status,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for trace in traces:
            handle.write(json.dumps(trace, ensure_ascii=False) + "\n")
    print(f"导出 {len(traces)} 条轨迹 -> {out}")
    return 0 if traces else 1


if __name__ == "__main__":
    raise SystemExit(main())
