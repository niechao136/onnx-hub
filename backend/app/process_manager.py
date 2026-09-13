"""进程管理模块（Runner）。

核心职责：把 ``models.yaml`` 中的启动模板渲染成真实命令行，以子进程方式拉起
sherpa-onnx 官方 server，并负责端口分配、健康检查、异常自动重启与并发限制。

设计要点（对应设计文档「关键技术难点」）：
- 内部端口从固定池（默认 7001-7099）分配，对外由网关屏蔽
- 健康检查 = 进程存活 + TCP/HTTP 探活，连续失败判定为僵死
- 自动重启有次数上限，避免崩溃进程被无限拉起
- 同时运行数量受 ``HUB_MAX_RUNNING_MODELS`` 限制，超限直接给出明确提示
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx
import psutil
from sqlmodel import select

from .config import BACKEND_DIR, Settings, settings
from .db import session_scope
from .downloader import downloaded_size, is_downloaded, missing_files
from .errors import (
    ModelAlreadyRunningError,
    ModelNotFoundError,
    ModelNotDownloadedError,
    ResourceLimitError,
    StartError,
)
from .models import ModelState, utcnow
from .registry import ModelSpec, get_registry, get_spec, model_dir_of, render_context

logger = logging.getLogger(__name__)

#: 连续探活失败多少次判定进程僵死
HEALTH_FAILURE_THRESHOLD = 3
#: 自动重启前的退避时间（秒）
RESTART_BACKOFF = 2.0


class PortPool:
    """内部端口池，保证同一时刻一个端口只分配给一个模型。"""

    def __init__(self, start: int, end: int) -> None:
        if start > end:
            raise ValueError("端口池范围非法: start 必须小于等于 end")
        self.start = start
        self.end = end
        self._assigned: dict[str, int] = {}
        self._in_use: set[int] = set()

    def acquire(self, key: str) -> int:
        """为 ``key`` 分配一个空闲且真正可绑定的端口（幂等）。"""
        if key in self._assigned:
            return self._assigned[key]

        for port in range(self.start, self.end + 1):
            if port in self._in_use:
                continue
            if not self.is_port_free(port):
                continue
            self._assigned[key] = port
            self._in_use.add(port)
            return port

        raise ResourceLimitError(
            f"内部端口池 {self.start}-{self.end} 已耗尽，无法为新模型分配端口"
        )

    def release(self, key: str) -> None:
        port = self._assigned.pop(key, None)
        if port is not None:
            self._in_use.discard(port)

    def reset(self) -> None:
        self._assigned.clear()
        self._in_use.clear()

    @property
    def assigned(self) -> dict[str, int]:
        return dict(self._assigned)

    @staticmethod
    def is_port_free(port: int) -> bool:
        """通过尝试绑定判断端口是否空闲。"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                return False
        return True


@dataclass
class RunningProcess:
    """内存中的运行态进程描述。"""

    model_id: str
    port: int
    pid: int
    process: asyncio.subprocess.Process
    log_path: Path
    log_file: object
    started_at: datetime
    restart_count: int = 0
    status: str = "running"
    health_failures: int = 0
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    ps: psutil.Process | None = field(default=None)

    @property
    def alive(self) -> bool:
        return self.process.returncode is None


class ProcessManager:
    """sherpa-onnx 子进程生命周期管理器。"""

    def __init__(self, config: Settings | None = None) -> None:
        self.settings = config or settings
        self._ports = PortPool(self.settings.port_pool_start, self.settings.port_pool_end)
        self._procs: dict[str, RunningProcess] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._health_task: asyncio.Task[None] | None = None
        self._stopping = False

    # ------------------------------------------------------------------ 工具
    def _lock(self, model_id: str) -> asyncio.Lock:
        lock = self._locks.get(model_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[model_id] = lock
        return lock

    def _spec(self, model_id: str) -> ModelSpec:
        try:
            return get_spec(model_id)
        except KeyError as exc:
            raise ModelNotFoundError(str(exc)) from exc

    @property
    def running_count(self) -> int:
        return sum(1 for rp in self._procs.values() if rp.alive)

    def port_of(self, model_id: str) -> int | None:
        rp = self._procs.get(model_id)
        return rp.port if rp and rp.alive else None

    def log_path_of(self, model_id: str) -> Path:
        return self.settings.log_dir / f"{model_id}.log"

    # ------------------------------------------------------------ 状态查询
    def get_state(self, model_id: str) -> ModelState:
        spec = self._spec(model_id)
        with session_scope() as session:
            state = session.get(ModelState, model_id) or ModelState(model_id=model_id)
        self._fill_download(spec, state)
        self._overlay_runtime(model_id, state)
        return state

    def list_states(self) -> list[ModelState]:
        specs = list(get_registry().values())
        with session_scope() as session:
            rows = {row.model_id: row for row in session.exec(select(ModelState)).all()}

        states: list[ModelState] = []
        for spec in specs:
            state = rows.get(spec.id) or ModelState(model_id=spec.id)
            self._fill_download(spec, state)
            self._overlay_runtime(spec.id, state)
            states.append(state)
        return states

    def _fill_download(self, spec: ModelSpec, state: ModelState) -> None:
        downloaded = is_downloaded(spec)
        state.downloaded = downloaded
        state.size_bytes = downloaded_size(spec)
        if downloaded:
            state.download_progress = 1.0

    def _overlay_runtime(self, model_id: str, state: ModelState) -> None:
        """用内存中的真实运行态覆盖数据库状态。"""
        rp = self._procs.get(model_id)
        if rp is not None and rp.alive:
            state.running = True
            state.status = rp.status
            state.port = rp.port
            state.pid = rp.pid
            state.restart_count = rp.restart_count
        elif rp is None and state.running:
            # 内存中已无记录（例如服务重启过），以停止态为准
            state.running = False
            state.status = state.last_error and "error" or "stopped"
            state.port = None
            state.pid = None

    def _persist_state(self, model_id: str, **changes: object) -> ModelState:
        with session_scope() as session:
            state = session.get(ModelState, model_id) or ModelState(model_id=model_id)
            for key, value in changes.items():
                setattr(state, key, value)
            state.updated_at = utcnow()
            session.add(state)
            session.commit()
            session.refresh(state)
            return state

    def get_auto_restart(self, model_id: str) -> bool:
        with session_scope() as session:
            state = session.get(ModelState, model_id)
            return bool(state.auto_restart) if state else True

    # ---------------------------------------------------------------- 启动
    async def start(self, model_id: str, *, wait_ready: bool = True) -> ModelState:
        spec = self._spec(model_id)
        async with self._lock(model_id):
            existing = self._procs.get(model_id)
            if existing is not None and existing.alive:
                raise ModelAlreadyRunningError(f"模型 {model_id} 已在运行中（端口 {existing.port}）")

            missing = missing_files(spec)
            if missing:
                raise ModelNotDownloadedError(
                    f"模型 {model_id} 尚未下载完整，缺少 {len(missing)} 个文件："
                    + ", ".join(missing[:5])
                )

            self._check_capacity(exclude=model_id)
            await self._spawn(spec, restart_count=0, wait_ready=wait_ready)
        return self.get_state(model_id)

    def _check_capacity(self, exclude: str | None = None) -> None:
        limit = self.settings.max_running_models
        running = [mid for mid, rp in self._procs.items() if rp.alive and mid != exclude]
        if len(running) >= limit:
            raise ResourceLimitError(
                f"同时运行的模型数量已达上限（{limit}），请先停止其他模型：" + ", ".join(running)
            )

    async def _spawn(
        self,
        spec: ModelSpec,
        *,
        restart_count: int,
        wait_ready: bool = True,
    ) -> RunningProcess:
        port = self._ports.acquire(spec.id)
        log_path = self.log_path_of(spec.id)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            command, args = spec.render(render_context(spec, port))
            executable = self._resolve_command(command)
            cwd = self._cwd_for(spec)
        except Exception:
            self._ports.release(spec.id)
            raise

        self._persist_state(
            spec.id,
            status="starting",
            running=False,
            port=port,
            last_error=None,
            restart_count=restart_count,
        )

        log_file = open(log_path, "ab", buffering=0)  # noqa: SIM115 - 需长期持有
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        kwargs: dict[str, object] = {}
        if os.name == "nt":  # pragma: no cover - 平台相关
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
                | subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
            )
        else:
            kwargs["start_new_session"] = True

        logger.info("启动模型 %s: %s %s (port=%s)", spec.id, executable, " ".join(args), port)
        try:
            process = await asyncio.create_subprocess_exec(
                executable,
                *args,
                cwd=str(cwd),
                env=env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=log_file,
                stderr=asyncio.subprocess.STDOUT,
                **kwargs,  # type: ignore[arg-type]
            )
        except Exception as exc:
            log_file.close()
            self._ports.release(spec.id)
            message = f"启动进程失败: {exc}"
            self._persist_state(spec.id, status="error", running=False, last_error=message)
            raise StartError(message) from exc

        if not wait_ready:
            rp = self._register(spec, port, process, log_path, log_file, restart_count)
            return rp

        ready = await self._wait_ready(spec, port, process)
        if not ready:
            tail = self.tail_log(spec.id, lines=20)
            await self._terminate(process)
            log_file.close()
            self._ports.release(spec.id)
            message = (
                f"进程启动后 {self.settings.start_timeout:.0f}s 内端口 {port} 仍未就绪，"
                f"请检查日志。\n{tail}"
            )
            self._persist_state(spec.id, status="error", running=False, last_error=message)
            raise StartError(message)

        return self._register(spec, port, process, log_path, log_file, restart_count)

    def _register(
        self,
        spec: ModelSpec,
        port: int,
        process: asyncio.subprocess.Process,
        log_path: Path,
        log_file: object,
        restart_count: int,
    ) -> RunningProcess:
        rp = RunningProcess(
            model_id=spec.id,
            port=port,
            pid=process.pid or -1,
            process=process,
            log_path=log_path,
            log_file=log_file,
            started_at=utcnow(),
            restart_count=restart_count,
            ps=self._psutil_process(process.pid),
        )
        self._procs[spec.id] = rp
        self._persist_state(
            spec.id,
            running=True,
            status="running",
            port=port,
            pid=rp.pid,
            restart_count=restart_count,
            last_error=None,
        )
        return rp

    def _cwd_for(self, spec: ModelSpec) -> Path:
        if spec.start.cwd == "backend_dir":
            return BACKEND_DIR
        path = model_dir_of(spec.id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _resolve_command(self, command: str) -> str:
        """把命令解析为可执行的绝对路径。"""
        candidate = Path(command)
        looks_like_path = candidate.is_absolute() or any(
            sep in command for sep in ("/", "\\")
        )
        if candidate.is_absolute():
            if candidate.exists():
                return str(candidate)
            raise StartError(f"启动命令不存在: {command}")

        if looks_like_path:
            for base in (BACKEND_DIR, Path.cwd()):
                probe = base / command
                if probe.exists():
                    return str(probe)
            found = shutil.which(command)
            if found:
                return found
            raise StartError(f"启动命令不存在: {command}")

        if command == sys.executable:
            return command
        found = shutil.which(command)
        if found:
            return found
        raise StartError(
            f"未找到可执行文件 '{command}'。请确认已安装 sherpa-onnx release 包并加入 PATH，"
            f"或在 models.yaml 的 start.command 中填写绝对路径（Windows 下注意 .exe 后缀）。"
        )

    # ---------------------------------------------------------------- 停止
    async def stop(self, model_id: str) -> ModelState:
        self._spec(model_id)
        async with self._lock(model_id):
            rp = self._procs.get(model_id)
            if rp is None:
                self._persist_state(
                    model_id,
                    running=False,
                    status="stopped",
                    port=None,
                    pid=None,
                    restart_count=0,
                )
                return self.get_state(model_id)

            self._persist_state(model_id, status="stopping")
            await self._terminate(rp.process)
            self._release(rp)
            self._persist_state(
                model_id,
                running=False,
                status="stopped",
                port=None,
                pid=None,
                restart_count=0,
            )
        return self.get_state(model_id)

    async def restart(self, model_id: str) -> ModelState:
        self._spec(model_id)
        if model_id in self._procs:
            await self.stop(model_id)
        return await self.start(model_id)

    def _release(self, rp: RunningProcess) -> None:
        self._procs.pop(rp.model_id, None)
        self._ports.release(rp.model_id)
        with contextlib.suppress(Exception):
            rp.log_file.close()  # type: ignore[attr-defined]

    async def _terminate(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        with contextlib.suppress(ProcessLookupError, OSError):
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=self.settings.stop_timeout)
        except asyncio.TimeoutError:
            logger.warning("进程 %s 未能优雅退出，强制结束", process.pid)
            with contextlib.suppress(ProcessLookupError, OSError):
                process.kill()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(process.wait(), timeout=5)

    # ------------------------------------------------------------ 健康检查
    async def start_health_loop(self) -> None:
        if self._health_task is None or self._health_task.done():
            self._stopping = False
            self._health_task = asyncio.create_task(
                self._health_loop(), name="process-health-check"
            )

    async def stop_health_loop(self) -> None:
        self._stopping = True
        task = self._health_task
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            self._health_task = None

    async def _health_loop(self) -> None:
        interval = self.settings.health_check_interval
        while not self._stopping:
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                raise
            if self._stopping:
                break
            for model_id in list(self._procs.keys()):
                try:
                    await self._check_one(model_id)
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001 - 健康检查必须自身健壮
                    logger.exception("健康检查 %s 时发生异常", model_id)

    async def _check_one(self, model_id: str) -> None:
        rp = self._procs.get(model_id)
        if rp is None:
            return
        spec = self._spec(model_id)

        # 顺带采样一次 CPU，让后续监控接口拿到真实增量
        self._sample_resource(rp)

        if not rp.alive:
            await self._handle_dead(
                spec, rp, reason=f"进程已退出（返回码 {rp.process.returncode}）"
            )
            return

        if await self._probe(spec, rp.port):
            if rp.health_failures:
                rp.health_failures = 0
                if rp.restart_count:
                    rp.restart_count = 0
                    self._persist_state(model_id, restart_count=0)
            return

        rp.health_failures += 1
        if rp.health_failures >= HEALTH_FAILURE_THRESHOLD:
            await self._handle_dead(
                spec,
                rp,
                reason=f"端口 {rp.port} 连续 {rp.health_failures} 次探活失败",
            )

    async def _handle_dead(
        self, spec: ModelSpec, rp: RunningProcess, *, reason: str
    ) -> None:
        tail = self.tail_log(spec.id, lines=10)
        await self._terminate(rp.process)
        restart_count = rp.restart_count
        self._release(rp)

        message = f"{reason}\n{tail}".strip()
        auto_restart = self.get_auto_restart(spec.id)
        can_restart = auto_restart and restart_count < self.settings.max_restart_attempts

        if not can_restart:
            self._persist_state(
                spec.id,
                running=False,
                status="error",
                port=None,
                pid=None,
                restart_count=restart_count,
                last_error=(
                    message
                    if auto_restart
                    else f"{message}\n（自动重启已关闭或已达上限，未再次拉起）"
                ),
            )
            logger.error("模型 %s 异常停止，不再重启: %s", spec.id, reason)
            return

        attempt = restart_count + 1
        logger.warning(
            "模型 %s 异常停止，%ss 后第 %s/%s 次自动重启: %s",
            spec.id,
            RESTART_BACKOFF,
            attempt,
            self.settings.max_restart_attempts,
            reason,
        )
        self._persist_state(
            spec.id,
            running=False,
            status="restarting",
            port=None,
            pid=None,
            restart_count=attempt,
            last_error=message,
        )
        await asyncio.sleep(RESTART_BACKOFF)
        async with self._lock(spec.id):
            try:
                await self._spawn(spec, restart_count=attempt)
            except Exception as exc:  # noqa: BLE001 - 重启失败要落库并停止尝试
                logger.error("模型 %s 第 %s 次自动重启失败: %s", spec.id, attempt, exc)
                self._persist_state(
                    spec.id,
                    running=False,
                    status="error",
                    port=None,
                    pid=None,
                    restart_count=attempt,
                    last_error=f"{message}\n自动重启失败: {exc}",
                )

    async def _probe(self, spec: ModelSpec, port: int) -> bool:
        health = spec.start.health
        if health.kind == "http":
            url = f"http://127.0.0.1:{port}{health.path}"
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    response = await client.get(url)
                return response.status_code < 500
            except Exception:  # noqa: BLE001
                return False

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", port), timeout=3.0
            )
        except Exception:  # noqa: BLE001
            return False
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
        del reader
        return True

    async def _wait_ready(
        self, spec: ModelSpec, port: int, process: asyncio.subprocess.Process
    ) -> bool:
        deadline = asyncio.get_running_loop().time() + self.settings.start_timeout
        while asyncio.get_running_loop().time() < deadline:
            if process.returncode is not None:
                return False
            if await self._probe(spec, port):
                if spec.start.startup_grace:
                    await asyncio.sleep(spec.start.startup_grace)
                return True
            await asyncio.sleep(0.5)
        return False

    # ---------------------------------------------------------------- 日志
    def tail_log(self, model_id: str, lines: int | None = None) -> str:
        path = self.log_path_of(model_id)
        if not path.exists():
            return ""
        count = lines or self.settings.log_tail_lines
        try:
            with path.open("rb") as fh:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                block = 8192
                data = b""
                while size > 0 and data.count(b"\n") <= count:
                    step = min(block, size)
                    size -= step
                    fh.seek(size)
                    data = fh.read(step) + data
            text = data.decode("utf-8", errors="replace")
        except OSError as exc:  # pragma: no cover
            return f"<读取日志失败: {exc}>"
        return "\n".join(text.splitlines()[-count:])

    # ------------------------------------------------------------ 资源监控
    @staticmethod
    def _psutil_process(pid: int | None) -> psutil.Process | None:
        if not pid or pid <= 0:
            return None
        try:
            return psutil.Process(pid)
        except psutil.Error:
            return None

    def _sample_resource(self, rp: RunningProcess) -> None:
        if rp.ps is None:
            rp.ps = self._psutil_process(rp.pid)
        if rp.ps is None:
            return
        try:
            rp.cpu_percent = rp.ps.cpu_percent(interval=None)
            with rp.ps.oneshot():
                rp.memory_mb = rp.ps.memory_info().rss / (1024 * 1024)
        except psutil.Error:
            rp.ps = None

    def resource_usage(self) -> list[dict[str, object]]:
        usage: list[dict[str, object]] = []
        for model_id, rp in self._procs.items():
            if not rp.alive:
                continue
            self._sample_resource(rp)
            uptime = (utcnow() - rp.started_at).total_seconds()
            usage.append(
                {
                    "model_id": model_id,
                    "pid": rp.pid,
                    "port": rp.port,
                    "status": rp.status,
                    "restart_count": rp.restart_count,
                    "uptime_seconds": round(uptime, 1),
                    "cpu_percent": round(rp.cpu_percent, 2),
                    "memory_mb": round(rp.memory_mb, 2),
                }
            )
        return usage

    # ------------------------------------------------------------ 生命周期
    def reconcile(self) -> None:
        """服务启动时清理上次遗留的进程与状态（单机部署下的孤儿进程）。"""
        self._ports.reset()
        with session_scope() as session:
            for row in session.exec(select(ModelState)).all():
                if row.pid:
                    self._kill_pid(row.pid)
                row.running = False
                row.status = "stopped"
                row.port = None
                row.pid = None
                row.restart_count = 0
                session.add(row)
            session.commit()

    @staticmethod
    def _kill_pid(pid: int) -> None:
        if pid <= 0 or pid == os.getpid():
            return
        try:
            proc = psutil.Process(pid)
        except psutil.Error:
            return
        with contextlib.suppress(psutil.Error):
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except psutil.TimeoutExpired:
                proc.kill()

    async def shutdown(self) -> None:
        """停止所有子进程（服务退出时调用）。"""
        await self.stop_health_loop()
        for model_id in list(self._procs.keys()):
            rp = self._procs.get(model_id)
            if rp is None:
                continue
            await self._terminate(rp.process)
            self._release(rp)
            self._persist_state(
                model_id, running=False, status="stopped", port=None, pid=None
            )


_manager: ProcessManager | None = None


def get_process_manager() -> ProcessManager:
    global _manager
    if _manager is None:
        _manager = ProcessManager()
    return _manager
