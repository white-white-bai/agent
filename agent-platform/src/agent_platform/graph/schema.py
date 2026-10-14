"""图定义 schema（自建，基于 LangGraph 状态图；JSON document 整存）。"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

SCHEMA_VERSION = "1.0"


class VarType(str, Enum):
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    OBJECT = "object"
    ARRAY = "array"
    FILE = "file"


class VariableDef(BaseModel):
    name: str
    type: VarType = VarType.STRING
    required: bool = False
    default: Any = None
    description: str = ""


class NodeType(str, Enum):
    START = "start"
    END = "end"
    LLM = "llm"
    KNOWLEDGE = "knowledge"
    CONDITION = "condition"
    CODE = "code"
    TOOL = "tool"
    AGGREGATE = "aggregate"
    ANSWER = "answer"


class Position(BaseModel):
    x: float = 0
    y: float = 0


class StartConfig(BaseModel):
    pass


class EndConfig(BaseModel):
    outputs: dict[str, str] = Field(default_factory=dict)


class LLMConfig(BaseModel):
    provider: Literal["cloud_gateway", "openai"] = "cloud_gateway"
    model: str = ""
    system_prompt: str = ""
    user_prompt: str = "{{ query }}"
    temperature: float = 0.7
    max_tokens: int | None = None
    output_var: str = "text"


class KnowledgeConfig(BaseModel):
    retriever: Literal["builtin", "light_rag", "knowflow", "knowledge_graph"] = "builtin"
    dataset_ids: list[str] = Field(default_factory=list)
    query: str = "{{ query }}"
    top_k: int = 5
    score_threshold: float | None = None
    output_var: str = "chunks"


class ConditionBranch(BaseModel):
    id: str
    expression: str


class ConditionConfig(BaseModel):
    branches: list[ConditionBranch] = Field(default_factory=list)
    fallback_id: str = ""


class CodeInput(BaseModel):
    name: str
    expression: str


class CodeConfig(BaseModel):
    code: str = ""
    inputs: list[CodeInput] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    timeout_ms: int = 3000


class ToolRef(BaseModel):
    name: str
    server: str = ""
    args: dict[str, Any] = Field(default_factory=dict)


class ToolConfig(BaseModel):
    tools: list[ToolRef] = Field(default_factory=list)
    output_var: str = "tool_result"


class AggregateConfig(BaseModel):
    variables: list[str] = Field(default_factory=list)
    output_var: str = "aggregated"


class AnswerConfig(BaseModel):
    template: str = "{{ text }}"
    output_var: str = "answer"


CONFIG_MODELS: dict[NodeType, type[BaseModel]] = {
    NodeType.START: StartConfig,
    NodeType.END: EndConfig,
    NodeType.LLM: LLMConfig,
    NodeType.KNOWLEDGE: KnowledgeConfig,
    NodeType.CONDITION: ConditionConfig,
    NodeType.CODE: CodeConfig,
    NodeType.TOOL: ToolConfig,
    NodeType.AGGREGATE: AggregateConfig,
    NodeType.ANSWER: AnswerConfig,
}


class NodeDef(BaseModel):
    id: str
    type: NodeType
    title: str = ""
    position: Position = Field(default_factory=Position)
    config: dict[str, Any] = Field(default_factory=dict)

    def typed_config(self) -> BaseModel:
        model = CONFIG_MODELS[self.type]
        return model.model_validate(self.config)


class EdgeDef(BaseModel):
    id: str = ""
    source: str
    target: str
    source_handle: str = ""


class GraphDef(BaseModel):
    schema_version: str = SCHEMA_VERSION
    app_id: str = ""
    name: str = ""
    inputs: list[VariableDef] = Field(default_factory=list)
    global_variables: dict[str, Any] = Field(default_factory=dict)
    nodes: list[NodeDef] = Field(default_factory=list)
    edges: list[EdgeDef] = Field(default_factory=list)

    @field_validator("nodes")
    @classmethod
    def _unique_node_ids(cls, nodes: list[NodeDef]) -> list[NodeDef]:
        ids = [n.id for n in nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("节点 id 重复")
        for node in nodes:
            node.typed_config()
        return nodes

    def node(self, node_id: str) -> NodeDef | None:
        return next((n for n in self.nodes if n.id == node_id), None)

    def start_node(self) -> NodeDef | None:
        return next((n for n in self.nodes if n.type == NodeType.START), None)

    def outgoing(self, node_id: str) -> list[EdgeDef]:
        return [e for e in self.edges if e.source == node_id]
