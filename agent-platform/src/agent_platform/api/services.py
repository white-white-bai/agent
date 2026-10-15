"""应用 / 图 / 会话 / 消息 / 护栏配置 / 知识库 / MCP 持久化。"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import func, select

from agent_platform.core.db import session_scope
from agent_platform.domain.models import (
    Agent,
    App,
    Conversation,
    Graph,
    GraphVersion,
    McpServer,
    Message,
    PromptTemplate,
    SensitiveWord,
    Tool,
)
from agent_platform.engine.context import LLMInvoker
from agent_platform.graph.schema import GraphDef

logger = logging.getLogger("agent_platform.memory")

SUMMARY_SYSTEM_PROMPT = (
    "你是会话摘要助手。把给定的历史对话压缩成简洁中文摘要，保留事实、结论、"
    "未决问题与用户偏好；只输出摘要正文，不要任何额外说明。"
)


def _new_uuid() -> str:
    return uuid.uuid4().hex


class AppIdConflictError(Exception):
    """app_id 已被占用，且无法按软删除复活（在用中，或软删除记录属于其他租户）。"""

    def __init__(self, message: str) -> None:
        super().__init__(message)


# --------------------------------------------------------------------------- 应用（注册表）

def create_app(
    *,
    tenant_code: str,
    app_id: str,
    api_key: str,
    app_name: str = "",
    app_type: str = "chat",
    icon: str = "",
    opening_statement: str = "",
    suggested_questions: list[str] | None = None,
    app_info: dict[str, Any] | None = None,
    app_uuid: str = "",
) -> App:
    with session_scope() as session:
        existing = session.scalar(select(App).where(App.app_id == app_id))
        if existing is not None:
            if not existing.is_deleted:
                raise AppIdConflictError(f"app_id 已存在：{app_id}")
            if existing.tenant_code != tenant_code:
                raise AppIdConflictError(f"app_id 属于其他租户：{app_id}")
            existing.api_key = api_key
            existing.app_name = app_name
            existing.app_type = app_type
            existing.icon = icon
            existing.opening_statement = opening_statement
            existing.suggested_questions = suggested_questions or []
            existing.app_info = app_info or {}
            existing.is_deleted = 0
            session.flush()
            return existing
        row = App(
            uuid=app_uuid or _new_uuid(),
            tenant_code=tenant_code,
            app_id=app_id,
            api_key=api_key,
            app_name=app_name,
            app_type=app_type,
            icon=icon,
            opening_statement=opening_statement,
            suggested_questions=suggested_questions or [],
            app_info=app_info or {},
        )
        session.add(row)
        session.flush()
        return row


def get_app_by_key(api_key: str) -> App | None:
    if not api_key:
        return None
    with session_scope() as session:
        return session.scalar(select(App).where(App.api_key == api_key, App.is_deleted == 0))


def get_app_by_app_id(app_id: str) -> App | None:
    if not app_id:
        return None
    with session_scope() as session:
        return session.scalar(select(App).where(App.app_id == app_id, App.is_deleted == 0))


def get_app_by_uuid(app_uuid: str) -> App | None:
    if not app_uuid:
        return None
    with session_scope() as session:
        return session.scalar(select(App).where(App.uuid == app_uuid, App.is_deleted == 0))


def list_apps(tenant_code: str = "") -> list[App]:
    with session_scope() as session:
        stmt = select(App).where(App.is_deleted == 0)
        if tenant_code:
            stmt = stmt.where(App.tenant_code == tenant_code)
        return list(session.scalars(stmt.order_by(App.id.desc())).all())


def update_app(app_uuid: str, **fields: Any) -> App | None:
    allowed = {
        "app_name",
        "app_type",
        "icon",
        "opening_statement",
        "suggested_questions",
        "app_info",
        "api_key",
        "tenant_code",
    }
    with session_scope() as session:
        row = session.scalar(select(App).where(App.uuid == app_uuid, App.is_deleted == 0))
        if row is None:
            return None
        for key, value in fields.items():
            if key in allowed and value is not None:
                setattr(row, key, value)
        session.flush()
        return row


def delete_app(app_uuid: str) -> bool:
    with session_scope() as session:
        row = session.scalar(select(App).where(App.uuid == app_uuid, App.is_deleted == 0))
        if row is None:
            return False
        row.is_deleted = 1
        return True


# --------------------------------------------------------------------------- 图（草稿 / 发布 / 回滚）

def get_graph_by_app_uuid(app_uuid: str) -> Graph | None:
    with session_scope() as session:
        return session.scalar(select(Graph).where(Graph.app_uuid == app_uuid))


def get_or_create_graph(app_uuid: str, tenant_code: str = "") -> Graph:
    with session_scope() as session:
        graph = session.scalar(select(Graph).where(Graph.app_uuid == app_uuid))
        if graph is not None:
            return graph
        graph = Graph(uuid=_new_uuid(), tenant_code=tenant_code, app_uuid=app_uuid, status="draft")
        session.add(graph)
        session.flush()
        return graph


def save_draft(app_uuid: str, definition: dict[str, Any], tenant_code: str = "") -> Graph:
    with session_scope() as session:
        graph = session.scalar(select(Graph).where(Graph.app_uuid == app_uuid))
        if graph is None:
            graph = Graph(uuid=_new_uuid(), tenant_code=tenant_code, app_uuid=app_uuid, status="draft")
            session.add(graph)
            session.flush()
        graph.draft = definition
        if graph.published_version_id is None:
            graph.status = "draft"
        session.flush()
        return graph


def get_draft(app_uuid: str) -> dict[str, Any] | None:
    with session_scope() as session:
        graph = session.scalar(select(Graph).where(Graph.app_uuid == app_uuid))
        if graph is None:
            return None
        if graph.draft:
            return graph.draft
        if graph.published_version_id is not None:
            version = session.get(GraphVersion, graph.published_version_id)
            return version.definition if version is not None else None
        return None


def _next_version(session: Any, graph_uuid: str) -> int:
    current = session.scalar(select(func.max(GraphVersion.version)).where(GraphVersion.graph_uuid == graph_uuid))
    return int(current or 0) + 1


def publish_draft(
    app_uuid: str, tenant_code: str = "", note: str = "", created_by: str = "", definition: dict[str, Any] | None = None
) -> GraphVersion | None:
    with session_scope() as session:
        graph = session.scalar(select(Graph).where(Graph.app_uuid == app_uuid))
        if graph is None:
            graph = Graph(uuid=_new_uuid(), tenant_code=tenant_code, app_uuid=app_uuid, status="draft")
            session.add(graph)
            session.flush()
        payload = definition if definition is not None else (graph.draft or {})
        if not payload:
            return None
        GraphDef.model_validate(payload)
        version = GraphVersion(
            uuid=_new_uuid(),
            graph_uuid=graph.uuid,
            version=_next_version(session, graph.uuid),
            definition=payload,
            note=note,
            created_by=created_by,
        )
        session.add(version)
        session.flush()
        graph.status = "published"
        graph.published_version_id = version.id
        graph.draft = payload
        return version


def list_versions(app_uuid: str) -> list[GraphVersion]:
    with session_scope() as session:
        graph = session.scalar(select(Graph).where(Graph.app_uuid == app_uuid))
        if graph is None:
            return []
        return list(
            session.scalars(
                select(GraphVersion).where(GraphVersion.graph_uuid == graph.uuid).order_by(GraphVersion.version.desc())
            ).all()
        )


def rollback(app_uuid: str, version: int) -> GraphVersion | None:
    with session_scope() as session:
        graph = session.scalar(select(Graph).where(Graph.app_uuid == app_uuid))
        if graph is None:
            return None
        version_row = session.scalar(
            select(GraphVersion).where(GraphVersion.graph_uuid == graph.uuid, GraphVersion.version == version)
        )
        if version_row is None:
            return None
        graph.published_version_id = version_row.id
        graph.draft = version_row.definition
        graph.status = "published"
        return version_row


def get_published_graph(app_uuid: str) -> GraphDef | None:
    with session_scope() as session:
        graph = session.scalar(select(Graph).where(Graph.app_uuid == app_uuid))
        if graph is None or graph.published_version_id is None:
            return None
        version = session.get(GraphVersion, graph.published_version_id)
        if version is None:
            return None
        return GraphDef.model_validate(version.definition)


# --------------------------------------------------------------------------- 会话 / 消息

def get_or_create_conversation(app: App, user_name: str, conversation_id: str = "") -> Conversation:
    with session_scope() as session:
        if conversation_id:
            existing = session.scalar(select(Conversation).where(Conversation.conversation_id == conversation_id))
            if existing is not None:
                return existing
        conversation = Conversation(
            uuid=_new_uuid(),
            tenant_code=app.tenant_code,
            app_uuid=app.uuid,
            conversation_id=conversation_id or _new_uuid(),
            user_name=user_name,
        )
        session.add(conversation)
        session.flush()
        return conversation


def get_conversation(conversation_id: str) -> Conversation | None:
    if not conversation_id:
        return None
    with session_scope() as session:
        return session.scalar(select(Conversation).where(Conversation.conversation_id == conversation_id))


def list_conversations(
    app_uuid: str, user_name: str = "", limit: int = 20, offset: int = 0
) -> list[Conversation]:
    with session_scope() as session:
        stmt = select(Conversation).where(Conversation.app_uuid == app_uuid)
        if user_name:
            stmt = stmt.where(Conversation.user_name == user_name)
        stmt = stmt.order_by(Conversation.updated_at.desc(), Conversation.id.desc()).limit(limit).offset(offset)
        return list(session.scalars(stmt).all())


def count_conversations(app_uuid: str, user_name: str = "") -> int:
    with session_scope() as session:
        stmt = select(func.count(Conversation.id)).where(Conversation.app_uuid == app_uuid)
        if user_name:
            stmt = stmt.where(Conversation.user_name == user_name)
        return int(session.scalar(stmt) or 0)


def rename_conversation(conversation_id: str, name: str, auto_generate: bool = False) -> Conversation | None:
    with session_scope() as session:
        conversation = session.scalar(select(Conversation).where(Conversation.conversation_id == conversation_id))
        if conversation is None:
            return None
        if name:
            conversation.name = name
        elif auto_generate and not conversation.name:
            first = session.scalar(
                select(Message)
                .where(Message.conversation_uuid == conversation.uuid, Message.role == "user")
                .order_by(Message.id.asc())
            )
            conversation.name = (first.query if first is not None else "")[:255]
        session.flush()
        return conversation


def save_message(
    conversation: Conversation,
    role: str,
    query: str = "",
    answer: str = "",
    metadata: dict | None = None,
    tokens: int = 0,
    cost_seconds: float = 0.0,
    message_id: str = "",
    parent_message_id: str = "",
) -> str:
    message_id = message_id or _new_uuid()
    with session_scope() as session:
        session.add(
            Message(
                uuid=_new_uuid(),
                conversation_uuid=conversation.uuid,
                message_id=message_id,
                parent_message_id=parent_message_id,
                role=role,
                query=query,
                answer=answer,
                answer_metadata=metadata or {},
                tokens=tokens,
                cost_seconds=cost_seconds,
            )
        )
    return message_id


def list_messages(
    conversation_id: str, limit: int = 20, first_id: str = "", offset: int = 0
) -> list[Message]:
    conversation = get_conversation(conversation_id)
    if conversation is None:
        return []
    with session_scope() as session:
        stmt = select(Message).where(Message.conversation_uuid == conversation.uuid)
        if first_id:
            anchor = session.scalar(select(Message).where(Message.message_id == first_id))
            if anchor is not None:
                stmt = stmt.where(Message.id > anchor.id)
        stmt = stmt.order_by(Message.id.asc()).limit(limit).offset(offset)
        return list(session.scalars(stmt).all())


def count_messages(conversation_id: str) -> int:
    conversation = get_conversation(conversation_id)
    if conversation is None:
        return 0
    with session_scope() as session:
        return int(
            session.scalar(select(func.count(Message.id)).where(Message.conversation_uuid == conversation.uuid)) or 0
        )


def load_history(conversation: Conversation, window: int) -> list[dict[str, str]]:
    if window <= 0:
        return []
    with session_scope() as session:
        rows = list(
            session.scalars(
                select(Message)
                .where(Message.conversation_uuid == conversation.uuid)
                .order_by(Message.id.desc())
                .limit(window)
            ).all()
        )
    return [
        {"role": row.role, "content": (row.answer if row.role == "assistant" else row.query) or ""}
        for row in reversed(rows)
    ]


def _summarizable_messages(conversation: Conversation, window: int) -> list[Message]:
    """窗口之外、且尚未纳入摘要的历史消息（正序）。"""
    with session_scope() as session:
        recent = (
            select(Message.id)
            .where(Message.conversation_uuid == conversation.uuid)
            .order_by(Message.id.desc())
            .limit(window)
        )
        stmt = (
            select(Message)
            .where(
                Message.conversation_uuid == conversation.uuid,
                Message.id > (conversation.summary_upto_id or 0),
                Message.id.not_in(recent),
            )
            .order_by(Message.id.asc())
        )
        return list(session.scalars(stmt).all())


def _render_overflow(messages: list[Message], max_chars: int) -> tuple[str, int]:
    """渲染待摘要的对话，返回 (文本, 已纳入的最大消息 id)。

    逐条累加，超出 max_chars 即停，剩余部分留待下一轮再压缩，保证不丢消息。
    """
    lines: list[str] = []
    used = 0
    last_id = 0
    for row in messages:
        text = (row.answer if row.role == "assistant" else row.query) or ""
        if not text:
            last_id = row.id
            continue
        line = f"{row.role}: {text}"
        if lines and used + len(line) > max_chars:
            break
        lines.append(line)
        used += len(line)
        last_id = row.id
    return "\n".join(lines), last_id


async def refresh_summary(
    conversation: Conversation,
    window: int,
    invoker: LLMInvoker,
    *,
    provider: str,
    max_chars: int = 4000,
) -> str:
    """把窗口之外的历史压缩进会话摘要；无新增可压缩内容时原样返回。"""
    if window <= 0 or max_chars <= 0:
        return conversation.summary or ""
    body, last_id = _render_overflow(_summarizable_messages(conversation, window), max_chars)
    if not body:
        return conversation.summary or ""
    previous = conversation.summary or ""
    if previous:
        prompt = f"已有摘要：\n{previous}\n\n新增对话：\n{body}\n\n请输出合并后的完整摘要。"
    else:
        prompt = f"新增对话：\n{body}\n\n请输出完整摘要。"
    try:
        summary = (
            await invoker(
                provider=provider,
                system_prompt=SUMMARY_SYSTEM_PROMPT,
                user_prompt=prompt,
                temperature=0.2,
                max_tokens=None,
            )
        ).strip()
    except Exception:
        logger.warning("会话摘要生成失败，降级为上一轮摘要", exc_info=True)
        return previous
    if not summary:
        return previous
    with session_scope() as session:
        row = session.scalar(select(Conversation).where(Conversation.uuid == conversation.uuid))
        if row is not None:
            row.summary = summary
            row.summary_upto_id = last_id
    conversation.summary = summary
    conversation.summary_upto_id = last_id
    return summary


def get_message_by_message_id(message_id: str) -> Message | None:
    if not message_id:
        return None
    with session_scope() as session:
        return session.scalar(select(Message).where(Message.message_id == message_id).order_by(Message.id.desc()))


def set_feedback(message_id: str, rating: str | None, user: str = "") -> Message | None:
    with session_scope() as session:
        message = session.scalar(select(Message).where(Message.message_id == message_id).order_by(Message.id.desc()))
        if message is None:
            return None
        message.feedback = rating
        return message


# --------------------------------------------------------------------------- 敏感词

def list_sensitive_words(tenant_code: str = "") -> list[SensitiveWord]:
    with session_scope() as session:
        stmt = select(SensitiveWord)
        if tenant_code:
            stmt = stmt.where(SensitiveWord.tenant_code == tenant_code)
        return list(session.scalars(stmt.order_by(SensitiveWord.id.desc())).all())


def add_sensitive_word(tenant_code: str, word: str) -> SensitiveWord:
    with session_scope() as session:
        row = SensitiveWord(tenant_code=tenant_code, word=word)
        session.add(row)
        session.flush()
        return row


def delete_sensitive_word(word_id: int) -> bool:
    with session_scope() as session:
        row = session.get(SensitiveWord, word_id)
        if row is None:
            return False
        session.delete(row)
        return True


# --------------------------------------------------------------------------- MCP Server 注册

def list_mcp_servers(tenant_code: str = "") -> list[McpServer]:
    with session_scope() as session:
        stmt = select(McpServer).where(McpServer.is_deleted == 0)
        if tenant_code:
            stmt = stmt.where(McpServer.tenant_code == tenant_code)
        return list(session.scalars(stmt.order_by(McpServer.id.desc())).all())


def create_mcp_server(
    *, tenant_code: str, name: str, url: str, kind: str = "mcp", headers: dict[str, str] | None = None
) -> McpServer:
    with session_scope() as session:
        row = McpServer(
            uuid=_new_uuid(), tenant_code=tenant_code, name=name, url=url, kind=kind, headers=headers or {}
        )
        session.add(row)
        session.flush()
        return row


def delete_mcp_server(server_uuid: str) -> bool:
    with session_scope() as session:
        row = session.scalar(select(McpServer).where(McpServer.uuid == server_uuid, McpServer.is_deleted == 0))
        if row is None:
            return False
        row.is_deleted = 1
        return True


# --------------------------------------------------------------------------- 工具声明 / 智能体 / 提示词模板

_TOOL_FIELDS = (
    "label", "category", "server", "kind", "http_method", "http_path",
    "params", "retry_attempts", "retry_backoff_seconds", "fallback",
)
_AGENT_FIELDS = (
    "label", "role", "mode", "provider", "system_prompt", "prompt_template", "cot",
    "tools", "retriever", "pipeline", "max_steps", "reflection_rounds", "temperature", "max_tokens",
)
_PROMPT_FIELDS = ("label", "system_prompt", "examples", "cot_hint")


def _apply_fields(row: Any, fields: dict[str, Any], allowed: tuple[str, ...]) -> None:
    for key in allowed:
        if fields.get(key) is not None:
            setattr(row, key, fields[key])


def list_tools(tenant_code: str = "") -> list[Tool]:
    with session_scope() as session:
        stmt = select(Tool).where(Tool.is_deleted == 0)
        if tenant_code:
            stmt = stmt.where(Tool.tenant_code == tenant_code)
        return list(session.scalars(stmt.order_by(Tool.id.desc())).all())


def get_tool(tool_uuid: str) -> Tool | None:
    with session_scope() as session:
        return session.scalar(select(Tool).where(Tool.uuid == tool_uuid, Tool.is_deleted == 0))


def get_tool_by_name(name: str) -> Tool | None:
    with session_scope() as session:
        return session.scalar(select(Tool).where(Tool.name == name, Tool.is_deleted == 0))


def create_tool(*, tenant_code: str, name: str, **fields: Any) -> Tool:
    with session_scope() as session:
        row = Tool(uuid=_new_uuid(), tenant_code=tenant_code, name=name)
        _apply_fields(row, fields, _TOOL_FIELDS)
        session.add(row)
        session.flush()
        return row


def update_tool(tool_uuid: str, **fields: Any) -> Tool | None:
    with session_scope() as session:
        row = session.scalar(select(Tool).where(Tool.uuid == tool_uuid, Tool.is_deleted == 0))
        if row is None:
            return None
        _apply_fields(row, fields, _TOOL_FIELDS)
        return row


def delete_tool(tool_uuid: str) -> bool:
    with session_scope() as session:
        row = session.scalar(select(Tool).where(Tool.uuid == tool_uuid, Tool.is_deleted == 0))
        if row is None:
            return False
        row.is_deleted = 1
        return True


def list_agents(tenant_code: str = "") -> list[Agent]:
    with session_scope() as session:
        stmt = select(Agent).where(Agent.is_deleted == 0)
        if tenant_code:
            stmt = stmt.where(Agent.tenant_code == tenant_code)
        return list(session.scalars(stmt.order_by(Agent.id.desc())).all())


def get_agent(agent_uuid: str) -> Agent | None:
    with session_scope() as session:
        return session.scalar(select(Agent).where(Agent.uuid == agent_uuid, Agent.is_deleted == 0))


def get_agent_by_code(code: str) -> Agent | None:
    with session_scope() as session:
        return session.scalar(select(Agent).where(Agent.code == code, Agent.is_deleted == 0))


def create_agent(*, tenant_code: str, code: str, **fields: Any) -> Agent:
    with session_scope() as session:
        row = Agent(uuid=_new_uuid(), tenant_code=tenant_code, code=code)
        _apply_fields(row, fields, _AGENT_FIELDS)
        session.add(row)
        session.flush()
        return row


def update_agent(agent_uuid: str, **fields: Any) -> Agent | None:
    with session_scope() as session:
        row = session.scalar(select(Agent).where(Agent.uuid == agent_uuid, Agent.is_deleted == 0))
        if row is None:
            return None
        _apply_fields(row, fields, _AGENT_FIELDS)
        return row


def delete_agent(agent_uuid: str) -> bool:
    with session_scope() as session:
        row = session.scalar(select(Agent).where(Agent.uuid == agent_uuid, Agent.is_deleted == 0))
        if row is None:
            return False
        row.is_deleted = 1
        return True


def list_prompts(tenant_code: str = "") -> list[PromptTemplate]:
    with session_scope() as session:
        stmt = select(PromptTemplate).where(PromptTemplate.is_deleted == 0)
        if tenant_code:
            stmt = stmt.where(PromptTemplate.tenant_code == tenant_code)
        return list(session.scalars(stmt.order_by(PromptTemplate.id.desc())).all())


def get_prompt(prompt_uuid: str) -> PromptTemplate | None:
    with session_scope() as session:
        return session.scalar(
            select(PromptTemplate).where(PromptTemplate.uuid == prompt_uuid, PromptTemplate.is_deleted == 0)
        )


def get_prompt_by_code(code: str) -> PromptTemplate | None:
    with session_scope() as session:
        return session.scalar(
            select(PromptTemplate).where(PromptTemplate.code == code, PromptTemplate.is_deleted == 0)
        )


def create_prompt(*, tenant_code: str, code: str, **fields: Any) -> PromptTemplate:
    with session_scope() as session:
        row = PromptTemplate(uuid=_new_uuid(), tenant_code=tenant_code, code=code)
        _apply_fields(row, fields, _PROMPT_FIELDS)
        session.add(row)
        session.flush()
        return row


def update_prompt(prompt_uuid: str, **fields: Any) -> PromptTemplate | None:
    with session_scope() as session:
        row = session.scalar(
            select(PromptTemplate).where(PromptTemplate.uuid == prompt_uuid, PromptTemplate.is_deleted == 0)
        )
        if row is None:
            return None
        _apply_fields(row, fields, _PROMPT_FIELDS)
        return row


def delete_prompt(prompt_uuid: str) -> bool:
    with session_scope() as session:
        row = session.scalar(
            select(PromptTemplate).where(PromptTemplate.uuid == prompt_uuid, PromptTemplate.is_deleted == 0)
        )
        if row is None:
            return False
        row.is_deleted = 1
        return True
