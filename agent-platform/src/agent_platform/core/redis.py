"""Redis 客户端（热缓存 / 限流 / 幂等）；不可用时降级为进程内实现。"""
from __future__ import annotations

import time
from typing import Any

from agent_platform.core.config import get_settings

_client: Any = None
_unavailable = False
_memory_counters: dict[str, tuple[int, float]] = {}
_memory_values: dict[str, tuple[Any, float]] = {}
_memory_lists: dict[str, list[str]] = {}


def get_redis() -> Any:
    global _client, _unavailable
    if _client is not None:
        return _client
    if _unavailable:
        return None
    try:
        import redis

        client = redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=1.0)
        client.ping()
        _client = client
    except Exception:  # noqa: BLE001
        _unavailable = True
        _client = None
    return _client


def incr_with_ttl(key: str, ttl_seconds: int) -> int:
    client = get_redis()
    if client is not None:
        try:
            pipe = client.pipeline()
            pipe.incr(key)
            pipe.expire(key, ttl_seconds)
            count, _ = pipe.execute()
            return int(count)
        except Exception:  # noqa: BLE001, S110
            pass
    now = time.time()
    count, expires = _memory_counters.get(key, (0, now + ttl_seconds))
    if expires < now:
        count, expires = 0, now + ttl_seconds
    count += 1
    _memory_counters[key] = (count, expires)
    return count


def set_value(key: str, value: Any, ttl_seconds: int) -> None:
    client = get_redis()
    if client is not None:
        try:
            client.set(key, value, ex=ttl_seconds)
            return
        except Exception:  # noqa: BLE001, S110
            pass
    _memory_values[key] = (value, time.time() + ttl_seconds)


def get_value(key: str) -> Any:
    client = get_redis()
    if client is not None:
        try:
            value = client.get(key)
            return value.decode() if isinstance(value, bytes) else value
        except Exception:  # noqa: BLE001, S110
            pass
    entry = _memory_values.get(key)
    if entry is None:
        return None
    value, expires = entry
    if expires < time.time():
        _memory_values.pop(key, None)
        return None
    return value


def list_push(key: str, value: str) -> int:
    client = get_redis()
    if client is not None:
        try:
            return int(client.rpush(key, value))
        except Exception:  # noqa: BLE001, S110
            pass
    bucket = _memory_lists.setdefault(key, [])
    bucket.append(value)
    return len(bucket)


def list_pop(key: str) -> str | None:
    client = get_redis()
    if client is not None:
        try:
            value = client.lpop(key)
            return value.decode() if isinstance(value, bytes) else value
        except Exception:  # noqa: BLE001, S110
            pass
    bucket = _memory_lists.get(key)
    if not bucket:
        return None
    return bucket.pop(0)


def reset_state() -> None:
    """测试用：重置客户端与内存回退。"""
    global _client, _unavailable
    _client = None
    _unavailable = False
    _memory_counters.clear()
    _memory_values.clear()
    _memory_lists.clear()
