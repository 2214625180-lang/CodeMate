import json
from collections.abc import Iterator, Sequence
from typing import Any

from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
    get_checkpoint_metadata,
)
from langchain_core.runnables import RunnableConfig
from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

from app.models.agent_checkpoint import (
    AgentCheckpoint,
    AgentCheckpointBlob,
    AgentCheckpointWrite,
)


class SQLAlchemyCheckpointSaver(BaseCheckpointSaver):
    """LangGraph machine-state persistence keyed by ``AgentRun.id``.

    Checkpoints, channel blobs and pending writes support deterministic recovery;
    they are distinct from the redacted, human-readable AgentStep timeline.
    """

    def __init__(self, session_factory: sessionmaker):
        super().__init__()
        self.session_factory = session_factory

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        configurable = config["configurable"]
        thread_id = str(configurable["thread_id"])
        checkpoint_ns = str(configurable.get("checkpoint_ns", ""))
        checkpoint_id = get_checkpoint_id(config)
        with self.session_factory() as db:
            statement = select(AgentCheckpoint).where(
                AgentCheckpoint.thread_id == thread_id,
                AgentCheckpoint.checkpoint_ns == checkpoint_ns,
            )
            if checkpoint_id:
                statement = statement.where(AgentCheckpoint.checkpoint_id == checkpoint_id)
            else:
                statement = statement.order_by(AgentCheckpoint.checkpoint_id.desc()).limit(1)
            record = db.execute(statement).scalar_one_or_none()
            if record is None:
                return None
            return self._checkpoint_tuple(db, record)

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        with self.session_factory() as db:
            statement = select(AgentCheckpoint)
            if config:
                configurable = config["configurable"]
                statement = statement.where(
                    AgentCheckpoint.thread_id == str(configurable["thread_id"])
                )
                if "checkpoint_ns" in configurable:
                    statement = statement.where(
                        AgentCheckpoint.checkpoint_ns
                        == str(configurable.get("checkpoint_ns", ""))
                    )
                if checkpoint_id := get_checkpoint_id(config):
                    statement = statement.where(AgentCheckpoint.checkpoint_id == checkpoint_id)
            if before and (before_id := get_checkpoint_id(before)):
                statement = statement.where(AgentCheckpoint.checkpoint_id < before_id)
            statement = statement.order_by(AgentCheckpoint.checkpoint_id.desc())
            records = db.execute(statement).scalars().all()
            emitted = 0
            for record in records:
                checkpoint_tuple = self._checkpoint_tuple(db, record)
                if filter and not all(
                    checkpoint_tuple.metadata.get(key) == value for key, value in filter.items()
                ):
                    continue
                if limit is not None and emitted >= limit:
                    break
                emitted += 1
                yield checkpoint_tuple

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        configurable = config["configurable"]
        thread_id = str(configurable["thread_id"])
        checkpoint_ns = str(configurable.get("checkpoint_ns", ""))
        checkpoint_copy = checkpoint.copy()
        channel_values: dict[str, Any] = checkpoint_copy.pop("channel_values")  # type: ignore[misc]
        checkpoint_type, checkpoint_blob = self.serde.dumps_typed(checkpoint_copy)
        metadata_type, metadata_blob = self.serde.dumps_typed(
            get_checkpoint_metadata(config, metadata)
        )
        with self.session_factory.begin() as db:
            for channel, version in new_versions.items():
                value_type, value_blob = (
                    self.serde.dumps_typed(channel_values[channel])
                    if channel in channel_values
                    else ("empty", b"")
                )
                db.merge(
                    AgentCheckpointBlob(
                        thread_id=thread_id,
                        checkpoint_ns=checkpoint_ns,
                        channel=channel,
                        version=self._version_key(version),
                        value_type=value_type,
                        value_blob=value_blob,
                    )
                )
            db.merge(
                AgentCheckpoint(
                    thread_id=thread_id,
                    checkpoint_ns=checkpoint_ns,
                    checkpoint_id=str(checkpoint["id"]),
                    parent_checkpoint_id=configurable.get("checkpoint_id"),
                    checkpoint_type=checkpoint_type,
                    checkpoint_blob=checkpoint_blob,
                    metadata_type=metadata_type,
                    metadata_blob=metadata_blob,
                )
            )
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        configurable = config["configurable"]
        thread_id = str(configurable["thread_id"])
        checkpoint_ns = str(configurable.get("checkpoint_ns", ""))
        checkpoint_id = str(configurable["checkpoint_id"])
        with self.session_factory.begin() as db:
            for position, (channel, value) in enumerate(writes):
                write_index = WRITES_IDX_MAP.get(channel, position)
                key = (thread_id, checkpoint_ns, checkpoint_id, task_id, write_index)
                existing = db.get(AgentCheckpointWrite, key)
                if existing is not None and write_index >= 0:
                    continue
                value_type, value_blob = self.serde.dumps_typed(value)
                db.merge(
                    AgentCheckpointWrite(
                        thread_id=thread_id,
                        checkpoint_ns=checkpoint_ns,
                        checkpoint_id=checkpoint_id,
                        task_id=task_id,
                        write_index=write_index,
                        channel=channel,
                        value_type=value_type,
                        value_blob=value_blob,
                        task_path=task_path,
                    )
                )

    def delete_thread(self, thread_id: str) -> None:
        with self.session_factory.begin() as db:
            db.execute(
                delete(AgentCheckpointWrite).where(AgentCheckpointWrite.thread_id == thread_id)
            )
            db.execute(
                delete(AgentCheckpointBlob).where(AgentCheckpointBlob.thread_id == thread_id)
            )
            db.execute(
                delete(AgentCheckpoint).where(AgentCheckpoint.thread_id == thread_id)
            )

    def _checkpoint_tuple(self, db, record: AgentCheckpoint) -> CheckpointTuple:
        checkpoint: Checkpoint = self.serde.loads_typed(
            (record.checkpoint_type, bytes(record.checkpoint_blob))
        )
        channel_values: dict[str, Any] = {}
        for channel, version in checkpoint["channel_versions"].items():
            blob = db.get(
                AgentCheckpointBlob,
                (
                    record.thread_id,
                    record.checkpoint_ns,
                    channel,
                    self._version_key(version),
                ),
            )
            if blob is not None and blob.value_type != "empty":
                channel_values[channel] = self.serde.loads_typed(
                    (blob.value_type, bytes(blob.value_blob))
                )
        writes = (
            db.execute(
                select(AgentCheckpointWrite)
                .where(
                    AgentCheckpointWrite.thread_id == record.thread_id,
                    AgentCheckpointWrite.checkpoint_ns == record.checkpoint_ns,
                    AgentCheckpointWrite.checkpoint_id == record.checkpoint_id,
                )
                .order_by(AgentCheckpointWrite.task_id, AgentCheckpointWrite.write_index)
            )
            .scalars()
            .all()
        )
        resolved_config: RunnableConfig = {
            "configurable": {
                "thread_id": record.thread_id,
                "checkpoint_ns": record.checkpoint_ns,
                "checkpoint_id": record.checkpoint_id,
            }
        }
        parent_config = None
        if record.parent_checkpoint_id:
            parent_config = {
                "configurable": {
                    "thread_id": record.thread_id,
                    "checkpoint_ns": record.checkpoint_ns,
                    "checkpoint_id": record.parent_checkpoint_id,
                }
            }
        return CheckpointTuple(
            config=resolved_config,
            checkpoint={**checkpoint, "channel_values": channel_values},
            metadata=self.serde.loads_typed(
                (record.metadata_type, bytes(record.metadata_blob))
            ),
            parent_config=parent_config,
            pending_writes=[
                (
                    write.task_id,
                    write.channel,
                    self.serde.loads_typed((write.value_type, bytes(write.value_blob))),
                )
                for write in writes
            ],
        )

    @staticmethod
    def _version_key(version: Any) -> str:
        return json.dumps(version, ensure_ascii=False, sort_keys=True, default=str)
