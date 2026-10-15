"""智能体编排：定义解析、提示词组装、7 种工作模式与执行入口。"""
from __future__ import annotations

from agent_platform.engine.agents.registry import AgentSpec, PromptSpec, apply_overrides, load_agent, load_template
from agent_platform.engine.agents.runner import build_agent_invoker

__all__ = [
    "AgentSpec",
    "PromptSpec",
    "apply_overrides",
    "build_agent_invoker",
    "load_agent",
    "load_template",
]
