from agent_platform.checkpoint.mysql import MySQLCheckpointSaver


def test_put_and_get_roundtrip():
    saver = MySQLCheckpointSaver()
    config = {"configurable": {"thread_id": "thread-a"}}
    saved = saver.put(
        config,
        {"id": "cp-1", "channel_values": {"answer": "hi"}, "v": 1},
        {"source": "input", "step": 0, "parents": {}},
        {},
    )
    assert saved["configurable"]["checkpoint_id"] == "cp-1"

    result = saver.get_tuple(config)
    assert result is not None
    assert result.checkpoint["id"] == "cp-1"
    assert result.checkpoint["channel_values"]["answer"] == "hi"
    assert result.metadata["source"] == "input"


def test_get_tuple_missing_returns_none():
    saver = MySQLCheckpointSaver()
    assert saver.get_tuple({"configurable": {"thread_id": "nope"}}) is None


def test_put_writes_roundtrip():
    saver = MySQLCheckpointSaver()
    config = {"configurable": {"thread_id": "thread-b"}}
    saver.put(config, {"id": "cp-2", "channel_values": {}, "v": 1}, {"source": "loop", "step": 1}, {})
    saver.put_writes({"configurable": {"thread_id": "thread-b", "checkpoint_id": "cp-2"}}, [("answer", "x")], "task-1")
    result = saver.get_tuple(config)
    assert result.pending_writes is not None
    assert result.pending_writes[0] == ("task-1", "answer", "x")
