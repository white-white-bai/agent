"""智能体与提示词模板的定义解析（读 ap_agent / ap_prompt_template，合并节点级覆盖）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from agent_platform.core.db import session_scope
from agent_platform.domain.models import Agent, PromptTemplate
from agent_platform.graph.schema import AGENT_MODES, AgentConfig, ToolRef


@dataclass
class AgentSpec:
    code: str
    label: str = ""
    role: str = "custom"
    mode: str = "react"
    provider: str = ""
    system_prompt: str = ""
    prompt_template: str = ""
    cot: bool = False
    tools: list[ToolRef] = field(default_factory=list)
    retriever: dict[str, Any] = field(default_factory=dict)
    pipeline: list[str] = field(default_factory=list)
    max_steps: int = 6
    reflection_rounds: int = 2
    temperature: float = 0.3
    max_tokens: int | None = None


@dataclass
class PromptSpec:
    code: str = ""
    system_prompt: str = ""
    examples: list[dict[str, str]] = field(default_factory=list)
    cot_hint: str = ""


def _row_visible(row_tenant: str, tenant_code: str) -> bool:
    return not (row_tenant and tenant_code and row_tenant != tenant_code)


def load_agent(code: str, tenant_code: str = "", default_max_steps: int = 6) -> AgentSpec:
    with session_scope() as session:
        row = session.scalar(select(Agent).where(Agent.code == code, Agent.is_deleted == 0))
    if row is None or not _row_visible(row.tenant_code, tenant_code):
        raise ValueError(f"未找到智能体定义: {code or '(未指定)'}")
    return AgentSpec(
        code=row.code,
        label=row.label or row.code,
        role=row.role or "custom",
        mode=row.mode if row.mode in AGENT_MODES else "react",
        provider=row.provider or "",
        system_prompt=row.system_prompt or "",
        prompt_template=row.prompt_template or "",
        cot=bool(row.cot),
        tools=[ToolRef.model_validate(item) for item in (row.tools or []) if isinstance(item, dict)],
        retriever=dict(row.retriever or {}),
        pipeline=[str(item) for item in (row.pipeline or [])],
        max_steps=int(row.max_steps or default_max_steps),
        reflection_rounds=int(row.reflection_rounds or 2),
        temperature=float(row.temperature if row.temperature is not None else 0.3),
        max_tokens=row.max_tokens,
    )


def load_template(code: str, tenant_code: str = "") -> PromptSpec | None:
    if not code:
        return None
    with session_scope() as session:
        row = session.scalar(
            select(PromptTemplate).where(PromptTemplate.code == code, PromptTemplate.is_deleted == 0)
        )
    if row is None or not _row_visible(row.tenant_code, tenant_code):
        return None
    return PromptSpec(
        code=row.code,
        system_prompt=row.system_prompt or "",
        examples=[item for item in (row.examples or []) if isinstance(item, dict)],
        cot_hint=row.cot_hint or "",
    )


def apply_overrides(spec: AgentSpec, config: AgentConfig) -> AgentSpec:
    """节点级覆盖：模式 / 工具 / 流水线成员 / CoT / 提示词模板 / 采样参数。"""
    if config.mode:
        spec.mode = config.mode
    if config.tools:
        spec.tools = list(config.tools)
    if config.pipeline:
        spec.pipeline = list(config.pipeline)
    if config.cot is not None:
        spec.cot = bool(config.cot)
    if config.prompt_template:
        spec.prompt_template = config.prompt_template
    if config.temperature is not None:
        spec.temperature = config.temperature
    if config.max_tokens is not None:
        spec.max_tokens = config.max_tokens
    if config.max_steps:
        spec.max_steps = config.max_steps
    if config.reflection_rounds:
        spec.reflection_rounds = config.reflection_rounds
    return spec
