"""对外 API 的请求/响应模型。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .models import ApiKey, ModelState
from .registry import ModelSpec, model_dir_of


class ModelFileInfo(BaseModel):
    key: str
    path: str
    exists: bool
    size_bytes: int = 0


class ModelInfo(BaseModel):
    """模型目录条目 + 实时状态。"""

    id: str
    name: str
    type: str
    language: str = ""
    description: str = ""
    memory_mb: int = 0
    tags: list[str] = Field(default_factory=list)

    downloaded: bool = False
    download_progress: float = 0.0
    size_bytes: int = 0
    running: bool = False
    status: str = "stopped"
    port: int | None = None
    pid: int | None = None
    restart_count: int = 0
    last_error: str | None = None

    gateway_path: str = ""
    source_repo: str = ""
    source_mirrors: list[str] = Field(default_factory=list)
    files: list[ModelFileInfo] = Field(default_factory=list)
    start_command: str = ""
    start_args: list[str] = Field(default_factory=list)
    start_cwd: str = "model_dir"
    health_check: str = "tcp"
    health_path: str = "/health"
    #: builtin = models.yaml 预置；custom = 用户创建
    origin: str = "builtin"
    #: 是否配置了下载源（false 表示需要手动上传文件）
    downloadable: bool = True


def to_model_info(spec: ModelSpec, state: ModelState) -> ModelInfo:
    base = model_dir_of(spec.id)
    files: list[ModelFileInfo] = []
    for item in spec.files:
        path = base / item.path
        exists = path.is_file() and path.stat().st_size > 0
        files.append(
            ModelFileInfo(
                key=item.key,
                path=item.path,
                exists=exists,
                size_bytes=path.stat().st_size if path.is_file() else 0,
            )
        )

    return ModelInfo(
        id=spec.id,
        name=spec.name,
        type=spec.type,
        language=spec.language,
        description=spec.description,
        memory_mb=spec.memory_mb,
        tags=list(spec.tags),
        downloaded=state.downloaded,
        download_progress=state.download_progress,
        size_bytes=state.size_bytes,
        running=state.running,
        status=state.status,
        port=state.port,
        pid=state.pid,
        restart_count=state.restart_count,
        last_error=state.last_error,
        gateway_path=spec.gateway_path(),
        source_repo=spec.source.repo,
        source_mirrors=list(spec.source.mirrors),
        files=files,
        start_command=spec.start.command,
        start_args=list(spec.start.args),
        start_cwd=spec.start.cwd,
        health_check=spec.start.health.kind,
        health_path=spec.start.health.path,
        origin=spec.origin,
        downloadable=spec.downloadable,
    )


class ModelLogs(BaseModel):
    model_id: str
    lines: int
    content: str
    log_path: str


class DownloadProgressInfo(BaseModel):
    model_id: str
    status: str
    progress: float
    total_files: int
    completed_files: int
    downloaded_bytes: int
    current_file: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class KeyCreateRequest(BaseModel):
    name: str = Field(default="default", max_length=128)


class KeyInfo(BaseModel):
    id: int
    name: str
    key_prefix: str
    active: bool
    created_at: datetime
    last_used_at: datetime | None = None


class KeyCreated(KeyInfo):
    """仅在创建时返回一次明文。"""

    key: str


def to_key_info(record: ApiKey) -> KeyInfo:
    return KeyInfo(
        id=int(record.id or 0),
        name=record.name,
        key_prefix=record.key_prefix,
        active=record.active,
        created_at=record.created_at,
        last_used_at=record.last_used_at,
    )


class TtsRequest(BaseModel):
    text: str = Field(min_length=1)
    speaker_id: int = 0
    speed: float = Field(default=1.0, gt=0.0, le=3.0)


class ProcessUsage(BaseModel):
    model_id: str
    pid: int
    port: int
    status: str
    restart_count: int
    uptime_seconds: float
    cpu_percent: float
    memory_mb: float


class ResourceMetrics(BaseModel):
    running_models: int
    max_running_models: int
    port_pool_start: int
    port_pool_end: int
    system_cpu_percent: float
    system_memory_percent: float
    system_memory_used_mb: float
    system_memory_total_mb: float
    processes: list[ProcessUsage] = Field(default_factory=list)
