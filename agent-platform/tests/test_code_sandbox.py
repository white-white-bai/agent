"""代码节点沙箱：默认进程内行为、Docker 隔离参数、超时与失败处理。"""
from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from agent_platform.engine import code_sandbox
from agent_platform.engine.code_sandbox import CodeExecutionError, run_code
from agent_platform.graph.schema import CodeConfig, CodeInput


def _settings(**overrides):
    data = {
        "code_sandbox_mode": "docker",
        "code_sandbox_image": "python:3.11-slim",
        "code_sandbox_timeout_seconds": 5.0,
        "code_sandbox_memory": "128m",
        "code_sandbox_cpus": "0.5",
        "code_sandbox_pids_limit": 64,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _config(**overrides):
    data = {
        "code": "def main(**inputs):\n    return {'doubled': inputs['n'] * 2, 'extra': 'x'}\n",
        "inputs": [CodeInput(name="n", expression="n")],
        "outputs": ["doubled"],
        "timeout_ms": 1000,
    }
    data.update(overrides)
    return CodeConfig(**data)


def test_inprocess_mode_keeps_legacy_behavior(monkeypatch):
    monkeypatch.setattr(code_sandbox, "get_settings", lambda: _settings(code_sandbox_mode="inprocess"))

    assert run_code(_config(outputs=[]), {"n": 21}) == {"doubled": 42, "extra": "x"}


def test_docker_mode_builds_isolated_command(monkeypatch):
    calls: list[tuple[list[str], dict]] = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"doubled": 42, "extra": "x"}), stderr="")

    monkeypatch.setattr(code_sandbox, "get_settings", lambda: _settings())
    monkeypatch.setattr(code_sandbox.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(code_sandbox.subprocess, "run", fake_run)

    assert run_code(_config(), {"n": 21}) == {"doubled": 42}
    command, kwargs = calls[0]
    assert command[0] == "/usr/bin/docker"
    assert command[command.index("--network") + 1] == "none"
    assert "--read-only" in command
    assert command[command.index("--user") + 1] == "65534:65534"
    assert "--cap-drop" in command and "ALL" in command
    assert command[command.index("--memory") + 1] == "128m"
    assert command[command.index("--pids-limit") + 1] == "64"
    assert kwargs["timeout"] == 1.0
    assert json.loads(kwargs["input"])["inputs"] == {"n": 21}


def test_docker_missing_binary_fails_closed(monkeypatch):
    monkeypatch.setattr(code_sandbox, "get_settings", lambda: _settings())
    monkeypatch.setattr(code_sandbox.shutil, "which", lambda name: None)

    with pytest.raises(CodeExecutionError, match="未找到 docker"):
        run_code(_config(), {"n": 21})


def test_docker_timeout_kills_container(monkeypatch):
    cleanup: list[list[str]] = []

    def fake_run(command, **kwargs):
        if command[1] == "rm":
            cleanup.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        raise subprocess.TimeoutExpired(command, 1.0)

    monkeypatch.setattr(code_sandbox, "get_settings", lambda: _settings())
    monkeypatch.setattr(code_sandbox.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(code_sandbox.subprocess, "run", fake_run)

    with pytest.raises(CodeExecutionError, match="超时"):
        run_code(_config(), {"n": 21})
    assert cleanup and cleanup[0][1:3] == ["rm", "-f"]


def test_docker_nonzero_exit_reports_stderr(monkeypatch):
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="boom")

    monkeypatch.setattr(code_sandbox, "get_settings", lambda: _settings())
    monkeypatch.setattr(code_sandbox.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(code_sandbox.subprocess, "run", fake_run)

    with pytest.raises(CodeExecutionError, match="boom"):
        run_code(_config(), {"n": 21})


def test_docker_image_allowlist_and_output_limit(monkeypatch):
    monkeypatch.setattr(code_sandbox.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(
        code_sandbox,
        "get_settings",
        lambda: _settings(code_sandbox_allowed_images="other:latest"),
    )
    with pytest.raises(CodeExecutionError, match="白名单"):
        run_code(_config(), {"n": 21})

    def huge_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="x" * 100, stderr="")

    monkeypatch.setattr(
        code_sandbox,
        "get_settings",
        lambda: _settings(code_sandbox_max_output_bytes=10),
    )
    monkeypatch.setattr(code_sandbox.subprocess, "run", huge_run)
    with pytest.raises(CodeExecutionError, match="输出超过上限"):
        run_code(_config(), {"n": 21})
