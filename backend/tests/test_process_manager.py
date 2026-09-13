"""进程管理模块测试（本项目最易出 bug 的部分）。

不依赖 sherpa-onnx：用一段「假 server」Python 脚本替代真实推理进程，覆盖
端口分配、启动就绪判定、并发限制、异常自动重启、资源采集等关键路径。
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app import process_manager as pmmod
from app.config import settings
from app.errors import (
    ModelAlreadyRunningError,
    ModelNotDownloadedError,
    ResourceLimitError,
    StartError,
)
from app.registry import HealthSpec, ModelFile, ModelSource, ModelSpec, StartSpec

FAKE_SERVER = textwrap.dedent(
    """
    import argparse
    import json
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"status": "ok"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
    """
)


# --------------------------------------------------------------------------- 夹具
@pytest.fixture
async def pm(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "model_dir", tmp_path / "models")
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "start_timeout", 20.0)
    monkeypatch.setattr(settings, "stop_timeout", 5.0)
    monkeypatch.setattr(settings, "port_pool_start", 7601)
    monkeypatch.setattr(settings, "port_pool_end", 7605)
    monkeypatch.setattr(settings, "max_running_models", 2)
    monkeypatch.setattr(settings, "max_restart_attempts", 3)
    monkeypatch.setattr(pmmod, "RESTART_BACKOFF", 0.05)
    settings.ensure_dirs()

    manager = pmmod.ProcessManager(settings)
    try:
        yield manager
    finally:
        await manager.shutdown()


@pytest.fixture
def registry(monkeypatch):
    """用内存字典替换 registry 查询。"""
    specs: dict[str, ModelSpec] = {}

    def fake_get_spec(model_id: str) -> ModelSpec:
        if model_id not in specs:
            raise KeyError(f"未知模型: {model_id}")
        return specs[model_id]

    monkeypatch.setattr(pmmod, "get_spec", fake_get_spec)
    return specs


@pytest.fixture
def server_script(tmp_path: Path) -> Path:
    path = tmp_path / "fake_server.py"
    path.write_text(FAKE_SERVER, encoding="utf-8")
    return path


def build_spec(
    model_id: str,
    script: Path,
    *,
    command: str = "{python}",
    args: list[str] | None = None,
    health: str = "http",
) -> ModelSpec:
    base = settings.model_dir / model_id
    base.mkdir(parents=True, exist_ok=True)
    (base / "dummy.txt").write_text("ok", encoding="utf-8")
    return ModelSpec(
        id=model_id,
        name=model_id,
        type="tts",
        source=ModelSource(repo="test/local", mirrors=["http://127.0.0.1:1/{file}"]),
        files=[ModelFile(key="dummy", path="dummy.txt")],
        start=StartSpec(
            command=command,
            args=args if args is not None else [str(script), "--port={port}"],
            cwd="model_dir",
            health=HealthSpec(kind=health, path="/health"),
            startup_grace=0.0,
        ),
    )


# --------------------------------------------------------------------- 端口池
def test_port_pool_allocates_and_releases() -> None:
    pool = pmmod.PortPool(7801, 7803)
    assert pool.acquire("a") == 7801
    assert pool.acquire("a") == 7801  # 幂等
    assert pool.acquire("b") == 7802
    pool.release("a")
    assert pool.acquire("c") == 7801
    assert pool.acquire("d") == 7803

    with pytest.raises(ResourceLimitError):
        pool.acquire("e")

    pool.release("b")
    assert pool.acquire("e") == 7802


def test_port_pool_skips_port_occupied_by_other_process() -> None:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
        blocker.bind(("127.0.0.1", 7811))
        blocker.listen(1)
        pool = pmmod.PortPool(7811, 7812)
        assert pool.acquire("x") == 7812  # 7811 被占用，跳到 7812


# ------------------------------------------------------------------ 启动/停止
async def test_start_and_stop(pm, registry, server_script: Path) -> None:
    registry["pm-demo"] = build_spec("pm-demo", server_script)

    state = await pm.start("pm-demo")
    assert state.running is True
    assert state.status == "running"
    assert settings.port_pool_start <= state.port <= settings.port_pool_end
    assert state.pid and state.pid > 0
    assert pm.running_count == 1
    assert pm.port_of("pm-demo") == state.port

    # 重复启动应当被拒绝
    with pytest.raises(ModelAlreadyRunningError):
        await pm.start("pm-demo")

    stopped = await pm.stop("pm-demo")
    assert stopped.running is False
    assert stopped.status == "stopped"
    assert stopped.port is None
    assert pm.running_count == 0
    assert pm._ports.assigned == {}


async def test_start_requires_downloaded_files(pm, registry, server_script: Path) -> None:
    spec = build_spec("pm-empty", server_script)
    (settings.model_dir / "pm-empty" / "dummy.txt").unlink()
    registry["pm-empty"] = spec

    with pytest.raises(ModelNotDownloadedError):
        await pm.start("pm-empty")


async def test_unknown_command_reports_clear_error(pm, registry, server_script: Path) -> None:
    registry["pm-nocmd"] = build_spec(
        "pm-nocmd",
        server_script,
        command="definitely-not-a-real-binary-xyz",
    )
    with pytest.raises(StartError, match="未找到可执行文件"):
        await pm.start("pm-nocmd")


async def test_process_exiting_before_ready_is_start_error(pm, registry, server_script: Path) -> None:
    registry["pm-crash-start"] = build_spec(
        "pm-crash-start",
        server_script,
        args=["-c", "import sys; sys.exit(3)"],
        health="tcp",
    )
    with pytest.raises(StartError, match="未就绪"):
        await pm.start("pm-crash-start", wait_ready=True)
    assert pm.running_count == 0
    assert pm._ports.assigned == {}


async def test_concurrency_limit(pm, registry, server_script: Path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_running_models", 1)
    registry["pm-a"] = build_spec("pm-a", server_script)
    registry["pm-b"] = build_spec("pm-b", server_script)

    await pm.start("pm-a")
    with pytest.raises(ResourceLimitError, match="上限"):
        await pm.start("pm-b")

    # 停掉 a 之后 b 可以启动，且端口被回收复用
    await pm.stop("pm-a")
    state = await pm.start("pm-b")
    assert state.running is True


# ---------------------------------------------------------------- 健康检查
async def test_auto_restart_after_crash(pm, registry, server_script: Path) -> None:
    registry["pm-restart"] = build_spec("pm-restart", server_script)

    state = await pm.start("pm-restart")
    old_pid = state.pid

    rp = pm._procs["pm-restart"]
    rp.process.kill()
    await rp.process.wait()

    await pm._check_one("pm-restart")

    restarted = pm.get_state("pm-restart")
    assert restarted.running is True
    assert restarted.restart_count == 1
    assert restarted.pid != old_pid
    assert pm.running_count == 1


async def test_no_restart_when_attempts_exhausted(
    pm, registry, server_script: Path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "max_restart_attempts", 0)
    registry["pm-dead"] = build_spec("pm-dead", server_script)

    await pm.start("pm-dead")
    rp = pm._procs["pm-dead"]
    rp.process.kill()
    await rp.process.wait()

    await pm._check_one("pm-dead")

    state = pm.get_state("pm-dead")
    assert state.running is False
    assert state.status == "error"
    assert state.last_error
    assert pm.running_count == 0


async def test_health_check_keeps_healthy_process(pm, registry, server_script: Path) -> None:
    registry["pm-healthy"] = build_spec("pm-healthy", server_script)
    await pm.start("pm-healthy")

    await pm._check_one("pm-healthy")

    state = pm.get_state("pm-healthy")
    assert state.running is True
    assert state.restart_count == 0


# ---------------------------------------------------------------- 资源监控
async def test_resource_usage_reports_process(pm, registry, server_script: Path) -> None:
    registry["pm-usage"] = build_spec("pm-usage", server_script)
    await pm.start("pm-usage")

    usage = pm.resource_usage()
    assert len(usage) == 1
    item = usage[0]
    assert item["model_id"] == "pm-usage"
    assert item["memory_mb"] > 0
    assert item["uptime_seconds"] >= 0


# -------------------------------------------------------------------- 日志
async def test_tail_log_returns_lines(pm, registry, server_script: Path) -> None:
    registry["pm-log"] = build_spec("pm-log", server_script)
    await pm.start("pm-log")

    log_path = pm.log_path_of("pm-log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("\n".join(f"line-{i}" for i in range(50)), encoding="utf-8")

    tail = pm.tail_log("pm-log", lines=5)
    assert tail.splitlines() == [f"line-{i}" for i in range(45, 50)]
