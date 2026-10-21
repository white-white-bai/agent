"""Agent 执行入口：解析定义与覆盖 → 组装提示词 → 按工作模式执行 → 归一输出。"""
from __future__ import annotations

from typing import Any

from agent_platform.core.config import Settings
from agent_platform.engine.agents import modes as modes_mod
from agent_platform.engine.agents.prompts import build_system_prompt, split_reasoning
from agent_platform.engine.agents.registry import apply_overrides, load_agent, load_template
from agent_platform.engine.expr import evaluate, render
from agent_platform.graph.schema import AgentConfig
from agent_platform.tools.mcp_bridge import build_tool_caller, build_toolbox


def build_agent_invoker(settings: Settings, toolbox: Any | None = None):
    caller = build_tool_caller(settings)
    toolbox = toolbox or build_toolbox(settings)

    async def invoke(
        config: AgentConfig, variables: dict[str, Any], ctx: Any, tenant_code: str = ""
    ) -> dict[str, Any]:
        spec = apply_overrides(load_agent(config.agent, tenant_code, settings.agent_max_steps), config)
        system = build_system_prompt(spec, load_template(spec.prompt_template, tenant_code))

        bound = dict(variables)
        for item in config.inputs:
            bound[item.name] = evaluate(item.expression, variables)
        query = render(config.query, bound)

        mc = modes_mod.ModeContext(
            llm=ctx.llm,
            caller=caller,
            retriever=ctx.retriever,
            tenant_code=tenant_code,
            toolbox=toolbox,
            tool_result_max_chars=settings.agent_tool_result_max_chars,
            memory_var=settings.user_memory_inject_var,
            prompt_guard_enabled=settings.prompt_guard_enabled,
            prompt_guard_max_chars=settings.prompt_guard_max_chars,
        )
        result = await modes_mod.run_spec(spec, mc, bound, query, system)
        answer, reasoning = split_reasoning(str(result.get("answer") or ""))
        return {
            "answer": answer,
            "reasoning": reasoning,
            "steps": result.get("steps") or [],
            "sources": result.get("sources") or [],
            "reflection": result.get("reflection") or [],
            "route": result.get("route") or "",
            "mode": spec.mode,
            "agent": spec.code,
        }

    return invoke
