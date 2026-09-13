"""SQLite 引擎与会话管理。"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlmodel import Session, SQLModel, create_engine

from .config import settings

engine = create_engine(
    settings.sqlite_url,
    echo=False,
    connect_args={"check_same_thread": False},
)


def init_db() -> None:
    """建表（幂等）。调用前需保证 ``configure()`` 已设置数据库路径。"""
    settings.ensure_dirs()
    # 确保所有表模型已被导入注册
    from . import models  # noqa: F401

    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    """FastAPI 依赖：请求级 SQLModel 会话。"""
    with Session(engine, expire_on_commit=False) as session:
        yield session


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """后台任务的会话上下文。

    ``expire_on_commit=False`` 让会话关闭后仍可安全读取已加载的属性，
    避免把 ORM 对象返回给上层时抛 ``DetachedInstanceError``。
    """
    with Session(engine, expire_on_commit=False) as session:
        yield session
