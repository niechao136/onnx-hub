"""自定义模型（用户新增模型）接口测试。"""

from __future__ import annotations

from typing import Any

from app.config import settings

BASE = "/api/models/custom"
BUILTIN_ID = "vits-zh-aishell3"


def spec_payload(model_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": model_id,
        "name": f"自定义模型 {model_id}",
        "type": "tts",
        "language": "zh",
        "description": "pytest 用自定义模型",
        "memory_mb": 100,
        "tags": ["test"],
        "source": {"repo": "", "mirrors": []},
        "files": [{"key": "tokens", "path": "tokens.txt"}],
        "start": {
            "command": "{python}",
            "args": ["-m", "http.server", "{port}"],
            "cwd": "backend_dir",
            "health": {"kind": "tcp"},
        },
    }
    payload.update(overrides)
    return payload


def cleanup(client, model_id: str) -> None:
    client.delete(f"{BASE}/{model_id}", params={"purge_files": True})


def test_create_update_delete_custom_model(client) -> None:
    model_id = "pytest-custom-tts"
    cleanup(client, model_id)

    created = client.post(BASE, json=spec_payload(model_id))
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["id"] == model_id
    assert body["origin"] == "custom"
    assert body["downloadable"] is False  # 未配置下载源 → 只能手动上传
    assert body["downloaded"] is False
    assert body["gateway_path"] == f"/api/tts/{model_id}"
    assert body["status"] == "stopped"

    # 与预置模型共存于同一份目录
    models = client.get("/api/models").json()
    ids = {item["id"] for item in models}
    assert model_id in ids
    assert BUILTIN_ID in ids
    assert next(item for item in models if item["id"] == BUILTIN_ID)["origin"] == "builtin"

    # 详情 / 状态 / 日志接口可直接复用
    assert client.get(f"/api/models/{model_id}").status_code == 200
    assert client.get(f"/api/models/{model_id}/status").status_code == 200
    assert client.get(f"/api/models/{model_id}/logs").status_code == 200

    # 更新（id 以路径为准）
    updated = client.put(
        f"{BASE}/{model_id}", json=spec_payload(model_id, name="改名了", memory_mb=222)
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "改名了"
    assert updated.json()["memory_mb"] == 222

    # 删除后从目录中消失
    assert client.delete(f"{BASE}/{model_id}", params={"purge_files": True}).status_code == 200
    assert model_id not in {item["id"] for item in client.get("/api/models").json()}
    assert client.get(f"/api/models/{model_id}").status_code == 404


def test_downloadable_flag_when_mirrors_configured(client) -> None:
    model_id = "pytest-custom-downloadable"
    cleanup(client, model_id)
    payload = spec_payload(
        model_id,
        source={"repo": "org/demo", "mirrors": ["https://example.com/{repo}/{file}"]},
    )
    created = client.post(BASE, json=payload)
    assert created.status_code == 200, created.text
    assert created.json()["downloadable"] is True
    assert created.json()["source_repo"] == "org/demo"
    cleanup(client, model_id)


def test_duplicate_custom_id_rejected(client) -> None:
    model_id = "pytest-dup"
    cleanup(client, model_id)
    assert client.post(BASE, json=spec_payload(model_id)).status_code == 200

    duplicated = client.post(BASE, json=spec_payload(model_id))
    assert duplicated.status_code == 409
    assert duplicated.json()["code"] == "custom_model_exists"

    cleanup(client, model_id)


def test_cannot_shadow_or_modify_builtin_model(client) -> None:
    shadow = client.post(BASE, json=spec_payload(BUILTIN_ID))
    assert shadow.status_code == 409

    updated = client.put(f"{BASE}/{BUILTIN_ID}", json=spec_payload(BUILTIN_ID))
    assert updated.status_code == 400
    assert updated.json()["code"] == "builtin_model_protected"

    deleted = client.delete(f"{BASE}/{BUILTIN_ID}")
    assert deleted.status_code == 400

    # 预置模型仍然完好
    assert client.get(f"/api/models/{BUILTIN_ID}").status_code == 200


def test_invalid_spec_rejected(client) -> None:
    bad = spec_payload("pytest-bad", start={"command": "{python}", "args": ["{not_a_placeholder}"]})
    response = client.post(BASE, json=bad)
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_model_spec"

    # 缺少 files
    response = client.post(BASE, json=spec_payload("pytest-bad2", files=[]))
    assert response.status_code == 400

    # 未知的 file key 与保留字冲突
    response = client.post(
        BASE, json=spec_payload("pytest-bad3", files=[{"key": "port", "path": "x.txt"}])
    )
    assert response.status_code == 400


def test_unknown_custom_model_returns_404(client) -> None:
    assert client.put(f"{BASE}/not-exist", json=spec_payload("not-exist")).status_code == 404
    assert client.delete(f"{BASE}/not-exist").status_code == 404


def test_upload_files_marks_model_ready(client) -> None:
    model_id = "pytest-upload"
    cleanup(client, model_id)
    payload = spec_payload(
        model_id,
        files=[
            {"key": "tokens", "path": "tokens.txt"},
            {"key": "model", "path": "sub/model.onnx"},
        ],
    )
    assert client.post(BASE, json=payload).status_code == 200

    first = client.put(f"/api/models/{model_id}/files/tokens.txt", content=b"hello-tokens")
    assert first.status_code == 200, first.text
    assert first.json()["size_bytes"] == len(b"hello-tokens")

    # 还缺一个文件，不应算已就绪
    assert client.get(f"/api/models/{model_id}").json()["downloaded"] is False

    second = client.put(f"/api/models/{model_id}/files/sub/model.onnx", content=b"x" * 64)
    assert second.status_code == 200, second.text

    info = client.get(f"/api/models/{model_id}").json()
    assert info["downloaded"] is True
    assert info["download_progress"] == 1.0
    assert all(item["exists"] for item in info["files"])

    # 上传后 .part 不应残留
    model_dir = settings.model_dir / model_id
    assert not list(model_dir.rglob("*.part"))

    assert client.delete(f"{BASE}/{model_id}", params={"purge_files": True}).status_code == 200
    assert not model_dir.exists()


def test_upload_empty_body_rejected(client) -> None:
    model_id = "pytest-upload-empty"
    cleanup(client, model_id)
    assert client.post(BASE, json=spec_payload(model_id)).status_code == 200

    response = client.put(f"/api/models/{model_id}/files/tokens.txt", content=b"")
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_model_spec"

    cleanup(client, model_id)


def test_upload_path_traversal_rejected(client) -> None:
    model_id = "pytest-traversal"
    cleanup(client, model_id)
    assert client.post(BASE, json=spec_payload(model_id)).status_code == 200

    # 编码后的 ../ 会进入路径参数，必须被拦截
    response = client.put(
        f"/api/models/{model_id}/files/%2e%2e%2f%2e%2e%2fevil.txt", content=b"boom"
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_model_spec"

    # 绝对路径同样拒绝
    response = client.put(f"/api/models/{model_id}/files//etc/passwd", content=b"boom")
    assert response.status_code in (400, 405)

    assert not (settings.model_dir.parent / "evil.txt").exists()
    cleanup(client, model_id)
