"""全局配置。

所有可配置项均支持通过环境变量覆盖，统一使用 ``HUB_`` 前缀，例如：

    HUB_MODEL_DIR=/data/models
    HUB_MAX_RUNNING_MODELS=1
    HUB_ADMIN_KEY=my-secret

也可以在 ``backend/.env`` 中书写（键名同样带 ``HUB_`` 前缀）。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ 目录
BACKEND_DIR = Path(__file__).resolve().parent.parent
# 仓库根目录
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HUB_",
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------- 存储 ----------
    #: 已下载模型文件的存放目录，Docker 中应挂载为数据卷
    model_dir: Path = BACKEND_DIR / "models"
    #: 运行期数据目录（SQLite、日志）
    data_dir: Path = BACKEND_DIR / "data"
    #: SQLite 数据库文件，默认 ``data_dir/hub.db``
    db_path: Path | None = None
    #: 预置模型目录配置文件
    models_config: Path = BACKEND_DIR / "app" / "config" / "models.yaml"

    # ---------- 进程管理 ----------
    #: 内部端口池范围（含两端）
    port_pool_start: int = 7001
    port_pool_end: int = 7099
    #: 同时运行的模型数量上限，超过时拒绝新的启动请求
    max_running_models: int = 2
    #: 启动后等待端口可用的超时时间（秒）
    start_timeout: float = 60.0
    #: 停止进程时等待优雅退出的时间（秒），超时后强制 kill
    stop_timeout: float = 10.0
    #: 健康检查周期（秒）
    health_check_interval: float = 10.0
    #: 单个进程自动重启的次数上限，避免崩溃进程被无限拉起
    max_restart_attempts: int = 3

    # ---------- 下载 ----------
    #: 单个文件下载失败后的重试次数（会在镜像之间轮换）
    download_retries: int = 3
    #: 下载请求超时时间（秒）
    download_timeout: float = 60.0
    #: 重试退避基数（秒），实际等待 = base * 2^attempt
    download_backoff: float = 2.0

    # ---------- 鉴权 ----------
    #: 对外网关接口（WS ASR / HTTP TTS）是否强制校验 API Key
    require_api_key: bool = True
    #: 管理接口的预留管理密钥；为空表示管理接口不做鉴权（便于本地开发）
    admin_key: str | None = None

    # ---------- 其他 ----------
    #: 模型详情页返回的日志尾部行数
    log_tail_lines: int = 200
    #: CORS 允许来源，逗号分隔，``*`` 表示全部
    cors_origins: str = "*"

    # ------------------------------------------------------------------
    # 派生属性
    # ------------------------------------------------------------------
    @property
    def sqlite_path(self) -> Path:
        return self.db_path or (self.data_dir / "hub.db")

    @property
    def sqlite_url(self) -> str:
        return f"sqlite:///{self.sqlite_path.as_posix()}"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def cors_origin_list(self) -> list[str]:
        raw = (self.cors_origins or "").strip()
        if not raw or raw == "*":
            return ["*"]
        return [item.strip() for item in raw.split(",") if item.strip()]

    def ensure_dirs(self) -> None:
        """确保运行期目录存在。"""
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings


settings = get_settings()
