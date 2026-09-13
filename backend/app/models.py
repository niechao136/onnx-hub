"""SQLite 数据模型（SQLModel）。

三张表：
- ``ModelState``    : 每个模型的持久化状态（是否下载、是否运行、端口、pid、错误）
- ``DownloadTask``  : 下载任务的历史记录（进度、结果）
- ``ApiKey``        : 对外网关使用的 API Key（只存哈希）
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import ConfigDict
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ModelState(SQLModel, table=True):
    """模型运行/下载状态。"""

    model_config = ConfigDict(protected_namespaces=())

    __tablename__ = "model_state"

    model_id: str = Field(primary_key=True, max_length=128)
    downloaded: bool = Field(default=False)
    download_progress: float = Field(default=0.0)
    size_bytes: int = Field(default=0)
    running: bool = Field(default=False)
    #: stopped | starting | running | stopping | error | restarting
    status: str = Field(default="stopped", max_length=32)
    port: int | None = Field(default=None)
    pid: int | None = Field(default=None)
    auto_restart: bool = Field(default=True)
    #: 连续自动重启次数，健康检查成功后会清零
    restart_count: int = Field(default=0)
    last_error: str | None = Field(default=None)
    updated_at: datetime = Field(default_factory=utcnow)


class DownloadTask(SQLModel, table=True):
    """下载任务记录。"""

    model_config = ConfigDict(protected_namespaces=())

    __tablename__ = "download_task"

    id: int | None = Field(default=None, primary_key=True)
    model_id: str = Field(index=True, max_length=128)
    #: pending | running | completed | failed | cancelled
    status: str = Field(default="pending", max_length=32)
    progress: float = Field(default=0.0)
    total_files: int = Field(default=0)
    completed_files: int = Field(default=0)
    total_bytes: int = Field(default=0)
    downloaded_bytes: int = Field(default=0)
    current_file: str | None = Field(default=None)
    error: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = Field(default=None)


class CustomModelRecord(SQLModel, table=True):
    """用户自定义模型。

    规格以 JSON 形式持久化，结构与 ``models.yaml`` 中的单个条目完全一致，
    加载时由 ``registry`` 与预置模型合并，因此下载/启动/网关逻辑无需区分来源。
    """

    model_config = ConfigDict(protected_namespaces=())

    __tablename__ = "custom_model"

    model_id: str = Field(primary_key=True, max_length=128)
    spec_json: str = Field(default="{}")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ApiKey(SQLModel, table=True):
    """对外调用网关所用的 API Key。"""

    __tablename__ = "api_key"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=128)
    #: sha256(key) 的十六进制摘要，明文只在生成时返回一次
    key_hash: str = Field(index=True, unique=True, max_length=128)
    #: 明文前缀，便于在界面上辨识是哪个 Key
    key_prefix: str = Field(max_length=32)
    active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utcnow)
    last_used_at: datetime | None = Field(default=None)
