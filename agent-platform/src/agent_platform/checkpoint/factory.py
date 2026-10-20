"""checkpointer 工厂：自主 agent 用（长期记忆 + HITL 中断/续跑）。

仅 agent 应用路径使用；工作流对话路径不传 checkpointer，行为与改造前一致。
"""
from __future__ import annotations

from agent_platform.checkpoint.mysql import MySQLCheckpointSaver

_saver: MySQLCheckpointSaver | None = None


def build_checkpointer(settings=None) -> MySQLCheckpointSaver:
    """返回进程级单例（saver 无状态，每次操作自开 session）。"""
    global _saver
    if _saver is None:
        _saver = MySQLCheckpointSaver()
    return _saver
