"""下载管理模块。

- 后台 asyncio 任务，按 ``models.yaml`` 中声明的文件清单下载到 ``models/{model_id}/``
- 多个镜像源之间自动 fallback（国内优先 ModelScope，失败再走 HuggingFace）
- 单文件失败自动重试（指数退避），并实时更新进度
- 进度既保存在内存（供接口实时查询 / SSE 推送），也落库（历史记录）
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx
from pydantic import BaseModel
from sqlmodel import select

from .config import Settings, settings
from .db import session_scope
from .errors import (
    DownloadError,
    ModelAlreadyDownloadingError,
    ModelNotFoundError,
)
from .models import DownloadTask, ModelState, utcnow
from .registry import ModelSpec, get_registry, get_spec, model_dir_of

CHUNK_SIZE = 1024 * 256  # 256 KiB


class DownloadProgress(BaseModel):
    """对外暴露的下载进度快照。"""

    model_id: str
    status: str = "pending"
    progress: float = 0.0
    total_files: int = 0
    completed_files: int = 0
    downloaded_bytes: int = 0
    current_file: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


@dataclass
class _Job:
    """内存中的下载任务。"""

    model_id: str
    spec: ModelSpec
    task_id: int | None = None
    status: str = "pending"
    total_files: int = 0
    completed_files: int = 0
    downloaded_bytes: int = 0
    current_file: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    runner: asyncio.Task[None] | None = None

    @property
    def progress(self) -> float:
        if self.status == "completed":
            return 1.0
        if not self.total_files:
            return 0.0
        return min(self.completed_files / self.total_files, 1.0)

    def snapshot(self) -> DownloadProgress:
        return DownloadProgress(
            model_id=self.model_id,
            status=self.status,
            progress=round(self.progress, 4),
            total_files=self.total_files,
            completed_files=self.completed_files,
            downloaded_bytes=self.downloaded_bytes,
            current_file=self.current_file,
            error=self.error,
            started_at=self.started_at,
            finished_at=self.finished_at,
        )


def missing_files(spec: ModelSpec) -> list[str]:
    """返回尚未下载（或大小为 0）的文件路径。"""
    base = model_dir_of(spec.id)
    return [
        item.path
        for item in spec.files
        if not (base / item.path).is_file() or (base / item.path).stat().st_size == 0
    ]


def is_downloaded(spec: ModelSpec) -> bool:
    return not missing_files(spec)


def downloaded_size(spec: ModelSpec) -> int:
    base = model_dir_of(spec.id)
    total = 0
    for item in spec.files:
        path = base / item.path
        if path.is_file():
            with contextlib.suppress(OSError):
                total += path.stat().st_size
    return total


class DownloadManager:
    """下载任务管理器。"""

    def __init__(self, config: Settings | None = None) -> None:
        self.settings = config or settings
        self._jobs: dict[str, _Job] = {}

    # ------------------------------------------------------------- 查询
    def active_job(self, model_id: str) -> _Job | None:
        job = self._jobs.get(model_id)
        if job and job.status in ("pending", "running"):
            return job
        return None

    def is_downloading(self, model_id: str) -> bool:
        return self.active_job(model_id) is not None

    def get_progress(self, model_id: str) -> DownloadProgress:
        """返回进度：优先内存中的实时任务，其次数据库历史。"""
        job = self._jobs.get(model_id)
        if job is not None:
            return job.snapshot()

        spec = get_spec(model_id)
        with session_scope() as session:
            record = session.exec(
                select(DownloadTask)
                .where(DownloadTask.model_id == model_id)
                .order_by(DownloadTask.id.desc())  # type: ignore[union-attr]
                .limit(1)
            ).first()

        if record is None:
            return DownloadProgress(
                model_id=model_id,
                status="completed" if is_downloaded(spec) else "idle",
                progress=1.0 if is_downloaded(spec) else 0.0,
                total_files=len(spec.files),
                completed_files=len(spec.files) if is_downloaded(spec) else 0,
                downloaded_bytes=downloaded_size(spec),
            )

        return DownloadProgress(
            model_id=model_id,
            status=record.status,
            progress=record.progress,
            total_files=record.total_files,
            completed_files=record.completed_files,
            downloaded_bytes=record.downloaded_bytes,
            current_file=record.current_file,
            error=record.error,
            started_at=record.created_at,
            finished_at=record.finished_at,
        )

    # ------------------------------------------------------------- 控制
    async def start(self, model_id: str, force: bool = False) -> DownloadProgress:
        """启动下载任务（幂等：已在下载则直接返回当前进度）。"""
        try:
            spec = get_spec(model_id)
        except KeyError as exc:
            raise ModelNotFoundError(str(exc)) from exc

        if self.is_downloading(model_id):
            if not force:
                return self._jobs[model_id].snapshot()
            raise ModelAlreadyDownloadingError(f"模型 {model_id} 正在下载中")

        if is_downloaded(spec) and not force:
            job = _Job(model_id=model_id, spec=spec, status="completed")
            job.completed_files = len(spec.files)
            job.total_files = len(spec.files)
            job.downloaded_bytes = downloaded_size(spec)
            job.started_at = job.finished_at = utcnow()
            self._jobs[model_id] = job
            return job.snapshot()

        job = _Job(
            model_id=model_id,
            spec=spec,
            status="pending",
            total_files=len(spec.files),
            started_at=utcnow(),
        )
        self._jobs[model_id] = job
        job.task_id = self._create_task_record(job)
        job.runner = asyncio.create_task(self._run(job), name=f"download:{model_id}")
        return job.snapshot()

    async def cancel(self, model_id: str) -> DownloadProgress:
        job = self._jobs.get(model_id)
        if job is None or job.status not in ("pending", "running"):
            return self.get_progress(model_id)

        job.cancel_event.set()
        if job.runner is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(job.runner), timeout=5)
        return job.snapshot()

    async def shutdown(self) -> None:
        """服务退出时取消所有下载任务。"""
        for job in list(self._jobs.values()):
            if job.status in ("pending", "running"):
                job.cancel_event.set()
        runners = [j.runner for j in self._jobs.values() if j.runner is not None]
        for runner in runners:
            runner.cancel()
        for runner in runners:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await runner

    # ------------------------------------------------------------- 内部
    def _create_task_record(self, job: _Job) -> int:
        with session_scope() as session:
            record = DownloadTask(
                model_id=job.model_id,
                status="running",
                total_files=len(job.spec.files),
                created_at=utcnow(),
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return int(record.id or 0)

    def _persist(self, job: _Job, *, finished: bool = False) -> None:
        with session_scope() as session:
            record = session.get(DownloadTask, job.task_id) if job.task_id else None
            if record is not None:
                record.status = job.status
                record.progress = round(job.progress, 4)
                record.completed_files = job.completed_files
                record.downloaded_bytes = job.downloaded_bytes
                record.current_file = job.current_file
                record.error = job.error
                if finished:
                    record.finished_at = utcnow()
                session.add(record)

            state = session.get(ModelState, job.model_id) or ModelState(
                model_id=job.model_id
            )
            state.download_progress = round(job.progress, 4)
            state.downloaded = job.status == "completed"
            state.size_bytes = downloaded_size(job.spec)
            if job.status == "failed":
                state.last_error = job.error
            state.updated_at = utcnow()
            session.add(state)
            session.commit()

    async def _run(self, job: _Job) -> None:
        job.status = "running"
        job.started_at = utcnow()
        try:
            base = model_dir_of(job.model_id)
            base.mkdir(parents=True, exist_ok=True)

            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.download_timeout, connect=15.0),
                follow_redirects=True,
                headers={"User-Agent": "sherpa-model-hub/0.1"},
            ) as client:
                for item in job.spec.files:
                    if job.cancel_event.is_set():
                        job.status = "cancelled"
                        break

                    target = base / item.path
                    if target.is_file() and target.stat().st_size > 0:
                        job.completed_files += 1
                        job.downloaded_bytes += target.stat().st_size
                        continue

                    job.current_file = item.path
                    job.error = None
                    await self._download_file(client, job, item.path, target)
                    job.completed_files += 1
                    job.current_file = None
                    self._persist(job)

            if job.cancel_event.is_set() and job.status == "running":
                job.status = "cancelled"
            elif job.status == "running":
                job.status = "completed"
                if not is_downloaded(job.spec):  # 兜底校验
                    raise DownloadError("下载结束后仍有文件缺失，请重试")
        except asyncio.CancelledError:
            job.status = "cancelled"
            job.error = job.error or "下载任务已被取消"
            raise
        except Exception as exc:  # noqa: BLE001 - 需要兜底记录任何失败原因
            job.status = "failed"
            job.error = str(exc)
        finally:
            job.finished_at = utcnow()
            self._persist(job, finished=True)

    async def _download_file(
        self,
        client: httpx.AsyncClient,
        job: _Job,
        file_path: str,
        target: Path,
    ) -> None:
        """带重试与多镜像 fallback 的单文件下载。"""
        urls = job.spec.source.urls_for(file_path)
        if not urls:
            raise DownloadError(
                f"模型 {job.model_id} 未配置下载源，请在模型详情页上传模型文件"
            )

        attempts = max(self.settings.download_retries, len(urls))
        last_error: Exception | None = None

        for attempt in range(attempts):
            if job.cancel_event.is_set():
                raise asyncio.CancelledError
            url = urls[attempt % len(urls)]
            try:
                await self._stream_to_file(client, url, target, job)
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - 记录后重试下一个源
                last_error = exc
                job.error = f"{url} -> {exc}"
                if attempt < attempts - 1:
                    delay = min(self.settings.download_backoff * (2**attempt), 30.0)
                    await asyncio.sleep(delay)

        detail = str(last_error)
        if "404" in detail:
            detail += "（提示：上游仓库文件清单可能有变，请核对 models.yaml 中的 files）"
        raise DownloadError(f"下载 {file_path} 失败：{detail}")

    async def _stream_to_file(
        self,
        client: httpx.AsyncClient,
        url: str,
        target: Path,
        job: _Job,
    ) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".part")

        try:
            async with client.stream("GET", url) as response:
                if response.status_code >= 400:
                    raise DownloadError(
                        f"HTTP {response.status_code} {response.reason_phrase}"
                    )
                with tmp.open("wb") as fh:
                    async for chunk in response.aiter_bytes(CHUNK_SIZE):
                        if job.cancel_event.is_set():
                            raise asyncio.CancelledError
                        if not chunk:
                            continue
                        fh.write(chunk)
                        job.downloaded_bytes += len(chunk)
        except BaseException:
            with contextlib.suppress(OSError):
                tmp.unlink()
            raise

        if not tmp.exists() or tmp.stat().st_size == 0:
            with contextlib.suppress(OSError):
                tmp.unlink()
            raise DownloadError("下载内容为空")

        os.replace(tmp, target)


_manager: DownloadManager | None = None


def get_download_manager() -> DownloadManager:
    global _manager
    if _manager is None:
        _manager = DownloadManager()
    return _manager


def validate_registry_downloads() -> None:
    """服务启动时校正数据库里的 downloaded 状态（文件可能被手工删除）。"""
    with session_scope() as session:
        for spec in get_registry().values():
            missing = missing_files(spec)
            state = session.get(ModelState, spec.id)
            if state is None:
                state = ModelState(model_id=spec.id)
            state.downloaded = not missing
            state.size_bytes = downloaded_size(spec)
            if not missing:
                state.download_progress = 1.0
            state.updated_at = utcnow()
            session.add(state)
        session.commit()
