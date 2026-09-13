"""自定义模型管理。

用户在界面上新增的模型**不写入 ``models.yaml``**，而是以 JSON 形式持久化到 SQLite；
``registry`` 加载时会把它与预置模型合并，因此下载、启动、网关等逻辑完全复用，
无需为自定义模型单独写一套流程。

另外提供模型文件上传的落盘能力，用于「自带 ONNX 文件」或上游没有下载源的场景。
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
from pathlib import Path

from sqlmodel import select

from .config import settings
from .db import session_scope
from .errors import (
    BuiltinModelProtectedError,
    CustomModelExistsError,
    InvalidModelSpecError,
    ModelNotFoundError,
)
from .models import CustomModelRecord, ModelState, utcnow
from .registry import ModelSpec, get_registry, model_dir_of, parse_spec

logger = logging.getLogger(__name__)


# =============================================================================
# 读取
# =============================================================================
def _record_to_spec(record: CustomModelRecord) -> ModelSpec:
    return parse_spec(json.loads(record.spec_json), origin="custom")


def load_specs_for_registry() -> dict[str, ModelSpec]:
    """供 ``registry.load_registry`` 调用。

    单条记录损坏（例如手工改库或升级后结构变化）时跳过并告警，不能因此让整个服务起不来。
    """
    specs: dict[str, ModelSpec] = {}
    try:
        with session_scope() as session:
            records = list(session.exec(select(CustomModelRecord)).all())
    except Exception as exc:  # noqa: BLE001 - 表未建好等情况不应阻断启动
        logger.warning("读取自定义模型失败（已跳过）: %s", exc)
        return specs

    for record in records:
        try:
            specs[record.model_id] = _record_to_spec(record)
        except Exception as exc:  # noqa: BLE001
            logger.warning("自定义模型 %s 定义已损坏，已跳过: %s", record.model_id, exc)
    return specs


def list_custom_model_ids() -> list[str]:
    with session_scope() as session:
        return [record.model_id for record in session.exec(select(CustomModelRecord)).all()]


def is_custom_model(model_id: str) -> bool:
    with session_scope() as session:
        return session.get(CustomModelRecord, model_id) is not None


# =============================================================================
# 写入
# =============================================================================
def create_custom_model(entry: dict) -> ModelSpec:
    """新增自定义模型。id 不能与已有自定义模型或预置模型重复。"""
    spec = parse_spec(entry, origin="custom")

    if is_custom_model(spec.id):
        raise CustomModelExistsError(f"自定义模型 {spec.id} 已存在，如需修改请使用编辑")
    if spec.id in get_registry():
        raise CustomModelExistsError(
            f"模型 id {spec.id} 已被预置模型占用，请换一个 id"
        )
    return _save(spec)


def update_custom_model(model_id: str, entry: dict) -> ModelSpec:
    """更新自定义模型（id 以路径参数为准）。"""
    _ensure_modifiable(model_id)
    spec = parse_spec({**entry, "id": model_id}, origin="custom")
    return _save(spec)


def delete_custom_model(model_id: str, *, purge_files: bool = False) -> None:
    """删除自定义模型记录；``purge_files=True`` 时同时删除已下载/上传的文件。"""
    _ensure_modifiable(model_id)

    with session_scope() as session:
        record = session.get(CustomModelRecord, model_id)
        if record is not None:
            session.delete(record)
        state = session.get(ModelState, model_id)
        if state is not None:
            session.delete(state)
        session.commit()

    if purge_files:
        target = model_dir_of(model_id)
        resolved = target.resolve()
        root = settings.model_dir.resolve()
        # 只允许删除 models 根目录之下的目录
        if resolved != root and root in resolved.parents and resolved.exists():
            shutil.rmtree(resolved, ignore_errors=True)


def _ensure_modifiable(model_id: str) -> CustomModelRecord:
    with session_scope() as session:
        record = session.get(CustomModelRecord, model_id)
    if record is not None:
        return record

    if model_id in get_registry():
        raise BuiltinModelProtectedError(
            f"{model_id} 是 models.yaml 中的预置模型，不支持通过接口修改或删除"
        )
    raise ModelNotFoundError(f"自定义模型 {model_id} 不存在")


def _save(spec: ModelSpec) -> ModelSpec:
    payload = json.dumps(spec.model_dump(exclude={"origin"}), ensure_ascii=False)
    with session_scope() as session:
        record = session.get(CustomModelRecord, spec.id)
        if record is None:
            record = CustomModelRecord(model_id=spec.id, spec_json=payload)
        else:
            record.spec_json = payload
            record.updated_at = utcnow()
        session.add(record)
        session.commit()
    logger.info("已保存自定义模型 %s", spec.id)
    return spec


# =============================================================================
# 文件上传
# =============================================================================
def resolve_upload_path(model_id: str, rel_path: str) -> Path:
    """把相对路径安全解析到模型目录内，防止路径穿越写入任意位置。"""
    raw = (rel_path or "").replace("\\", "/").strip()
    if not raw or raw in (".", ".."):
        raise InvalidModelSpecError("文件路径不能为空")
    if raw.startswith("/") or ":" in raw:
        raise InvalidModelSpecError("请使用相对模型目录的路径，不要使用绝对路径")

    parts = [part for part in raw.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise InvalidModelSpecError("文件路径不允许包含 ..")

    base = model_dir_of(model_id).resolve()
    target = (base / "/".join(parts)).resolve()
    if target != base and base not in target.parents:
        raise InvalidModelSpecError("文件路径越界，已拒绝写入")
    return target


async def save_upload(model_id: str, rel_path: str, stream) -> tuple[Path, int]:
    """把请求体流式写入模型目录（边收边写，不占内存）。"""
    target = resolve_upload_path(model_id, rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".part")

    size = 0
    try:
        with tmp.open("wb") as handle:
            async for chunk in stream:
                if not chunk:
                    continue
                handle.write(chunk)
                size += len(chunk)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise

    if size == 0:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise InvalidModelSpecError("上传内容为空")

    os.replace(tmp, target)
    logger.info("模型 %s 上传文件完成: %s (%s 字节)", model_id, rel_path, size)
    return target, size
