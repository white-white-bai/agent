"""按 app 的并发上限：超出即拒绝；配置等待时长后可排队等空位。"""
from __future__ import annotations

import asyncio

from agent_platform.core import redis as redis_store
from agent_platform.core.config import Settings

PREFIX = "ap:concurrency:"
SLOT_TTL_SECONDS = 3600
POLL_INTERVAL_SECONDS = 0.2


class ConcurrencyLimiter:
    """上限由 max_concurrency_per_app 控制，<=0 时整体关闭。

    每个在跑的请求占一个计数槽，槽位带 TTL 兜底，进程异常退出后不会永久占位。
    """

    def __init__(self, settings: Settings) -> None:
        self.limit = settings.max_concurrency_per_app
        self.wait_seconds = settings.concurrency_wait_seconds
        self.enabled = self.limit > 0

    def _key(self, app_uuid: str) -> str:
        return PREFIX + app_uuid

    def acquire(self, app_uuid: str) -> bool:
        if not self.enabled:
            return True
        key = self._key(app_uuid)
        count = redis_store.incr_with_ttl(key, SLOT_TTL_SECONDS)
        if count <= self.limit:
            return True
        redis_store.incr_with_ttl(key, SLOT_TTL_SECONDS, amount=-1)
        return False

    def release(self, app_uuid: str) -> None:
        if not self.enabled:
            return
        redis_store.incr_with_ttl(self._key(app_uuid), SLOT_TTL_SECONDS, amount=-1)

    async def acquire_with_wait(self, app_uuid: str) -> bool:
        if not self.enabled:
            return True
        if self.acquire(app_uuid):
            return True
        waited = 0.0
        while waited < self.wait_seconds:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            waited += POLL_INTERVAL_SECONDS
            if self.acquire(app_uuid):
                return True
        return False
