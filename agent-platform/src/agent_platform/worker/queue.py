"""worker 异步任务队列（Redis list，不可用时降级为进程内队列）。"""
from __future__ import annotations

import json
from typing import Any

from agent_platform.core.redis import list_pop, list_push

QUEUE_KEY = "ap:jobs"


def enqueue(job_type: str, payload: dict[str, Any] | None = None) -> str:
    job = {"type": job_type, "payload": payload or {}}
    list_push(QUEUE_KEY, json.dumps(job, ensure_ascii=False))
    return job_type


def dequeue() -> dict[str, Any] | None:
    raw = list_pop(QUEUE_KEY)
    if raw is None:
        return None
    return json.loads(raw)
