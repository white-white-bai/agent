"""Agent 应用定义（自主 agent 的配置文档，对标 Dify「Agent 应用」）。"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from agent_platform.graph.schema import KnowledgeConfig

SCHEMA_VERSION = "1.0"

HITL_POLICIES = ("off", "before_all_tools", "before_listed")


class AgentToolRef(BaseModel):
    """Agent 可用工具：引用 ap_tool 声明（name+server）。"""

    name: str
    server: str = ""
    hitl: bool = False  # 该工具是否逐次人工审批（policy=before_listed 时生效）


class AgentMemoryConfig(BaseModel):
    """长期记忆：消息由 checkpointer 跨轮持久；window 控制送模型的裁剪条数。"""

    window: int = 10
    summary_enabled: bool = False
    provider: str = ""


class AgentHitlConfig(BaseModel):
    """Human-in-the-loop：命中策略的工具调用前 interrupt 等待人工批准。"""

    enabled: bool = False
    policy: Literal["off", "before_all_tools", "before_listed"] = "off"
    tools: list[str] = Field(default_factory=list)
    prompt: str = "即将执行工具 {tool}，参数：{args}。是否批准？"


class AgentHandoff(BaseModel):
    """子 Agent 委派的结构化交接契约。"""

    from_agent: str
    to_agent: str
    status: Literal["ok", "error"]
    answer: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)


class AgentAppDef(BaseModel):
    """自主 agent 的完整定义：指令 + 模型 + 工具 + 知识 + 记忆 + 规划/反思 + 子 agent + HITL。"""

    schema_version: str = SCHEMA_VERSION
    name: str = ""
    instructions: str = ""
    provider: str = ""
    temperature: float = 0.3
    max_tokens: int | None = None
    opening_statement: str = ""
    tools: list[AgentToolRef] = Field(default_factory=list)
    # 动态发现工具的 MCP Server 名单（ap_mcp_server.name / AP_TOOL_SERVERS 的 key）
    mcp_servers: list[str] = Field(default_factory=list)
    knowledge: KnowledgeConfig = Field(default_factory=KnowledgeConfig)
    knowledge_as_tool: bool = True
    browser: bool = False
    browser_allowed_hosts: str = ""
    browser_allow_private: bool = False
    browser_storage_state: str = ""
    memory: AgentMemoryConfig = Field(default_factory=AgentMemoryConfig)
    planning: bool = False
    reflection_rounds: int = 0
    max_steps: int = 6
    sub_agents: list[str] = Field(default_factory=list)  # ap_agent.code
    hitl: AgentHitlConfig = Field(default_factory=AgentHitlConfig)

    def to_document(self) -> dict:
        return self.model_dump(mode="json")
