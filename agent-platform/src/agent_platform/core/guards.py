"""护栏链：敏感词 / 额度 / 频率 / 轮数 / 默认回复。

「先上不启用」：`AP_GUARD_ENABLED=False`（默认）时全部短路放行，双跑期与 Java 侧各持一份配置。
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select

from agent_platform.core.config import Settings, get_settings
from agent_platform.core.db import session_scope
from agent_platform.core.redis import incr_with_ttl
from agent_platform.domain.models import Conversation, Message, SensitiveWord

DEFAULT_REPLY = "智能客服为您解答政务服务领域的问题，超出领域的问题不在能力之内哦！"


@dataclass
class GuardDecision:
    allowed: bool = True
    reply: str = ""
    reason: str = ""
    guard: str = ""


class GuardChain:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def enabled(self) -> bool:
        return bool(self.settings.guard_enabled)

    def _default_reply(self) -> str:
        return self.settings.guard_default_reply or DEFAULT_REPLY

    def check_sensitive(self, text: str, tenant_code: str) -> GuardDecision:
        if not (self.enabled and self.settings.guard_sensitive_enabled):
            return GuardDecision()
        normalized = (text or "").lower()
        if not normalized:
            return GuardDecision()
        with session_scope() as session:
            words = session.scalars(
                select(SensitiveWord).where(SensitiveWord.tenant_code.in_([tenant_code, ""]))
            ).all()
        hits = [w.word for w in words if w.word and w.word.lower() in normalized]
        if hits:
            return GuardDecision(False, self._default_reply(), f"命中敏感词: {hits[0]}", "sensitive")
        return GuardDecision()

    def check_rate(self, app_uuid: str, user: str) -> GuardDecision:
        if not (self.enabled and self.settings.guard_rate_enabled):
            return GuardDecision()
        limit = self.settings.guard_rate_per_minute
        if limit <= 0:
            return GuardDecision()
        key = f"ap:rate:{app_uuid}:{user or 'anonymous'}"
        if incr_with_ttl(key, 60) > limit:
            return GuardDecision(False, self._default_reply(), "请求过于频繁", "rate")
        return GuardDecision()

    def check_rounds(self, conversation: Conversation | None) -> GuardDecision:
        if not (self.enabled and self.settings.guard_round_enabled) or conversation is None:
            return GuardDecision()
        limit = self.settings.guard_max_rounds
        if limit <= 0:
            return GuardDecision()
        with session_scope() as session:
            used = session.scalar(
                select(func.count(Message.id)).where(
                    Message.conversation_uuid == conversation.uuid, Message.role == "user"
                )
            )
        if (used or 0) >= limit:
            return GuardDecision(False, self._default_reply(), "会话轮数超限", "rounds")
        return GuardDecision()

    def check_quota(self, tenant_code: str) -> GuardDecision:
        if not (self.enabled and self.settings.guard_quota_enabled):
            return GuardDecision()
        quota = self.settings.guard_daily_token_quota
        if quota <= 0:
            return GuardDecision()
        with session_scope() as session:
            used = session.scalar(
                select(func.coalesce(func.sum(Message.tokens), 0))
                .join(Conversation, Conversation.uuid == Message.conversation_uuid)
                .where(Conversation.tenant_code == tenant_code)
            )
        if (used or 0) >= quota:
            return GuardDecision(False, self._default_reply(), "额度已用尽", "quota")
        return GuardDecision()

    def pre_check(
        self,
        *,
        tenant_code: str,
        app_uuid: str,
        user: str,
        query: str,
        conversation: Conversation | None = None,
    ) -> GuardDecision:
        for decision in (
            self.check_sensitive(query, tenant_code),
            self.check_rate(app_uuid, user),
            self.check_rounds(conversation),
            self.check_quota(tenant_code),
        ):
            if not decision.allowed:
                return decision
        return GuardDecision()
