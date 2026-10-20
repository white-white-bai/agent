"""请求/响应 schema（兼容云智 / Dify + 中台管理端）。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatMessagesRequest(BaseModel):
    query: str = ""
    inputs: dict[str, Any] = Field(default_factory=dict)
    user: str = ""
    conversation_id: str = ""
    response_mode: str = "streaming"
    files: list[dict[str, Any]] = Field(default_factory=list)
    idempotency_key: str = ""


class OpeningInfo(BaseModel):
    opening_statement: str = ""
    opening_questions: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- 云智 / Dify 兼容

class TokenRequest(BaseModel):
    grant_type: str = "client_credentials"
    client_id: str = ""
    client_secret: str = ""


class FeedbackRequest(BaseModel):
    rating: str | None = None
    user: str = ""


class RenameRequest(BaseModel):
    name: str = ""
    auto_generate: bool = False
    user: str = ""


class WorkflowRunRequest(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    response_mode: str = "blocking"
    user: str = ""


class DirectQueryRequest(BaseModel):
    """云智直读库分页查询（兼容 pageNum/current、pageSize/size 两种命名）。"""

    appId: str = ""
    app_id: str = ""
    conversationId: str = ""
    conversation_id: str = ""
    userName: str = ""
    user_name: str = ""
    messageId: str = ""
    message_id: str = ""
    pageNum: int = 1
    pageSize: int = 20
    current: int = 0
    size: int = 0
    model_config = {"extra": "allow"}

    @property
    def page(self) -> int:
        return self.current or self.pageNum or 1

    @property
    def page_size(self) -> int:
        return self.size or self.pageSize or 20

    @property
    def app_identifier(self) -> str:
        return self.appId or self.app_id

    @property
    def conversation_identifier(self) -> str:
        return self.conversationId or self.conversation_id

    @property
    def user_identifier(self) -> str:
        return self.userName or self.user_name

    @property
    def message_identifier(self) -> str:
        return self.messageId or self.message_id


# --------------------------------------------------------------------------- 中台管理端

class AppCreateRequest(BaseModel):
    tenant_code: str = ""
    app_id: str = ""
    api_key: str = ""
    app_name: str = ""
    app_type: str = "chat"
    icon: str = ""
    opening_statement: str = ""
    suggested_questions: list[str] = Field(default_factory=list)
    app_info: dict[str, Any] = Field(default_factory=dict)


class AppUpdateRequest(BaseModel):
    app_name: str | None = None
    app_type: str | None = None
    icon: str | None = None
    opening_statement: str | None = None
    suggested_questions: list[str] | None = None
    app_info: dict[str, Any] | None = None
    api_key: str | None = None
    tenant_code: str | None = None


class GraphDraftRequest(BaseModel):
    definition: dict[str, Any] = Field(default_factory=dict)


class GraphPublishRequest(BaseModel):
    note: str = ""
    created_by: str = ""
    definition: dict[str, Any] | None = None


class GraphRollbackRequest(BaseModel):
    version: int


class GraphImportRequest(BaseModel):
    dsl: dict[str, Any] | None = None
    content: str = ""
    llm_provider: str = ""
    retriever: str = "builtin"
    name: str = ""
    save: bool = True


class RunNodeRequest(BaseModel):
    node_id: str
    definition: dict[str, Any] | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)


class RunGraphRequest(BaseModel):
    definition: dict[str, Any] | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    thread_id: str = ""


class ResumeRunRequest(BaseModel):
    interrupt_id: str = ""
    action: str = "approve"
    payload: dict[str, Any] = Field(default_factory=dict)
    definition: dict[str, Any] | None = None


class ToolParamSpec(BaseModel):
    name: str
    type: str = "string"
    required: bool = False
    enum: list[str] = Field(default_factory=list)
    description: str = ""


class ToolUpsertRequest(BaseModel):
    tenant_code: str = ""
    name: str = ""
    label: str = ""
    category: str = ""
    server: str = ""
    kind: str = "http"
    http_method: str = "POST"
    http_path: str = ""
    params: list[ToolParamSpec] = Field(default_factory=list)
    retry_attempts: int | None = None
    retry_backoff_seconds: float | None = None
    fallback: dict[str, Any] = Field(default_factory=dict)


class ToolTestRequest(BaseModel):
    args: dict[str, Any] = Field(default_factory=dict)
    tenant_code: str = ""


class PromptExample(BaseModel):
    input: str = ""
    output: str = ""


class PromptUpsertRequest(BaseModel):
    tenant_code: str = ""
    code: str = ""
    label: str = ""
    system_prompt: str = ""
    examples: list[PromptExample] = Field(default_factory=list)
    cot_hint: str = ""


class AgentUpsertRequest(BaseModel):
    tenant_code: str = ""
    code: str = ""
    label: str = ""
    role: str = "custom"
    mode: str = "react"
    provider: str = ""
    system_prompt: str = ""
    prompt_template: str = ""
    cot: bool = False
    tools: list[dict[str, Any]] = Field(default_factory=list)
    retriever: dict[str, Any] = Field(default_factory=dict)
    pipeline: list[str] = Field(default_factory=list)
    max_steps: int = 6
    reflection_rounds: int = 2
    temperature: float = 0.3
    max_tokens: int | None = None


class SensitiveWordCreateRequest(BaseModel):
    tenant_code: str = ""
    word: str


class McpServerCreateRequest(BaseModel):
    tenant_code: str = ""
    name: str
    url: str = ""
    kind: str = "mcp"
    headers: dict[str, str] = Field(default_factory=dict)


class DatasetUpsertRequest(BaseModel):
    tenant_code: str = ""
    name: str = ""
    description: str = ""
    embedding_model: str = ""
    index_method: str = "high_quality"
    chunk_config: dict[str, Any] = Field(default_factory=dict)
    retrieval: dict[str, Any] = Field(default_factory=dict)


class DocumentTextRequest(BaseModel):
    tenant_code: str = ""
    name: str = ""
    content: str = ""
    chunk_config: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SegmentUpdateRequest(BaseModel):
    content: str | None = None
    enabled: int | None = None


class RetrieveRequest(BaseModel):
    tenant_code: str = ""
    query: str = ""
    top_k: int | None = None
    score_threshold: float | None = None


class UserMemoryUpsertRequest(BaseModel):
    tenant_code: str = ""
    app_uuid: str = ""
    user_key: str = ""
    user_name: str = ""
    kind: str = "fact"
    content: str = ""
    importance: float = 0.5
    enabled: bool = True
    expires_at: str = ""


class UserMemoryRecallRequest(BaseModel):
    tenant_code: str = ""
    app_uuid: str = ""
    user_key: str = ""
    query: str = ""
    top_k: int | None = None
    score_threshold: float | None = None


class UserMemoryPurgeRequest(BaseModel):
    tenant_code: str = ""
    app_uuid: str = ""
    user_key: str = ""


# --------------------------------------------------------------------------- 管理端账号

class LoginRequest(BaseModel):
    username: str
    password: str


class UserCreateRequest(BaseModel):
    username: str
    password: str
    role_code: str = "viewer"
    tenant_code: str = ""
    display_name: str = ""


class UserUpdateRequest(BaseModel):
    role_code: str | None = None
    tenant_code: str | None = None
    display_name: str | None = None
    is_active: int | None = None
    password: str = ""


class RoleCreateRequest(BaseModel):
    code: str
    name: str = ""
    permissions: list[str] = Field(default_factory=list)
