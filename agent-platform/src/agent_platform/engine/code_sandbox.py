"""代码节点执行：默认受限进程内 exec，可切换 Docker 隔离沙箱。

`AP_CODE_SANDBOX_MODE=inprocess`（默认）保持旧行为；`docker` 模式在隔离容器中执行，
禁用网络、只读根文件系统、非 root，并限制 CPU / 内存 / PID / 超时。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import uuid
from typing import Any

from agent_platform.core.config import get_settings
from agent_platform.engine.expr import evaluate
from agent_platform.graph.schema import CodeConfig

_SAFE_BUILTINS = {
    "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict, "enumerate": enumerate,
    "float": float, "int": int, "len": len, "list": list, "max": max, "min": min, "range": range,
    "round": round, "set": set, "sorted": sorted, "str": str, "sum": sum, "tuple": tuple, "zip": zip,
    "ValueError": ValueError, "Exception": Exception, "print": None,
}

_DOCKER_RUNNER = textwrap.dedent(
    """
    import json
    import sys

    out = sys.stdout
    sys.stdout = sys.stderr
    payload = json.load(sys.stdin)
    scope = {}
    exec(compile(payload["code"], "<code_node>", "exec"), scope)
    main = scope.get("main")
    if not callable(main):
        raise SystemExit("代码节点必须定义 main(**inputs) 函数")
    result = main(**payload.get("inputs", {}))
    if result is None:
        result = {}
    if not isinstance(result, dict):
        raise SystemExit("代码节点 main 必须返回 dict")
    out.write(json.dumps(result, ensure_ascii=False, default=str))
    """
).strip()


class CodeExecutionError(Exception):
    pass


def _inputs(config: CodeConfig, variables: dict[str, Any]) -> dict[str, Any]:
    return {item.name: evaluate(item.expression, variables) for item in config.inputs}


def _shape_result(config: CodeConfig, result: Any) -> dict[str, Any]:
    if result is None:
        result = {}
    if not isinstance(result, dict):
        raise CodeExecutionError("代码节点 main 必须返回 dict")
    if config.outputs:
        return {name: result.get(name) for name in config.outputs}
    return result


def _run_inprocess(config: CodeConfig, variables: dict[str, Any]) -> dict[str, Any]:
    inputs = _inputs(config, variables)
    sandbox_globals: dict[str, Any] = {"__builtins__": _SAFE_BUILTINS}
    try:
        exec(compile(config.code, "<code_node>", "exec"), sandbox_globals)
        main = sandbox_globals.get("main")
        if not callable(main):
            raise CodeExecutionError("代码节点必须定义 main(**inputs) 函数")
        result = main(**inputs)
    except CodeExecutionError:
        raise
    except Exception as exc:
        raise CodeExecutionError(f"代码节点执行失败: {exc}") from exc
    return _shape_result(config, result)


def _run_docker(config: CodeConfig, variables: dict[str, Any], settings: Any) -> dict[str, Any]:
    docker = shutil.which("docker")
    if not docker:
        raise CodeExecutionError("代码沙箱不可用：未找到 docker（AP_CODE_SANDBOX_MODE=docker）")
    inputs = _inputs(config, variables)
    payload = json.dumps(
        {"code": config.code, "inputs": inputs}, ensure_ascii=False, default=str
    )
    image = str(getattr(settings, "code_sandbox_image", "python:3.11-slim") or "python:3.11-slim")
    allowed = [
        item.strip()
        for item in str(getattr(settings, "code_sandbox_allowed_images", "") or "").split(",")
        if item.strip()
    ]
    if allowed and image not in allowed:
        raise CodeExecutionError(f"代码沙箱镜像不在白名单：{image}")
    if getattr(settings, "code_sandbox_require_pinned_image", False) and not _pinned(image):
        raise CodeExecutionError(f"代码沙箱镜像未固定摘要：{image}")
    required_runtime = str(getattr(settings, "code_sandbox_required_runtime", "") or "")
    runtime = str(getattr(settings, "code_sandbox_runtime", "") or "")
    if required_runtime and runtime != required_runtime:
        raise CodeExecutionError(f"代码沙箱 runtime 不符：期望 {required_runtime}，实际 {runtime or '(默认)'}")
    container_name = f"ap-code-{uuid.uuid4().hex}"
    timeout = max(
        0.1,
        min(
            float(config.timeout_ms or 3000) / 1000.0,
            float(getattr(settings, "code_sandbox_timeout_seconds", 5.0) or 5.0),
        ),
    )
    command = [
        docker,
        "run",
        "--rm",
        "-i",
        "--name",
        container_name,
        "--network",
        "none",
        "--read-only",
        "--user",
        "65534:65534",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--log-driver",
        "none",
    ]
    runtime = str(getattr(settings, "code_sandbox_runtime", "") or "")
    if runtime:
        command.extend(["--runtime", runtime])
    seccomp = str(getattr(settings, "code_sandbox_seccomp_profile", "") or "")
    if seccomp:
        command.extend(["--security-opt", f"seccomp={seccomp}"])
    command.extend(
        [
            "--ipc",
            "none",
            "--init",
            "--stop-timeout",
            "1",
            "--ulimit",
            "nofile=64:64",
            "--ulimit",
            "nproc=64:64",
            "--memory",
            str(getattr(settings, "code_sandbox_memory", "128m") or "128m"),
            "--memory-swap",
            str(getattr(settings, "code_sandbox_memory", "128m") or "128m"),
            "--cpus",
            str(getattr(settings, "code_sandbox_cpus", "0.5") or "0.5"),
            "--pids-limit",
            str(int(getattr(settings, "code_sandbox_pids_limit", 64) or 64)),
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=16m",
            image,
            "python",
            "-I",
            "-B",
            "-c",
            _DOCKER_RUNNER,
        ]
    )
    try:
        completed = subprocess.run(
            command,
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        subprocess.run(
            [docker, "rm", "-f", container_name],
            capture_output=True,
            text=True,
            check=False,
        )
        raise CodeExecutionError(f"代码沙箱执行超时（{timeout:.1f}s）") from exc
    max_output = int(getattr(settings, "code_sandbox_max_output_bytes", 65536) or 65536)
    output_size = len((completed.stdout or "").encode("utf-8")) + len(
        (completed.stderr or "").encode("utf-8")
    )
    if output_size > max_output:
        raise CodeExecutionError(f"代码沙箱输出超过上限：{output_size} > {max_output} bytes")
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[:500]
        raise CodeExecutionError(f"代码沙箱执行失败: {detail}")
    try:
        result = json.loads((completed.stdout or "").strip())
    except json.JSONDecodeError as exc:
        raise CodeExecutionError("代码沙箱返回非 JSON 结果") from exc
    return _shape_result(config, result)


def _pinned(image: str) -> bool:
    return "@sha256:" in (image or "")


def sandbox_status(settings: Any = None) -> dict[str, Any]:
    """返回沙箱策略自检结果；不启动容器，只检查配置与 docker 可执行文件。"""
    settings = settings or get_settings()
    mode = str(getattr(settings, "code_sandbox_mode", "inprocess") or "inprocess").lower()
    image = str(getattr(settings, "code_sandbox_image", "python:3.11-slim") or "python:3.11-slim")
    runtime = str(getattr(settings, "code_sandbox_runtime", "") or "")
    required_runtime = str(getattr(settings, "code_sandbox_required_runtime", "") or "")
    require_isolation = bool(getattr(settings, "code_sandbox_require_isolation", False))
    require_pinned = bool(getattr(settings, "code_sandbox_require_pinned_image", False))
    docker = shutil.which("docker")
    allowed = [
        item.strip()
        for item in str(getattr(settings, "code_sandbox_allowed_images", "") or "").split(",")
        if item.strip()
    ]
    issues: list[str] = []
    if mode not in ("inprocess", "docker"):
        issues.append(f"未知沙箱模式：{mode}")
    if require_isolation:
        if mode != "docker":
            issues.append("要求隔离但 AP_CODE_SANDBOX_MODE 不是 docker")
        if not docker:
            issues.append("要求隔离但未找到 docker")
    if mode == "docker" and not docker:
        issues.append("docker 模式但未找到 docker")
    if allowed and image not in allowed:
        issues.append(f"镜像不在白名单：{image}")
    if require_pinned and not _pinned(image):
        issues.append(f"镜像未固定摘要：{image}")
    if required_runtime and runtime != required_runtime:
        issues.append(f"runtime 不符：期望 {required_runtime}，实际 {runtime or '(默认)'}")
    return {
        "mode": mode,
        "docker_available": bool(docker),
        "image": image,
        "image_pinned": _pinned(image),
        "runtime": runtime,
        "required_runtime": required_runtime,
        "require_isolation": require_isolation,
        "require_pinned_image": require_pinned,
        "issues": issues,
        "ready": not issues,
    }


def assert_sandbox_ready(settings: Any = None) -> dict[str, Any]:
    """启动/执行前校验策略；强制隔离不满足时失败关闭。"""
    status = sandbox_status(settings)
    enforced = (
        status["require_isolation"]
        or status["require_pinned_image"]
        or bool(status["required_runtime"])
    )
    if enforced and not status["ready"]:
        raise CodeExecutionError("代码沙箱未满足强制隔离：" + "；".join(status["issues"]))
    return status


def run_code(config: CodeConfig, variables: dict[str, Any]) -> dict[str, Any]:
    if not config.code.strip():
        raise CodeExecutionError("代码节点为空")
    settings = get_settings()
    status = assert_sandbox_ready(settings)
    mode = status["mode"]
    if mode == "docker":
        return _run_docker(config, variables, settings)
    return _run_inprocess(config, variables)
