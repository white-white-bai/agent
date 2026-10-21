"""CI 入口：回放 Agent 轨迹并按标准工具路径打分；失败返回 1。"""
from __future__ import annotations

from agent_platform.agentapp.eval import main

if __name__ == "__main__":
    raise SystemExit(main())
