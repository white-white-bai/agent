"""自研 MySQL checkpointer（复用现有 MySQL，图状态与会话同库）。"""
from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple
from sqlalchemy import delete, select

from agent_platform.core.db import session_scope
from agent_platform.domain.models import Checkpoint as CheckpointRow
from agent_platform.domain.models import CheckpointWrite as CheckpointWriteRow


class MySQLCheckpointSaver(BaseCheckpointSaver):
    def _parts(self, config: dict[str, Any]) -> tuple[str, str, str | None]:
        configurable = config["configurable"]
        return (
            configurable["thread_id"],
            configurable.get("checkpoint_ns", ""),
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
                .order_by(CheckpointWriteRow.task_id, CheckpointWriteRow.idx)
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
        config = config or {}
        thread_id, checkpoint_ns, _ = self._parts(config)
        with session_scope() as session:
            stmt = (
                select(CheckpointRow)
                .where(
                    CheckpointRow.thread_id == thread_id,
                    CheckpointRow.checkpoint_ns == checkpoint_ns,
                )
                .order_by(CheckpointRow.id.desc())
            )
            if limit:
                stmt = stmt.limit(limit)
            rows = session.scalars(stmt).all()
        for row in rows:
            result = self.get_tuple(
                {
                    "configurable": {
                        "thread_id": row.thread_id,
                        "checkpoint_ns": row.checkpoint_ns,
                        "checkpoint_id": row.checkpoint_id,
                    }
                }
            )
            if result is not None:
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
        cp_type, cp_blob = self.serde.dumps_typed(checkpoint)
        md_type, md_blob = self.serde.dumps_typed(metadata)
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
        with session_scope() as session:
            session.execute(
                delete(CheckpointWriteRow).where(
                    CheckpointWriteRow.thread_id == thread_id,
                    CheckpointWriteRow.checkpoint_ns == checkpoint_ns,
                    CheckpointWriteRow.checkpoint_id == checkpoint_id,
                    CheckpointWriteRow.task_id == task_id,
                )
            )
            for idx, (channel, value) in enumerate(writes):
                value_type, value_blob = self.serde.dumps_typed(value)
                session.add(
                    CheckpointWriteRow(
                        thread_id=thread_id,
                        checkpoint_ns=checkpoint_ns,
                        checkpoint_id=checkpoint_id,
                        task_id=task_id,
                        idx=idx,
                        channel=channel,
                        type=value_type,
                        value=value_blob,
                    )
                )

    async def aget_tuple(self, config: dict[str, Any]) -> CheckpointTuple | None:
        return self.get_tuple(config)

    async def alist(
        self,
        config: dict[str, Any] | None,
        *,
        filter: dict[str, Any] | None = None,
        before: dict[str, Any] | None = None,
        limit: int | None = None,
    ):
        for item in self.list(config, filter=filter, before=before, limit=limit):
            yield item

    async def aput(
        self,
        config: dict[str, Any],
        checkpoint: dict[str, Any],
        metadata: dict[str, Any],
        new_versions: dict[str, Any],
    ) -> dict[str, Any]:
        return self.put(config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: dict[str, Any],
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        self.put_writes(config, writes, task_id, task_path)
