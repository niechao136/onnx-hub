"""API Key 鉴权模块。

- Key 明文以 ``sk-hub-`` 前缀 + 随机串生成，**只在生成时返回一次**
- 数据库只保存 ``sha256(key)`` 摘要，泄漏数据库也无法反推 Key
- 网关接口（WS ASR / HTTP TTS）默认开启校验，可用 ``HUB_REQUIRE_API_KEY=false`` 关闭
- 管理接口可通过 ``HUB_ADMIN_KEY`` 设置一个管理密钥（未设置则不做鉴权，便于本地开发）
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone

from fastapi import Header, Query, Request, status
from sqlmodel import Session, select

from .config import settings
from .db import get_session
from .errors import AuthError
from .models import ApiKey

KEY_PREFIX = "sk-hub-"
PREFIX_DISPLAY_LEN = len(KEY_PREFIX) + 6


def generate_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def create_key(session: Session, name: str) -> tuple[ApiKey, str]:
    """创建 API Key，返回 ``(记录, 明文)``。"""
    plain = generate_key()
    record = ApiKey(
        name=name.strip() or "未命名",
        key_hash=hash_key(plain),
        key_prefix=plain[:PREFIX_DISPLAY_LEN],
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record, plain


def list_keys(session: Session) -> list[ApiKey]:
    return list(session.exec(select(ApiKey).order_by(ApiKey.id)).all())  # type: ignore[arg-type]


def delete_key(session: Session, key_id: int) -> bool:
    record = session.get(ApiKey, key_id)
    if record is None:
        return False
    session.delete(record)
    session.commit()
    return True


def verify_key(session: Session, key: str) -> bool:
    """校验 Key 是否有效，并记录最近使用时间。"""
    if not key:
        return False
    record = session.exec(select(ApiKey).where(ApiKey.key_hash == hash_key(key))).first()
    if record is None or not record.active:
        return False
    record.last_used_at = datetime.now(timezone.utc)
    session.add(record)
    session.commit()
    return True


def extract_key(request: Request) -> str | None:
    """从请求中提取 API Key。

    支持三种携带方式（按优先级）：
    1. ``Authorization: Bearer <key>``
    2. ``X-API-Key: <key>``
    3. 查询参数 ``?api_key=<key>``（浏览器 WebSocket 无法自定义 Header 时的兜底）
    """
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    header_key = request.headers.get("x-api-key")
    if header_key:
        return header_key.strip()
    return request.query_params.get("api_key")


async def require_api_key(request: Request) -> None:
    """网关接口依赖：校验 API Key。"""
    if not settings.require_api_key:
        return
    key = extract_key(request)
    if key is None:
        raise AuthError("缺少 API Key，请通过 Authorization: Bearer <key> 或 X-API-Key 传递")
    session = next(get_session())
    try:
        if not verify_key(session, key):
            raise AuthError("API Key 无效或已被禁用")
    finally:
        session.close()


async def require_admin(
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
    admin_key: str | None = Query(default=None, alias="admin_key"),
) -> None:
    """管理接口依赖：仅在配置了 ``HUB_ADMIN_KEY`` 时校验。"""
    expected = settings.admin_key
    if not expected:
        return
    provided = x_admin_key or admin_key
    if not provided or not secrets.compare_digest(provided, expected):
        raise AuthError("管理密钥无效", status_code=status.HTTP_401_UNAUTHORIZED)
