"""HTTP / WebSocket 接口层测试（后端核心链路的端到端冒烟）。"""

from __future__ import annotations

import pytest
from starlette.websockets import WebSocketDisconnect

from app.gateway import (
    WS_CLOSE_MODEL_NOT_FOUND,
    WS_CLOSE_MODEL_NOT_RUNNING,
)

MODEL_ID = "zipformer-streaming-bilingual-zh-en"


def test_root_and_health(client) -> None:
    root = client.get("/")
    assert root.status_code == 200
    assert root.json()["name"] == "sherpa-model-hub"

    health = client.get("/api/system/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"


def test_list_models(client) -> None:
    response = client.get("/api/models")
    assert response.status_code == 200
    models = response.json()
    assert len(models) >= 3

    ids = {item["id"] for item in models}
    assert MODEL_ID in ids

    sample = next(item for item in models if item["id"] == MODEL_ID)
    assert sample["type"] == "asr-streaming"
    assert sample["gateway_path"] == f"/ws/asr/{MODEL_ID}"
    assert sample["running"] is False
    assert sample["status"] == "stopped"
    assert sample["files"], "应返回文件清单用于前端展示"
    assert sample["memory_mb"] > 0

    tts = next(item for item in models if item["id"] == "vits-zh-aishell3")
    assert tts["gateway_path"] == "/api/tts/vits-zh-aishell3"


def test_model_detail_and_404(client) -> None:
    response = client.get(f"/api/models/{MODEL_ID}")
    assert response.status_code == 200
    assert response.json()["id"] == MODEL_ID

    missing = client.get("/api/models/not-exist")
    assert missing.status_code == 404
    assert missing.json()["code"] == "model_not_found"


def test_download_progress_endpoint(client) -> None:
    response = client.get(f"/api/models/{MODEL_ID}/download/progress")
    assert response.status_code == 200
    payload = response.json()
    assert payload["model_id"] == MODEL_ID
    assert payload["status"] in ("idle", "completed", "running", "failed", "cancelled")

    assert client.get("/api/models/nope/download/progress").status_code == 404


def test_start_rejects_not_downloaded_model(client) -> None:
    response = client.post(f"/api/models/{MODEL_ID}/start")
    assert response.status_code == 409
    assert response.json()["code"] == "model_not_downloaded"


def test_stop_on_idle_model_is_noop(client) -> None:
    response = client.post(f"/api/models/{MODEL_ID}/stop")
    assert response.status_code == 200
    assert response.json()["status"] == "stopped"


def test_logs_endpoint(client) -> None:
    response = client.get(f"/api/models/{MODEL_ID}/logs", params={"lines": 10})
    assert response.status_code == 200
    payload = response.json()
    assert payload["model_id"] == MODEL_ID
    assert payload["log_path"].endswith(f"{MODEL_ID}.log")


def test_registry_reload(client) -> None:
    response = client.post("/api/registry/reload")
    assert response.status_code == 200
    assert response.json()["reloaded"] >= 3


def test_system_metrics(client) -> None:
    response = client.get("/api/system/metrics")
    assert response.status_code == 200
    payload = response.json()
    assert payload["running_models"] == len(payload["processes"])
    assert payload["system_memory_total_mb"] > 0
    assert payload["max_running_models"] >= 1

    # 磁盘信息（模型存储所在分区）
    assert payload["disk_path"]
    assert payload["disk_total_mb"] > 0
    assert payload["disk_used_mb"] > 0
    assert 0 <= payload["disk_percent"] <= 100
    assert payload["disk_free_mb"] == pytest.approx(
        payload["disk_total_mb"] - payload["disk_used_mb"], rel=0.05
    )


def test_api_key_lifecycle(client) -> None:
    created = client.post("/api/keys", json={"name": "pytest"})
    assert created.status_code == 200
    payload = created.json()
    assert payload["key"].startswith("sk-hub-")
    assert payload["key_prefix"] == payload["key"][: len("sk-hub-") + 6]
    key_id = payload["id"]

    listed = client.get("/api/keys")
    assert listed.status_code == 200
    assert any(item["id"] == key_id for item in listed.json())
    # 列表接口绝不返回明文
    assert all("key" not in item for item in listed.json())

    deleted = client.delete(f"/api/keys/{key_id}")
    assert deleted.status_code == 200
    assert client.delete(f"/api/keys/{key_id}").status_code == 404


def test_tts_proxy_requires_running_model(client) -> None:
    response = client.post(
        "/api/tts/vits-zh-aishell3",
        json={"text": "你好", "speaker_id": 0, "speed": 1.0},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "model_not_running"


def test_tts_proxy_rejects_non_tts_model(client) -> None:
    response = client.post(f"/api/tts/{MODEL_ID}", json={"text": "hi"})
    # 模型未运行，先在网关层拦截
    assert response.status_code == 409


def test_ws_unknown_model_closes_with_4404(client) -> None:
    with client.websocket_connect("/ws/asr/not-exist") as websocket:
        with pytest.raises(WebSocketDisconnect) as exc:
            websocket.receive_text()
    assert exc.value.code == WS_CLOSE_MODEL_NOT_FOUND


def test_ws_model_not_running_closes_with_4409(client) -> None:
    with client.websocket_connect(f"/ws/asr/{MODEL_ID}") as websocket:
        with pytest.raises(WebSocketDisconnect) as exc:
            websocket.receive_text()
    assert exc.value.code == WS_CLOSE_MODEL_NOT_RUNNING


def test_cors_headers_present(client) -> None:
    response = client.get("/api/models", headers={"Origin": "http://localhost:3000"})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin")
