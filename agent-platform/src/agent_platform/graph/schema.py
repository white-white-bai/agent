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
    PARAMETER_EXTRACTOR = "parameter-extractor"
    TEMPLATE_TRANSFORM = "template-transform"
    HTTP_REQUEST = "http-request"
    QUESTION_CLASSIFIER = "question-classifier"
    VARIABLE_ASSIGNER = "variable-assigner"
    LIST_OPERATOR = "list-operator"
    AGENT = "agent"


class Position(BaseModel):
    x: float = 0
    y: float = 0


class StartConfig(BaseModel):
    pass


class EndConfig(BaseModel):
    outputs: dict[str, str] = Field(default_factory=dict)


class LLMConfig(BaseModel):
    # provider 为 AP_LLM_MODELS 里的模型条目 key；留空用清单第一个
    provider: str = ""
    # 知识上下文（裸表达式，如 knowledge3）；非空时把该变量拼进提示词
    context: str = ""
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
    # 检索流水线覆盖项：None = 用全局配置（AP_RETRIEVAL_* / AP_RERANK_*）
    coarse_top_k: int | None = None
    hybrid: bool | None = None
    rerank: bool | None = None
    # 检索模式：None = 用知识库配置（其次全局）。vector/fulltext/hybrid
    mode: Literal["vector", "fulltext", "hybrid"] | None = None


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
    # 单个工具失败时的链路策略：raise 直接中断（默认），skip 跳过继续
    on_error: Literal["raise", "skip"] = "raise"


class ToolConfig(BaseModel):
    tools: list[ToolRef] = Field(default_factory=list)
    output_var: str = "tool_result"


class AggregateConfig(BaseModel):
    variables: list[str] = Field(default_factory=list)
    output_var: str = "aggregated"


class AnswerConfig(BaseModel):
    template: str = "{{ text }}"
    output_var: str = "answer"


class ExtractorParameter(BaseModel):
    """参数提取器的单个输出参数定义。"""

    name: str
    type: str = "string"
    description: str = ""
    required: bool = False
    options: list[str] = Field(default_factory=list)

    @field_validator("required", mode="before")
    @classmethod
    def _coerce_required(cls, value: Any) -> bool:
        # 前端 rows 表单可能传字符串，bool("false") is True 的坑需在此挡掉
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes", "on")
        return bool(value)


class ParameterExtractorConfig(BaseModel):
    """参数提取器配置：LLM 结构化提取，输出按参数名平铺（含 __is_success / __reason）。"""

    provider: str = ""
    query: str = "{{ query }}"
    instruction: str = ""
    parameters: list[ExtractorParameter] = Field(default_factory=list)
    temperature: float = 0.7
    max_tokens: int | None = None
    output_var: str = "extracted"


class TemplateTransformConfig(BaseModel):
    """模板转换配置：本地变量名绑定 + Jinja2 模板渲染，输出固定为字符串。"""

    variables: list[CodeInput] = Field(default_factory=list)
    template: str = ""
    output_var: str = "output"


# Agent 支持的 7 种工作模式
AGENT_MODES = (
    "react",
    "plan_execute",
    "reflection",
    "supervisor",
    "pipeline",
    "agent_as_tool",
    "deep_search",
)


class AgentConfig(BaseModel):
    """智能体节点：引用 ap_agent 定义，可逐项覆盖。"""

    agent: str = ""
    mode: str = ""  # 空 = 用 agent 定义里的模式
    query: str = "{{ query }}"
    inputs: list[CodeInput] = Field(default_factory=list)
    tools: list[ToolRef] = Field(default_factory=list)
    pipeline: list[str] = Field(default_factory=list)
    cot: bool | None = None
    prompt_template: str = ""
    max_steps: int = 6
    reflection_rounds: int = 2
    temperature: float | None = None
    max_tokens: int | None = None
    output_var: str = "agent_result"

    @field_validator("cot", mode="before")
    @classmethod
    def _coerce_cot(cls, value: Any) -> Any:
        # 前端下拉可能传 "true"/"false"/""；空串表示「用智能体定义里的设置」
        if isinstance(value, str):
            text = value.strip().lower()
            if not text:
                return None
            return text in ("true", "1", "yes", "on")
        return value


class HttpRequestConfig(BaseModel):
    """HTTP 请求：url/headers/params/body 支持模板，输出 {body, status_code, headers}。"""

    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"] = "GET"
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    params: dict[str, str] = Field(default_factory=dict)
    body_type: Literal["none", "json", "text"] = "none"
    body: str = ""
    timeout: int = 30
    output_var: str = "http"

    @field_validator("method", mode="before")
    @classmethod
    def _normalize_method(cls, value: Any) -> Any:
        return value.upper() if isinstance(value, str) else value


class ClassifierClass(BaseModel):
    id: str
    name: str


class QuestionClassifierConfig(BaseModel):
    """问题分类器：LLM 判定所属类别，类别 id 走 state['route'] 驱动分支。"""

    provider: str = ""
    query: str = "{{ query }}"
    classes: list[ClassifierClass] = Field(default_factory=list)
    instruction: str = ""
    temperature: float = 0.0
    max_tokens: int | None = None
    output_var: str = "class_name"


class AssignItem(BaseModel):
    name: str
    expression: str


class VariableAssignerConfig(BaseModel):
    """变量赋值：对每个 item 求值后写入同名变量。"""

    items: list[AssignItem] = Field(default_factory=list)


class ListOperatorConfig(BaseModel):
    """数组操作：取首/尾/下标/截取/筛选/排序/长度。"""

    variable: str = ""
    operation: Literal["first", "last", "at", "limit", "filter", "sort", "size"] = "first"
    index: int = 0
    count: int = 3
    expression: str = ""
    desc: bool = False
    output_var: str = "list_result"


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
    NodeType.PARAMETER_EXTRACTOR: ParameterExtractorConfig,
    NodeType.TEMPLATE_TRANSFORM: TemplateTransformConfig,
    NodeType.HTTP_REQUEST: HttpRequestConfig,
    NodeType.QUESTION_CLASSIFIER: QuestionClassifierConfig,
    NodeType.VARIABLE_ASSIGNER: VariableAssignerConfig,
    NodeType.LIST_OPERATOR: ListOperatorConfig,
    NodeType.AGENT: AgentConfig,
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
