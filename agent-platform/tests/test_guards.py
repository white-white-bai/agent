"""护栏链：默认短路放行 + 敏感词 / 频率 / 轮数 / 额度。"""
from __future__ import annotations

import uuid

from agent_platform.core.config import Settings
from agent_platform.core.db import session_scope
from agent_platform.core.guards import DEFAULT_REPLY, GuardChain
from agent_platform.domain.models import Conversation, Message, SensitiveWord


def _settings(**overrides) -> Settings:
    base = {"guard_enabled": True, "guard_default_reply": "请换个问题"}
    base.update(overrides)
    return Settings(**base)


def _seed_word(word: str, tenant_code: str = "t") -> None:
    with session_scope() as session:
        session.add(SensitiveWord(tenant_code=tenant_code, word=word))


def _seed_conversation(tenant_code: str = "t") -> Conversation:
    with session_scope() as session:
        row = Conversation(
            uuid=uuid.uuid4().hex,
            tenant_code=tenant_code,
            app_uuid="app-uuid",
            conversation_id=uuid.uuid4().hex,
        )
        session.add(row)
        session.flush()
        session.expunge(row)
        return row


def _seed_message(conversation: Conversation, *, role: str = "user", tokens: int = 0) -> None:
    with session_scope() as session:
        session.add(
            Message(
                uuid=uuid.uuid4().hex,
                conversation_uuid=conversation.uuid,
                message_id=uuid.uuid4().hex,
                role=role,
                query="q",
                tokens=tokens,
            )
        )


# --------------------------------------------------------------------------- 默认短路


def test_guard_disabled_short_circuits_every_check():
    _seed_word("违禁")
    chain = GuardChain(Settings(guard_enabled=False, guard_sensitive_enabled=True, guard_rate_per_minute=1))
    assert chain.enabled is False
    assert chain.check_sensitive("这是违禁内容", "t").allowed
    assert chain.check_rate("app", "alice").allowed
    assert chain.pre_check(tenant_code="t", app_uuid="app", user="alice", query="违禁").allowed


def test_guard_enabled_but_individual_switch_off():
    _seed_word("违禁")
    chain = GuardChain(_settings())
    assert chain.enabled is True
    assert chain.check_sensitive("违禁", "t").allowed
    assert chain.check_rate("app", "alice").allowed
    assert chain.check_rounds(None).allowed
    assert chain.check_quota("t").allowed


def test_guard_reply_falls_back_to_builtin_default():
    chain = GuardChain(Settings(guard_enabled=True))
    assert chain._default_reply() == DEFAULT_REPLY
    _seed_word("违禁")
    chain = GuardChain(_settings(guard_sensitive_enabled=True))
    assert chain.check_sensitive("违禁", "t").reply == "请换个问题"


# --------------------------------------------------------------------------- 敏感词


def test_sensitive_word_blocks_query():
    _seed_word("违禁")
    chain = GuardChain(_settings(guard_sensitive_enabled=True))
    decision = chain.check_sensitive("这里有违禁词", "t")
    assert decision.allowed is False
    assert decision.guard == "sensitive"
    assert decision.reason == "命中敏感词: 违禁"
    assert decision.reply == "请换个问题"


def test_sensitive_word_is_case_insensitive_and_global():
    _seed_word("Bad", tenant_code="")
    chain = GuardChain(_settings(guard_sensitive_enabled=True))
    assert chain.check_sensitive("this is BAD", "other").allowed is False
    assert chain.check_sensitive("something else", "other").allowed is True
    assert chain.check_sensitive("", "t").allowed is True


def test_sensitive_word_scope_is_per_tenant():
    _seed_word("违禁", tenant_code="t")
    chain = GuardChain(_settings(guard_sensitive_enabled=True))
    assert chain.check_sensitive("违禁", "t").allowed is False
    assert chain.check_sensitive("违禁", "u").allowed is True


# --------------------------------------------------------------------------- 频率 / 轮数 / 额度


def test_rate_limit_blocks_after_threshold():
    chain = GuardChain(_settings(guard_rate_enabled=True, guard_rate_per_minute=2))
    app_uuid, user = uuid.uuid4().hex, uuid.uuid4().hex
    assert chain.check_rate(app_uuid, user).allowed is True
    assert chain.check_rate(app_uuid, user).allowed is True
    blocked = chain.check_rate(app_uuid, user)
    assert blocked.allowed is False and blocked.reason == "请求过于频繁"


def test_rate_limit_counts_per_user_and_app():
    chain = GuardChain(_settings(guard_rate_enabled=True, guard_rate_per_minute=1))
    app_uuid = uuid.uuid4().hex
    assert chain.check_rate(app_uuid, "alice").allowed is True
    assert chain.check_rate(app_uuid, "bob").allowed is True
    assert chain.check_rate(uuid.uuid4().hex, "alice").allowed is True
    assert chain.check_rate(app_uuid, "alice").allowed is False


def test_rate_limit_with_zero_limit_is_disabled():
    chain = GuardChain(_settings(guard_rate_enabled=True, guard_rate_per_minute=0))
    for _ in range(5):
        assert chain.check_rate("app", "alice").allowed is True


def test_round_limit_counts_user_messages():
    conversation = _seed_conversation()
    _seed_message(conversation)
    _seed_message(conversation)
    _seed_message(conversation, role="assistant")
    chain = GuardChain(_settings(guard_round_enabled=True, guard_max_rounds=2))
    blocked = chain.check_rounds(conversation)
    assert blocked.allowed is False and blocked.guard == "rounds"


def test_round_limit_allows_under_threshold():
    conversation = _seed_conversation()
    _seed_message(conversation)
    chain = GuardChain(_settings(guard_round_enabled=True, guard_max_rounds=3))
    assert chain.check_rounds(conversation).allowed is True


def test_quota_sums_tokens_across_tenant():
    conversation = _seed_conversation(tenant_code="q-tenant")
    _seed_message(conversation, tokens=30)
    _seed_message(conversation, tokens=40)
    chain = GuardChain(_settings(guard_quota_enabled=True, guard_daily_token_quota=50))
    blocked = chain.check_quota("q-tenant")
    assert blocked.allowed is False and blocked.guard == "quota"
    assert chain.check_quota("other-tenant").allowed is True


# --------------------------------------------------------------------------- 链式顺序


def test_pre_check_returns_first_blocking_guard():
    _seed_word("违禁")
    chain = GuardChain(
        _settings(
            guard_sensitive_enabled=True,
            guard_rate_enabled=True,
            guard_rate_per_minute=1,
        )
    )
    first = chain.pre_check(tenant_code="t", app_uuid=uuid.uuid4().hex, user="alice", query="违禁")
    assert first.guard == "sensitive"


def test_pre_check_passes_when_nothing_triggers():
    chain = GuardChain(
        _settings(
            guard_sensitive_enabled=True,
            guard_rate_enabled=True,
            guard_rate_per_minute=5,
            guard_round_enabled=True,
            guard_max_rounds=5,
            guard_quota_enabled=True,
            guard_daily_token_quota=1000,
        )
    )
    decision = chain.pre_check(tenant_code="t", app_uuid=uuid.uuid4().hex, user="alice", query="你好")
    assert decision.allowed is True
    assert decision.guard == "" and decision.reply == ""


def test_guard_decision_defaults():
    from agent_platform.core.guards import GuardDecision

    decision = GuardDecision()
    assert decision.allowed is True and decision.reason == "" and decision.guard == ""
