"""自研 MySQL checkpointer（复用现有 MySQL，图状态与会话同库）。"""
from __future__ import annotations

import asyncio
from collections.abc import Iterator, Sequence
from typing import Any

from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    CheckpointTuple,
    get_checkpoint_metadata,
)
from sqlalchemy import delete, select

from agent_platform.core.db import session_scope
from agent_platform.domain.models import Checkpoint as CheckpointRow
from agent_platform.domain.models import CheckpointWrite as CheckpointWriteRow


class MySQLCheckpointSaver(BaseCheckpointSaver):
    def _parts(self, config: dict[str, Any] | None) -> tuple[str, str, str | None]:
        configurable = (config or {}).get("configurable") or {}
        thread_id = configurable.get("thread_id")
        if not thread_id:
            raise ValueError("checkpointer 需要 configurable.thread_id")
        return (
            str(thread_id),
            str(configurable.get("checkpoint_ns", "")),
            configurable.get("checkpoint_id"),
        )

    def get_tuple(self, config: dict[str, Any]) -> CheckpointTuple | None:
        thread_id, checkpoint_ns, checkpoint_id = self._parts(config)
        with session_scope() as session:
            stmt = select(CheckpointRow).where(
                CheckpointRow.thread_id == thread_id,
                CheckpointRow.checkpoint_ns == checkpoint_ns,
            )
            if checkpoint_id:
                stmt = stmt.where(CheckpointRow.checkpoint_id == checkpoint_id)
            else:
                stmt = stmt.order_by(CheckpointRow.id.desc())
            row = session.scalars(stmt).first()
            if row is None:
                return None

            writes = session.scalars(
                select(CheckpointWriteRow)
                .where(
                    CheckpointWriteRow.thread_id == thread_id,
                    CheckpointWriteRow.checkpoint_ns == checkpoint_ns,
                    CheckpointWriteRow.checkpoint_id == row.checkpoint_id,
                )
                .order_by(
                    CheckpointWriteRow.task_path,
                    CheckpointWriteRow.task_id,
                    CheckpointWriteRow.idx,
                )
            ).all()

            checkpoint = self.serde.loads_typed((row.type, row.checkpoint))
            metadata = self.serde.loads_typed((row.metadata_type, row.metadata_blob))
            pending_writes = [
                (w.task_id, w.channel, self.serde.loads_typed((w.type, w.value))) for w in writes
            ]
            new_config = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": row.checkpoint_id,
                }
            }
            parent_config = None
            if row.parent_checkpoint_id:
                parent_config = {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": row.parent_checkpoint_id,
                    }
                }
            return CheckpointTuple(
                config=new_config,
                checkpoint=checkpoint,
                metadata=metadata,
                parent_config=parent_config,
                pending_writes=pending_writes or None,
            )

    def list(
        self,
        config: dict[str, Any] | None,
        *,
        filter: dict[str, Any] | None = None,
        before: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        configurable = (config or {}).get("configurable") or {}
        thread_id = configurable.get("thread_id")
        checkpoint_ns = configurable.get("checkpoint_ns")
        config_checkpoint_id = configurable.get("checkpoint_id")
        before_checkpoint_id = ((before or {}).get("configurable") or {}).get("checkpoint_id")

        with session_scope() as session:
            stmt = select(CheckpointRow)
            if config is not None:
                if not thread_id:
                    raise ValueError("checkpointer 需要 configurable.thread_id")
                stmt = stmt.where(CheckpointRow.thread_id == str(thread_id))
                if checkpoint_ns is not None:
                    stmt = stmt.where(CheckpointRow.checkpoint_ns == str(checkpoint_ns))
                if config_checkpoint_id:
                    stmt = stmt.where(CheckpointRow.checkpoint_id == str(config_checkpoint_id))
            rows = session.scalars(stmt.order_by(CheckpointRow.id.desc())).all()

        remaining = limit
        for row in rows:
            if before_checkpoint_id and row.checkpoint_id >= str(before_checkpoint_id):
                continue
            result = self.get_tuple(
                {
                    "configurable": {
                        "thread_id": row.thread_id,
                        "checkpoint_ns": row.checkpoint_ns,
                        "checkpoint_id": row.checkpoint_id,
                    }
                }
            )
            if result is None:
                continue
            if filter and not all(result.metadata.get(key) == value for key, value in filter.items()):
                continue
            if remaining is not None:
                if remaining <= 0:
                    break
                remaining -= 1
            yield result

    def put(
        self,
        config: dict[str, Any],
        checkpoint: dict[str, Any],
        metadata: dict[str, Any],
        new_versions: dict[str, Any],
    ) -> dict[str, Any]:
        thread_id, checkpoint_ns, parent_checkpoint_id = self._parts(config)
        checkpoint_id = checkpoint["id"]
        merged_metadata = get_checkpoint_metadata(config, metadata)
        cp_type, cp_blob = self.serde.dumps_typed(checkpoint)
        md_type, md_blob = self.serde.dumps_typed(merged_metadata)
        with session_scope() as session:
            session.execute(
                delete(CheckpointRow).where(
                    CheckpointRow.thread_id == thread_id,
                    CheckpointRow.checkpoint_ns == checkpoint_ns,
                    CheckpointRow.checkpoint_id == checkpoint_id,
                )
            )
            session.add(
                CheckpointRow(
                    thread_id=thread_id,
                    checkpoint_ns=checkpoint_ns,
                    checkpoint_id=checkpoint_id,
                    parent_checkpoint_id=parent_checkpoint_id,
                    type=cp_type,
                    checkpoint=cp_blob,
                    metadata_type=md_type,
                    metadata_blob=md_blob,
                )
            )
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }

    def put_writes(
        self,
        config: dict[str, Any],
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread_id, checkpoint_ns, checkpoint_id = self._parts(config)
        if not checkpoint_id:
            raise ValueError("put_writes 需要 configurable.checkpoint_id")
        with session_scope() as session:
            for offset, (channel, value) in enumerate(writes):
                idx = WRITES_IDX_MAP.get(channel, offset)
                if idx >= 0:
                    existing = session.scalar(
                        select(CheckpointWriteRow.id).where(
                            CheckpointWriteRow.thread_id == thread_id,
                            CheckpointWriteRow.checkpoint_ns == checkpoint_ns,
                            CheckpointWriteRow.checkpoint_id == checkpoint_id,
                            CheckpointWriteRow.task_id == task_id,
                            CheckpointWriteRow.idx == idx,
                        )
                    )
                    if existing is not None:
                        continue
                else:
                    session.execute(
                        delete(CheckpointWriteRow).where(
                            CheckpointWriteRow.thread_id == thread_id,
                            CheckpointWriteRow.checkpoint_ns == checkpoint_ns,
                            CheckpointWriteRow.checkpoint_id == checkpoint_id,
                            CheckpointWriteRow.task_id == task_id,
                            CheckpointWriteRow.idx == idx,
                        )
                    )
                value_type, value_blob = self.serde.dumps_typed(value)
                session.add(
                    CheckpointWriteRow(
                        thread_id=thread_id,
                        checkpoint_ns=checkpoint_ns,
                        checkpoint_id=checkpoint_id,
                        task_id=task_id,
                        task_path=task_path,
                        idx=idx,
                        channel=channel,
                        type=value_type,
                        value=value_blob,
                    )
                )

    def delete_thread(self, thread_id: str) -> None:
        with session_scope() as session:
            session.execute(delete(CheckpointWriteRow).where(CheckpointWriteRow.thread_id == thread_id))
            session.execute(delete(CheckpointRow).where(CheckpointRow.thread_id == thread_id))

    async def aget_tuple(self, config: dict[str, Any]) -> CheckpointTuple | None:
        return await asyncio.to_thread(self.get_tuple, config)

    async def alist(
        self,
        config: dict[str, Any] | None,
        *,
        filter: dict[str, Any] | None = None,
        before: dict[str, Any] | None = None,
        limit: int | None = None,
    ):
        items = await asyncio.to_thread(
            lambda: list(self.list(config, filter=filter, before=before, limit=limit))
        )
        for item in items:
            yield item

    async def aput(
        self,
        config: dict[str, Any],
        checkpoint: dict[str, Any],
        metadata: dict[str, Any],
        new_versions: dict[str, Any],
    ) -> dict[str, Any]:
        return await asyncio.to_thread(self.put, config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: dict[str, Any],
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        await asyncio.to_thread(self.put_writes, config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id: str) -> None:
        await asyncio.to_thread(self.delete_thread, thread_id)
