"""模型仓库模块。

负责解析 ``app/config/models.yaml``，把 YAML 中的模型目录转换成强类型的
``ModelSpec``，并提供查询与命令模板渲染能力。
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError

from .config import BACKEND_DIR, settings
from .errors import RegistryError

ModelType = Literal["asr-streaming", "asr-offline", "tts"]

#: 启动参数模板中允许出现的保留占位符
RESERVED_PLACEHOLDERS = {"port", "model_dir", "data_dir", "backend_dir", "python"}

__all__ = [
    "ModelFile",
    "ModelSource",
    "HealthSpec",
    "StartSpec",
    "ModelSpec",
    "ModelType",
    "RegistryError",
    "load_registry",
    "get_registry",
    "list_specs",
    "get_spec",
    "model_dir_of",
    "render_context",
]


class ModelFile(BaseModel):
    """模型需要下载的一个文件。"""

    key: str
    path: str

    @property
    def is_nested(self) -> bool:
        return "/" in self.path


class ModelSource(BaseModel):
    """下载源配置。"""

    repo: str = ""
    mirrors: list[str] = Field(default_factory=list)

    def urls_for(self, file_path: str) -> list[str]:
        """返回该文件的所有候选下载地址（按 mirrors 顺序）。"""
        return [
            template.format(repo=self.repo, file=file_path)
            for template in self.mirrors
            if template
        ]


class HealthSpec(BaseModel):
    """健康检查配置。"""

    kind: Literal["tcp", "http"] = "tcp"
    path: str = "/health"


class StartSpec(BaseModel):
    """进程启动配置。"""

    command: str
    args: list[str] = Field(default_factory=list)
    cwd: Literal["model_dir", "backend_dir"] = "model_dir"
    health: HealthSpec = Field(default_factory=HealthSpec)
    #: 进程启动后额外等待时间（秒），用于规避端口就绪前的抖动
    startup_grace: float = 1.0


class ModelSpec(BaseModel):
    """一个可管理的模型定义。"""

    id: str
    name: str
    type: ModelType
    language: str = ""
    description: str = ""
    memory_mb: int = 0
    tags: list[str] = Field(default_factory=list)
    source: ModelSource = Field(default_factory=ModelSource)
    files: list[ModelFile] = Field(default_factory=list)
    start: StartSpec

    # ---------------------------------------------------------------- 辅助
    @property
    def file_keys(self) -> set[str]:
        return {f.key for f in self.files}

    @property
    def is_asr(self) -> bool:
        return self.type in ("asr-streaming", "asr-offline")

    def gateway_path(self) -> str:
        """该模型对外暴露的稳定路径。"""
        if self.is_asr:
            return f"/ws/asr/{self.id}"
        return f"/api/tts/{self.id}"

    def render(self, context: dict[str, str]) -> tuple[str, list[str]]:
        """渲染启动命令模板，返回 ``(command, args)``。

        支持的占位符：``{port}``、``{model_dir}``、``{data_dir}``、
        ``{backend_dir}``、``{python}`` 以及 ``files`` 中定义的每个 ``key``。
        """
        merged = {**context, "python": sys.executable}

        def _fmt(value: str) -> str:
            try:
                return value.format_map(merged)
            except KeyError as exc:  # 缺失的占位符
                raise RegistryError(
                    f"模型 {self.id} 的启动模板引用了未定义的占位符 {exc}"
                ) from exc

        return _fmt(self.start.command), [_fmt(a) for a in self.start.args]


def _validate(specs: list[ModelSpec]) -> None:
    seen: set[str] = set()
    for spec in specs:
        if spec.id in seen:
            raise RegistryError(f"models.yaml 中存在重复的模型 id: {spec.id}")
        seen.add(spec.id)

        if not spec.files:
            raise RegistryError(f"模型 {spec.id} 未配置任何 files")

        file_keys: set[str] = set()
        for item in spec.files:
            if item.key in file_keys:
                raise RegistryError(f"模型 {spec.id} 的 files 中存在重复 key: {item.key}")
            if item.key in RESERVED_PLACEHOLDERS:
                raise RegistryError(
                    f"模型 {spec.id} 的 file key '{item.key}' 与保留占位符冲突，请改名"
                )
            file_keys.add(item.key)

        if not spec.source.mirrors:
            raise RegistryError(f"模型 {spec.id} 未配置 source.mirrors")

        # 提前渲染一次，尽早发现模板里的占位符笔误
        probe = {key: f"<{key}>" for key in file_keys}
        spec.render(
            {
                "port": "0",
                "model_dir": str(settings.model_dir / spec.id),
                "data_dir": str(settings.data_dir),
                "backend_dir": str(BACKEND_DIR),
                **probe,
            }
        )


def load_registry(path: Path | None = None) -> dict[str, ModelSpec]:
    """从 YAML 文件加载模型目录。"""
    config_path = Path(path or settings.models_config)
    if not config_path.exists():
        raise RegistryError(f"模型目录配置文件不存在: {config_path}")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    entries = raw.get("models") or []
    if not isinstance(entries, list) or not entries:
        raise RegistryError(f"{config_path} 中未定义任何模型（models 列表为空）")

    specs: list[ModelSpec] = []
    for index, entry in enumerate(entries):
        try:
            specs.append(ModelSpec.model_validate(entry))
        except ValidationError as exc:
            raise RegistryError(
                f"{config_path} 第 {index + 1} 个模型定义非法: {exc}"
            ) from exc

    _validate(specs)
    return {spec.id: spec for spec in specs}


@lru_cache(maxsize=1)
def _cached_registry() -> tuple[str, dict[str, ModelSpec]]:
    path = Path(settings.models_config)
    return str(path), load_registry(path)


def get_registry(reload: bool = False) -> dict[str, ModelSpec]:
    """获取模型目录（默认带缓存）。"""
    if reload:
        _cached_registry.cache_clear()
    return _cached_registry()[1]


def list_specs(reload: bool = False) -> list[ModelSpec]:
    return list(get_registry(reload=reload).values())


def get_spec(model_id: str) -> ModelSpec:
    """按 id 取模型定义，不存在时抛 ``KeyError``。"""
    registry = get_registry()
    if model_id not in registry:
        raise KeyError(f"未知模型: {model_id}")
    return registry[model_id]


def model_dir_of(model_id: str) -> Path:
    return settings.model_dir / model_id


def render_context(spec: ModelSpec, port: int) -> dict[str, str]:
    """构造启动模板渲染上下文。"""
    base = model_dir_of(spec.id)
    context: dict[str, str] = {
        "port": str(port),
        "model_dir": str(base),
        "data_dir": str(settings.data_dir),
        "backend_dir": str(BACKEND_DIR),
    }
    for item in spec.files:
        context[item.key] = str(base / item.path)
    return context
