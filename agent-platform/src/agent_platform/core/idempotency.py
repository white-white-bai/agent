"""幂等键：同一请求重复到达时复用首次结果，避免重复执行与重复落库。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from agent_platform.core import redis as redis_store
from agent_platform.core.config import Settings

PREFIX = "ap:idem:"
LOCK_VALUE = "1"
DONE_VALUE = "done"


@dataclass
class IdempotencyOutcome:
    replay: dict[str, Any] | None = None
    in_flight: bool = False

    @property
    def hit(self) -> bool:
        return self.replay is not None or self.in_flight


class IdempotencyStore:
    """TTL 由 idempotency_ttl_seconds 控制，<=0 时整体关闭。

    默认只在调用方显式给键（Idempotency-Key 头或 body idempotency_key）时生效；
    idempotency_derive_key 打开后才用 app+user+conversation+query 自行推导，
    否则同一会话里正常重复提问会被误判为重放。
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.ttl = settings.idempotency_ttl_seconds
        self.enabled = self.ttl > 0

    def key_for(
        self,
        *,
        app_uuid: str,
        user: str = "",
        conversation_id: str = "",
        query: str = "",
        explicit: str = "",
    ) -> str:
        token = (explicit or "").strip()
        if not token:
            if not self.settings.idempotency_derive_key:
                return ""
            token = f"{app_uuid}|{user}|{conversation_id}|{query}"
        return PREFIX + token

    def acquire(self, key: str) -> IdempotencyOutcome:
        if not (self.enabled and key):
            return IdempotencyOutcome()
        if redis_store.set_if_absent(key, LOCK_VALUE, self.ttl):
            return IdempotencyOutcome()
        payload = redis_store.get_value(key)
        if payload in (None, "", LOCK_VALUE, DONE_VALUE):
            return IdempotencyOutcome(in_flight=True)
        try:
            return IdempotencyOutcome(replay=json.loads(payload))
        except (TypeError, ValueError):
            return IdempotencyOutcome(in_flight=True)

    def complete(self, key: str, payload: dict[str, Any]) -> None:
        if not (self.enabled and key):
            return
        redis_store.set_value(key, json.dumps(payload, ensure_ascii=False), self.ttl)

    def release(self, key: str) -> None:
        if not (self.enabled and key):
            return
        redis_store.delete(key)
