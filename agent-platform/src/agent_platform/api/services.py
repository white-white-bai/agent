"""应用 / 图 / 会话持久化。"""
from __future__ import annotations

import uuid

from sqlalchemy import select

from agent_platform.core.db import session_scope
from agent_platform.domain.models import App, Conversation, Graph, GraphVersion, Message
from agent_platform.graph.schema import GraphDef


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


def get_published_graph(app_uuid: str) -> GraphDef | None:
    with session_scope() as session:
        graph = session.scalar(select(Graph).where(Graph.app_uuid == app_uuid))
        if graph is None or graph.published_version_id is None:
            return None
        version = session.get(GraphVersion, graph.published_version_id)
        if version is None:
            return None
        return GraphDef.model_validate(version.definition)


def get_or_create_conversation(app: App, user_name: str, conversation_id: str = "") -> Conversation:
    with session_scope() as session:
        if conversation_id:
            existing = session.scalar(select(Conversation).where(Conversation.conversation_id == conversation_id))
            if existing is not None:
                return existing
        conversation = Conversation(
            uuid=uuid.uuid4().hex,
            tenant_code=app.tenant_code,
            app_uuid=app.uuid,
            conversation_id=conversation_id or uuid.uuid4().hex,
            user_name=user_name,
        )
        session.add(conversation)
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
) -> str:
    message_id = uuid.uuid4().hex
    with session_scope() as session:
        session.add(
            Message(
                uuid=uuid.uuid4().hex,
                conversation_uuid=conversation.uuid,
                message_id=message_id,
                role=role,
                query=query,
                answer=answer,
                answer_metadata=metadata or {},
                tokens=tokens,
                cost_seconds=cost_seconds,
            )
        )
    return message_id
