from datetime import datetime, timezone
from typing import ClassVar

from sqlalchemy import JSON, DateTime, Float, Index, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from agent_platform.core.db import Base

# 知识库文档原文可达 15MB，MySQL 下需 LONGTEXT（Text 仅 64KB）；SQLite/其它方言仍用 TEXT
LongText = Text().with_variant(mysql.LONGTEXT, "mysql")
# checkpoint 整份 state 可能超过 64KB，MySQL 下必须 LONGBLOB
LongBlob = LargeBinary().with_variant(mysql.LONGBLOB, "mysql")
# 知识库三表统一排序规则：分段与文档按 uuid 关联，collation 不一致会触发 MySQL「Illegal mix of collations」
KB_TABLE_ARGS: dict[str, str] = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}


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


class AgentApp(Base):
    """Agent 应用配置（草稿/发布）：对标图应用，但定义的是自主 agent 而非工作流图。"""

    __tablename__ = "ap_agent_app"
    __table_args__ = (UniqueConstraint("app_uuid", name="uk_ap_agent_app_app_uuid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    tenant_code: Mapped[str] = mapped_column(String(64), index=True)
    app_uuid: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    published_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    draft: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class AgentAppVersion(Base):
    __tablename__ = "ap_agent_app_version"
    __table_args__ = (UniqueConstraint("agent_uuid", "version", name="uk_ap_agent_app_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    agent_uuid: Mapped[str] = mapped_column(String(64), index=True)
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
    checkpoint: Mapped[bytes] = mapped_column(LongBlob)
    metadata_type: Mapped[str] = mapped_column(String(32))
    metadata_blob: Mapped[bytes] = mapped_column("metadata", LongBlob)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Dataset(Base):
    """知识库：文档与分段的归属容器，携带默认检索配置。"""

    __tablename__ = "ap_dataset"
    __table_args__: ClassVar[dict[str, str]] = KB_TABLE_ARGS

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    tenant_code: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    embedding_model: Mapped[str] = mapped_column(String(64), default="")
    index_method: Mapped[str] = mapped_column(String(16), default="high_quality")
    chunk_config: Mapped[dict] = mapped_column(JSON, default=dict)
    retrieval: Mapped[dict] = mapped_column(JSON, default=dict)
    is_deleted: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class Document(Base):
    """知识库文档元数据（正文以分段形式存放在 ap_document_segment）。"""

    __tablename__ = "ap_document"
    __table_args__: ClassVar[dict[str, str]] = KB_TABLE_ARGS

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    tenant_code: Mapped[str] = mapped_column(String(64), index=True)
    dataset_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    name: Mapped[str] = mapped_column(String(255), default="")
    content: Mapped[str] = mapped_column(LongText, default="")
    file_type: Mapped[str] = mapped_column(String(32), default="")
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="ready")
    error: Mapped[str] = mapped_column(String(512), default="")
    chunk_config: Mapped[dict] = mapped_column(JSON, default=dict)
    doc_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    is_deleted: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class DocumentSegment(Base):
    """文档分段：向量检索的最小单位。"""

    __tablename__ = "ap_document_segment"
    __table_args__: ClassVar[dict[str, str]] = KB_TABLE_ARGS

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    tenant_code: Mapped[str] = mapped_column(String(64), index=True)
    dataset_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    document_uuid: Mapped[str] = mapped_column(String(64), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text, default="")
    embedding: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
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
    task_path: Mapped[str] = mapped_column(String(128), default="")
    idx: Mapped[int] = mapped_column(Integer)
    channel: Mapped[str] = mapped_column(String(128))
    type: Mapped[str] = mapped_column(String(32))
    value: Mapped[bytes] = mapped_column(LongBlob)


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
    description: Mapped[str] = mapped_column(Text, default="")
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


class Run(Base):
    """管理端图运行记录：承载 HITL 中断/恢复与图定义快照。"""

    __tablename__ = "ap_run"
    __table_args__ = (UniqueConstraint("thread_id", name="uk_ap_run_thread"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    tenant_code: Mapped[str] = mapped_column(String(64), index=True, default="")
    app_uuid: Mapped[str] = mapped_column(String(64), index=True, default="")
    thread_id: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(16), default="running")
    graph_definition: Mapped[dict] = mapped_column(JSON, default=dict)
    subgraph_snapshot: Mapped[list] = mapped_column(JSON, default=list)
    interrupt_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    resolved_by: Mapped[str] = mapped_column(String(64), default="")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class UserMemory(Base):
    """用户级长期记忆条目：按租户 + 应用 + 用户隔离。"""

    __tablename__ = "ap_user_memory"
    __table_args__ = (
        UniqueConstraint("tenant_code", "user_key", "app_uuid", "content_hash", name="uk_ap_user_memory_dedup"),
        Index("idx_ap_user_memory_scope", "tenant_code", "user_key", "app_uuid", "is_deleted"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    tenant_code: Mapped[str] = mapped_column(String(64), index=True, default="")
    app_uuid: Mapped[str] = mapped_column(String(64), index=True, default="")
    user_key: Mapped[str] = mapped_column(String(128), index=True)
    user_name: Mapped[str] = mapped_column(String(128), default="")
    kind: Mapped[str] = mapped_column(String(16), default="fact")
    content: Mapped[str] = mapped_column(LongText, default="")
    embedding: Mapped[list] = mapped_column(JSON, default=list)
    embedding_model: Mapped[str] = mapped_column(String(64), default="")
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    source_conversation_id: Mapped[str] = mapped_column(String(64), default="")
    source_message_id: Mapped[str] = mapped_column(String(64), default="")
    content_hash: Mapped[str] = mapped_column(String(64), index=True, default="")
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    last_hit_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_deleted: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class UserMemoryState(Base):
    """用户记忆抽取水位线：每 (租户, 用户, 应用) 一行。"""

    __tablename__ = "ap_user_memory_state"
    __table_args__ = (UniqueConstraint("tenant_code", "user_key", "app_uuid", name="uk_ap_user_memory_state"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    tenant_code: Mapped[str] = mapped_column(String(64), index=True, default="")
    app_uuid: Mapped[str] = mapped_column(String(64), index=True, default="")
    user_key: Mapped[str] = mapped_column(String(128), index=True)
    last_message_id: Mapped[int] = mapped_column(Integer, default=0)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
