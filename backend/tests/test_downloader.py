"""下载模块测试。

用一个本地 HTTP 服务模拟模型源（覆盖：进度追踪、多镜像 fallback、失败重试、
部分文件已存在时跳过）。
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import threading
from pathlib import Path

import pytest

from app import downloader as dl
from app.config import settings
from app.registry import HealthSpec, ModelFile, ModelSource, ModelSpec, StartSpec

RETRY_TOKENS = b"a" * 4096
MODEL_BYTES = b"b" * 8192


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:  # noqa: D102
        pass


@pytest.fixture(scope="module")
def model_source() -> str:
    """本地静态文件服务，模拟模型下载源。"""
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="hub-source-"))
    (root / "tokens.txt").write_bytes(RETRY_TOKENS)
    (root / "sub").mkdir()
    (root / "sub" / "model.onnx").write_bytes(MODEL_BYTES)

    handler = functools.partial(_QuietHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def make_spec(model_id: str, mirrors: list[str]) -> ModelSpec:
    return ModelSpec(
        id=model_id,
        name=model_id,
        type="tts",
        source=ModelSource(repo="local/demo", mirrors=mirrors),
        files=[
            ModelFile(key="tokens", path="tokens.txt"),
            ModelFile(key="model", path="sub/model.onnx"),
        ],
        start=StartSpec(command="{python}", args=["-c", "pass"], health=HealthSpec()),
    )


async def wait_finished(manager: dl.DownloadManager, model_id: str, timeout: float = 20.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        progress = manager.get_progress(model_id)
        if progress.status in ("completed", "failed", "cancelled"):
            return progress
        await asyncio.sleep(0.05)
    raise AssertionError("等待下载结束超时")


@pytest.fixture
def patched(monkeypatch, tmp_path: Path):
    """把模型目录指向临时目录，并让 downloader 使用测试用的 ModelSpec。"""
    monkeypatch.setattr(settings, "model_dir", tmp_path / "models")
    monkeypatch.setattr(settings, "download_retries", 3)
    monkeypatch.setattr(settings, "download_backoff", 0.01)
    settings.ensure_dirs()

    specs: dict[str, ModelSpec] = {}

    def fake_get_spec(model_id: str) -> ModelSpec:
        if model_id not in specs:
            raise KeyError(f"未知模型: {model_id}")
        return specs[model_id]

    monkeypatch.setattr(dl, "get_spec", fake_get_spec)
    return specs, tmp_path / "models"


async def test_download_tracks_progress(patched, model_source: str) -> None:
    specs, models_dir = patched
    specs["demo"] = make_spec("demo", [f"{model_source}/{{file}}"])

    manager = dl.DownloadManager()
    snapshot = await manager.start("demo")
    assert snapshot.status in ("pending", "running")
    assert snapshot.total_files == 2

    progress = await wait_finished(manager, "demo")
    assert progress.status == "completed", progress.error
    assert progress.progress == 1.0
    assert progress.completed_files == 2
    assert progress.downloaded_bytes == len(RETRY_TOKENS) + len(MODEL_BYTES)

    assert (models_dir / "demo" / "tokens.txt").read_bytes() == RETRY_TOKENS
    assert (models_dir / "demo" / "sub" / "model.onnx").read_bytes() == MODEL_BYTES
    assert not list(models_dir.rglob("*.part")), "临时文件应被清理"

    spec = specs["demo"]
    assert dl.is_downloaded(spec) is True
    assert dl.downloaded_size(spec) == len(RETRY_TOKENS) + len(MODEL_BYTES)


async def test_download_falls_back_to_second_mirror(patched, model_source: str) -> None:
    specs, models_dir = patched
    # 第一个镜像指向不存在的端口，应当自动切到第二个镜像
    specs["fallback"] = make_spec(
        "fallback",
        ["http://127.0.0.1:1/{file}", f"{model_source}/{{file}}"],
    )

    manager = dl.DownloadManager()
    await manager.start("fallback")
    progress = await wait_finished(manager, "fallback")
    assert progress.status == "completed", progress.error
    assert (models_dir / "fallback" / "tokens.txt").exists()


async def test_download_failure_is_reported(patched) -> None:
    specs, models_dir = patched
    specs["broken"] = make_spec("broken", ["http://127.0.0.1:1/{file}"])

    manager = dl.DownloadManager()
    await manager.start("broken")
    progress = await wait_finished(manager, "broken")
    assert progress.status == "failed"
    assert progress.error
    assert not list((models_dir / "broken").rglob("*.part"))


async def test_existing_files_are_skipped(patched, model_source: str) -> None:
    specs, models_dir = patched
    specs["cached"] = make_spec("cached", [f"{model_source}/{{file}}"])

    base = models_dir / "cached"
    (base / "sub").mkdir(parents=True, exist_ok=True)
    (base / "tokens.txt").write_bytes(RETRY_TOKENS)
    (base / "sub" / "model.onnx").write_bytes(MODEL_BYTES)

    manager = dl.DownloadManager()
    progress = await manager.start("cached")
    assert progress.status == "completed"
    assert progress.progress == 1.0


async def test_missing_files_reported(patched) -> None:
    specs, _ = patched
    specs["empty"] = make_spec("empty", ["http://127.0.0.1:1/{file}"])
    assert dl.missing_files(specs["empty"]) == ["tokens.txt", "sub/model.onnx"]
    assert dl.is_downloaded(specs["empty"]) is False
