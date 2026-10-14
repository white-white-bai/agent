"""worker 入口：从 Redis 队列消费任务并执行（无任务时空转轮询）。"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from agent_platform.core.db import init_db
from agent_platform.worker.jobs import handle_job
from agent_platform.worker.queue import dequeue

logger = logging.getLogger("agent_platform.worker")

POLL_INTERVAL_SECONDS = 1.0


async def run_once() -> bool:
    """取一个任务执行；队列为空返回 False。"""
    job = dequeue()
    if job is None:
        return False
    try:
        result = await handle_job(job)
        logger.info("任务完成 type=%s result=%s", job.get("type"), result)
    except Exception:
        logger.exception("任务失败 type=%s", job.get("type"))
    return True


async def serve() -> None:
    init_db()
    logger.info("worker 启动，开始消费队列")
    while True:
        handled = await run_once()
        if not handled:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)


def main() -> Any:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve())


if __name__ == "__main__":
    main()
