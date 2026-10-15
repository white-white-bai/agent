from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from agent_platform.core.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Tenant(Base):
    __tablename__ = "ap_tenant"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class App(Base):
    __tablename__ = "ap_app"
    __table_args__ = (UniqueConstraint("app_id", name="uk_ap_app_app_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    tenant_code: Mapped[str] = mapped_column(String(64), index=True)
    app_id: Mapped[str] = mapped_column(String(64), index=True)
    api_key: Mapped[str] = mapped_column(String(128))
    app_name: Mapped[str] = mapped_column(String(128), default="")
    app_type: Mapped[str] = mapped_column(String(32), default="chat")
    icon: Mapped[str] = mapped_column(String(512), default="")
    opening_statement: Mapped[str] = mapped_column(Text, default="")
    suggested_questions: Mapped[list] = mapped_column(JSON, default=list)
    app_info: Mapped[dict] = mapped_column(JSON, default=dict)
    is_deleted: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class Graph(Base):
    __tablename__ = "ap_graph"
    __table_args__ = (UniqueConstraint("app_uuid", name="uk_ap_graph_app_uuid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    tenant_code: Mapped[str] = mapped_column(String(64), index=True)
    app_uuid: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    published_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    draft: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class GraphVersion(Base):
    __tablename__ = "ap_graph_version"
    __table_args__ = (UniqueConstraint("graph_uuid", "version", name="uk_ap_graph_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    graph_uuid: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer)
    definition: Mapped[dict] = mapped_column(JSON)
    note: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Conversation(Base):
    __tablename__ = "ap_conversation"
    __table_args__ = (UniqueConstraint("conversation_id", name="uk_ap_conversation_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    tenant_code: Mapped[str] = mapped_column(String(64), index=True)
    app_uuid: Mapped[str] = mapped_column(String(64), index=True)
    conversation_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(64), default="")
    user_name: Mapped[str] = mapped_column(String(128), default="")
    name: Mapped[str] = mapped_column(String(255), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    summary_upto_id: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class Message(Base):
    __tablename__ = "ap_message"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    conversation_uuid: Mapped[str] = mapped_column(String(64), index=True)
    message_id: Mapped[str] = mapped_column(String(64), index=True)
    parent_message_id: Mapped[str] = mapped_column(String(64), default="")
    role: Mapped[str] = mapped_column(String(16), default="user")
    query: Mapped[str] = mapped_column(Text, default="")
    answer: Mapped[str] = mapped_column(Text, default="")
    answer_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    feedback: Mapped[str | None] = mapped_column(String(16), nullable=True)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_seconds: Mapped[float] = mapped_column(default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class SensitiveWord(Base):
    __tablename__ = "ap_sensitive_word"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_code: Mapped[str] = mapped_column(String(64), index=True, default="")
    word: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Checkpoint(Base):
    __tablename__ = "ap_checkpoint"
    __table_args__ = (UniqueConstraint("thread_id", "checkpoint_ns", "checkpoint_id", name="uk_ap_checkpoint"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(String(128), index=True)
    checkpoint_ns: Mapped[str] = mapped_column(String(128), default="")
    checkpoint_id: Mapped[str] = mapped_column(String(128), index=True)
    parent_checkpoint_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    type: Mapped[str] = mapped_column(String(32))
    checkpoint: Mapped[bytes] = mapped_column(LargeBinary)
    metadata_type: Mapped[str] = mapped_column(String(32))
    metadata_blob: Mapped[bytes] = mapped_column("metadata", LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Document(Base):
    __tablename__ = "ap_document"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    tenant_code: Mapped[str] = mapped_column(String(64), index=True)
    dataset_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    title: Mapped[str] = mapped_column(String(255), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    embedding: Mapped[list] = mapped_column(JSON, default=list)
    doc_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    is_deleted: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class McpServer(Base):
    __tablename__ = "ap_mcp_server"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    tenant_code: Mapped[str] = mapped_column(String(64), index=True, default="")
    name: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="mcp")
    url: Mapped[str] = mapped_column(String(512), default="")
    headers: Mapped[dict] = mapped_column(JSON, default=dict)
    is_deleted: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class CheckpointWrite(Base):
    __tablename__ = "ap_checkpoint_write"
    __table_args__ = (
        UniqueConstraint("thread_id", "checkpoint_ns", "checkpoint_id", "task_id", "idx", name="uk_ap_checkpoint_write"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(String(128), index=True)
    checkpoint_ns: Mapped[str] = mapped_column(String(128), default="")
    checkpoint_id: Mapped[str] = mapped_column(String(128), index=True)
    task_id: Mapped[str] = mapped_column(String(128))
    idx: Mapped[int] = mapped_column(Integer)
    channel: Mapped[str] = mapped_column(String(128))
    type: Mapped[str] = mapped_column(String(32))
    value: Mapped[bytes] = mapped_column(LargeBinary)


class AdminRole(Base):
    __tablename__ = "ap_admin_role"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    permissions: Mapped[list] = mapped_column(JSON, default=list)
    is_builtin: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class AdminUser(Base):
    __tablename__ = "ap_admin_user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    salt: Mapped[str] = mapped_column(String(64))
    display_name: Mapped[str] = mapped_column(String(128), default="")
    role_code: Mapped[str] = mapped_column(String(64), index=True, default="viewer")
    tenant_code: Mapped[str] = mapped_column(String(64), index=True, default="")
    is_active: Mapped[int] = mapped_column(Integer, default=1)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class MetricEvent(Base):
    __tablename__ = "ap_metric_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_code: Mapped[str] = mapped_column(String(64), index=True, default="")
    app_uuid: Mapped[str] = mapped_column(String(64), index=True, default="")
    kind: Mapped[str] = mapped_column(String(32), index=True, default="error")
    detail: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Tool(Base):
    """生产级工具声明：参数 schema + 端点 + 重试/兜底策略。"""

    __tablename__ = "ap_tool"
    __table_args__ = (UniqueConstraint("name", name="uk_ap_tool_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    tenant_code: Mapped[str] = mapped_column(String(64), index=True, default="")
    name: Mapped[str] = mapped_column(String(128), index=True)
    label: Mapped[str] = mapped_column(String(128), default="")
    category: Mapped[str] = mapped_column(String(32), default="")
    server: Mapped[str] = mapped_column(String(64), default="")
    kind: Mapped[str] = mapped_column(String(16), default="http")
    http_method: Mapped[str] = mapped_column(String(8), default="POST")
    http_path: Mapped[str] = mapped_column(String(512), default="")
    params: Mapped[list] = mapped_column(JSON, default=list)
    retry_attempts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retry_backoff_seconds: Mapped[float | None] = mapped_column(nullable=True)
    fallback: Mapped[dict] = mapped_column(JSON, default=dict)
    is_builtin: Mapped[int] = mapped_column(Integer, default=0)
    is_deleted: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class PromptTemplate(Base):
    """少样本提示词模板：system 骨架 + 示例对 + 思维链提示。"""

    __tablename__ = "ap_prompt_template"
    __table_args__ = (UniqueConstraint("code", name="uk_ap_prompt_template_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    tenant_code: Mapped[str] = mapped_column(String(64), index=True, default="")
    code: Mapped[str] = mapped_column(String(64), index=True)
    label: Mapped[str] = mapped_column(String(128), default="")
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    examples: Mapped[list] = mapped_column(JSON, default=list)
    cot_hint: Mapped[str] = mapped_column(Text, default="")
    is_builtin: Mapped[int] = mapped_column(Integer, default=0)
    is_deleted: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class Agent(Base):
    """智能体定义：角色 + 工作模式 + 模型/工具/检索 + 提示词与思维链。"""

    __tablename__ = "ap_agent"
    __table_args__ = (UniqueConstraint("code", name="uk_ap_agent_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    tenant_code: Mapped[str] = mapped_column(String(64), index=True, default="")
    code: Mapped[str] = mapped_column(String(64), index=True)
    label: Mapped[str] = mapped_column(String(128), default="")
    role: Mapped[str] = mapped_column(String(32), default="custom")
    mode: Mapped[str] = mapped_column(String(32), default="react")
    provider: Mapped[str] = mapped_column(String(64), default="")
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    prompt_template: Mapped[str] = mapped_column(String(64), default="")
    cot: Mapped[int] = mapped_column(Integer, default=0)
    tools: Mapped[list] = mapped_column(JSON, default=list)
    retriever: Mapped[dict] = mapped_column(JSON, default=dict)
    pipeline: Mapped[list] = mapped_column(JSON, default=list)
    max_steps: Mapped[int] = mapped_column(Integer, default=6)
    reflection_rounds: Mapped[int] = mapped_column(Integer, default=2)
    temperature: Mapped[float] = mapped_column(default=0.3)
    max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_builtin: Mapped[int] = mapped_column(Integer, default=0)
    is_deleted: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
