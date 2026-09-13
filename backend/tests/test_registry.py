"""模型仓库模块测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.errors import RegistryError
from app.registry import (
    ModelFile,
    ModelSource,
    ModelSpec,
    load_registry,
    model_dir_of,
    render_context,
)


def write_yaml(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "models.yaml"
    path.write_text(body, encoding="utf-8")
    return path


SINGLE_MODEL = """
version: 1
models:
  - id: demo
    name: 测试模型
    type: asr-streaming
    source:
      repo: demo/repo
      mirrors:
        - https://example.com/{repo}/{file}
    files:
      - key: tokens
        path: tokens.txt
    start:
      command: sherpa-onnx-online-websocket-server
      args:
        - --port={port}
        - --tokens={tokens}
"""


def test_builtin_registry_is_valid() -> None:
    registry = load_registry()
    assert len(registry) >= 3
    assert "zipformer-streaming-bilingual-zh-en" in registry
    assert "vits-zh-aishell3" in registry

    types = {spec.type for spec in registry.values()}
    assert {"asr-streaming", "tts"} <= types

    for spec in registry.values():
        assert spec.files, f"{spec.id} 未配置文件清单"
        assert spec.source.mirrors, f"{spec.id} 未配置下载源"
        expected = f"/ws/asr/{spec.id}" if spec.is_asr else f"/api/tts/{spec.id}"
        assert spec.gateway_path() == expected


def test_render_replaces_all_placeholders() -> None:
    spec = ModelSpec(
        id="demo",
        name="demo",
        type="asr-streaming",
        source=ModelSource(repo="demo/repo", mirrors=["https://example.com/{file}"]),
        files=[ModelFile(key="tokens", path="tokens.txt")],
        start={
            "command": "sherpa-onnx-online-websocket-server",
            "args": ["--port={port}", "--tokens={tokens}", "--dir={model_dir}"],
        },
    )
    command, args = spec.render(render_context(spec, 7001))
    base = model_dir_of("demo")
    assert command == "sherpa-onnx-online-websocket-server"
    assert args == [
        "--port=7001",
        f"--tokens={base / 'tokens.txt'}",
        f"--dir={base}",
    ]


def test_mirror_urls_are_expanded() -> None:
    source = ModelSource(
        repo="org/model",
        mirrors=[
            "https://huggingface.co/{repo}/resolve/main/{file}",
            "https://modelscope.cn/models/{repo}/resolve/master/{file}",
        ],
    )
    urls = source.urls_for("tokens.txt")
    assert urls[0] == "https://huggingface.co/org/model/resolve/main/tokens.txt"
    assert urls[1] == "https://modelscope.cn/models/org/model/resolve/master/tokens.txt"


def test_single_model_yaml_loads(tmp_path: Path) -> None:
    registry = load_registry(write_yaml(tmp_path, SINGLE_MODEL))
    assert list(registry) == ["demo"]
    assert registry["demo"].file_keys == {"tokens"}


DUPLICATE_MODELS = """
version: 1
models:
  - id: dup
    name: dup-a
    type: tts
    source:
      repo: demo/repo
      mirrors:
        - https://example.com/{file}
    files:
      - key: tokens
        path: tokens.txt
    start:
      command: echo
  - id: dup
    name: dup-b
    type: tts
    source:
      repo: demo/repo
      mirrors:
        - https://example.com/{file}
    files:
      - key: tokens
        path: tokens.txt
    start:
      command: echo
"""


def test_duplicate_id_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(RegistryError, match="重复的模型 id"):
        load_registry(write_yaml(tmp_path, DUPLICATE_MODELS))


def test_unknown_placeholder_is_rejected(tmp_path: Path) -> None:
    body = SINGLE_MODEL.replace("--tokens={tokens}", "--tokens={nope}")
    with pytest.raises(RegistryError, match="未定义的占位符"):
        load_registry(write_yaml(tmp_path, body))


def test_file_key_conflicts_with_reserved_placeholder(tmp_path: Path) -> None:
    body = SINGLE_MODEL.replace("- key: tokens", "- key: port")
    with pytest.raises(RegistryError, match="保留占位符"):
        load_registry(write_yaml(tmp_path, body))


def test_empty_models_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(RegistryError, match="未定义任何模型"):
        load_registry(write_yaml(tmp_path, "version: 1\nmodels: []\n"))


def test_missing_config_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(RegistryError, match="不存在"):
        load_registry(tmp_path / "nope.yaml")
