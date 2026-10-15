"""Dify DSL 导入 CLI：`python -m agent_platform.importer app.yml [-o out.json]`。"""
from __future__ import annotations

import argparse
import json
import sys

from agent_platform.importer import DifyImportError, convert, load_dsl


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agent_platform.importer", description="Dify DSL → 中台图定义")
    parser.add_argument("dsl", help="Dify 导出的 DSL 文件（.json / .yml / .yaml）")
    parser.add_argument("-o", "--output", default="", help="输出文件；缺省打印到标准输出")
    parser.add_argument("--app-id", default="", help="覆盖 app_id（缺省取 DSL 的 app.id）")
    parser.add_argument("--name", default="", help="覆盖应用名（缺省取 DSL 的 app.name）")
    parser.add_argument("--llm-provider", default="", help="AP_LLM_MODELS 的模型条目 key（缺省用清单第一个）")
    parser.add_argument(
        "--retriever",
        default="builtin",
        choices=["builtin", "light_rag", "knowflow", "knowledge_graph"],
    )
    args = parser.parse_args(argv)

    try:
        result = convert(
            load_dsl(args.dsl),
            app_id=args.app_id,
            name=args.name,
            llm_provider=args.llm_provider,
            retriever=args.retriever,
        )
    except DifyImportError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1

    text = json.dumps(result.definition, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.write("\n")
    else:
        print(text)
    for item in result.warnings:
        print(f"[warn] {item}", file=sys.stderr)
    print(
        f"[ok] 节点 {result.stats['converted']}/{result.stats['total']}，降级 {result.stats['degraded']}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
