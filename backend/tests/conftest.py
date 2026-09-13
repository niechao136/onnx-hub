"""pytest 全局配置。

**必须在导入 app 之前设置环境变量**，因为 ``app.config.settings`` 是模块级单例。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TEST_ROOT = Path(tempfile.mkdtemp(prefix="sherpa-hub-test-"))

os.environ.setdefault("HUB_MODEL_DIR", str(_TEST_ROOT / "models"))
os.environ.setdefault("HUB_DATA_DIR", str(_TEST_ROOT / "data"))
os.environ.setdefault("HUB_REQUIRE_API_KEY", "false")
os.environ.setdefault("HUB_MAX_RUNNING_MODELS", "2")
os.environ.setdefault("HUB_HEALTH_CHECK_INTERVAL", "60")
os.environ.setdefault("HUB_START_TIMEOUT", "20")
os.environ.setdefault("HUB_STOP_TIMEOUT", "5")
os.environ.setdefault("HUB_DOWNLOAD_RETRIES", "2")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import init_db  # noqa: E402

init_db()


@pytest.fixture(scope="session")
def client() -> TestClient:
    """带 lifespan 的测试客户端（覆盖整个测试会话）。"""
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
