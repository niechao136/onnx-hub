"""API 网关 / WebSocket 转发层。

对外暴露**稳定路径**，屏蔽内部动态端口：

======================  ==================================================
管理接口（可选管理密钥）  ``/api/models``、``/api/models/{id}/download|start|stop`` …
网关接口（API Key）      ``WS /ws/asr/{id}``、``POST /api/tts/{id}``
======================  ==================================================

WS 转发使用 ``websockets`` 库手写代理，双向透传音频帧，不依赖 nginx 做动态路由。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

import httpx
import psutil
import websockets
from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from sqlmodel import Session

from .auth import (
    create_key,
    delete_key,
    extract_key,
    list_keys,
    require_admin,
    require_api_key,
    verify_key,
)
from .config import settings
from .db import get_session
from .downloader import get_download_manager
from .errors import (
    ModelNotFoundError,
    ModelNotRunningError,
)
from .process_manager import get_process_manager
from .registry import get_registry, get_spec, list_specs
from .schemas import (
    DownloadProgressInfo,
    KeyCreateRequest,
    KeyCreated,
    KeyInfo,
    ModelInfo,
    ModelLogs,
    ProcessUsage,
    ResourceMetrics,
    TtsRequest,
    to_key_info,
    to_model_info,
)

logger = logging.getLogger(__name__)

# 管理接口：可选管理密钥（HUB_ADMIN_KEY）
mgmt_router = APIRouter(prefix="/api", tags=["管理"], dependencies=[Depends(require_admin)])
# 对外网关接口：API Key 校验
gw_router = APIRouter(tags=["网关"])
# 无鉴权的探活接口
public_router = APIRouter(tags=["系统"])

#: WebSocket 自定义关闭码
WS_CLOSE_UNAUTHORIZED = 4401
WS_CLOSE_MODEL_NOT_FOUND = 4404
WS_CLOSE_MODEL_NOT_RUNNING = 4409
WS_CLOSE_UPSTREAM_ERROR = 4500


# =============================================================================
# 模型目录 / 状态
# =============================================================================
@mgmt_router.get("/models", response_model=list[ModelInfo], summary="模型列表（含状态）")
def list_models() -> list[ModelInfo]:
    manager = get_process_manager()
    specs = {spec.id: spec for spec in list_specs()}
    return [to_model_info(specs[state.model_id], state) for state in manager.list_states()]


@mgmt_router.get("/models/{model_id}", response_model=ModelInfo, summary="模型详情")
def get_model(model_id: str) -> ModelInfo:
    try:
        spec = get_spec(model_id)
    except KeyError as exc:
        raise ModelNotFoundError(str(exc)) from exc
    return to_model_info(spec, get_process_manager().get_state(model_id))


@mgmt_router.post("/registry/reload", summary="重新加载 models.yaml")
def reload_registry() -> dict[str, object]:
    from .downloader import validate_registry_downloads

    registry = get_registry(reload=True)
    validate_registry_downloads()
    return {"reloaded": len(registry), "models": sorted(registry)}


# =============================================================================
# 下载管理
# =============================================================================
@mgmt_router.post(
    "/models/{model_id}/download",
    response_model=DownloadProgressInfo,
    summary="开始下载模型",
)
async def start_download(
    model_id: str, force: bool = Query(default=False, description="已下载时强制重新下载")
) -> DownloadProgressInfo:
    try:
        get_spec(model_id)
    except KeyError as exc:
        raise ModelNotFoundError(str(exc)) from exc
    progress = await get_download_manager().start(model_id, force=force)
    return DownloadProgressInfo(**progress.model_dump())


@mgmt_router.get(
    "/models/{model_id}/download/progress",
    response_model=DownloadProgressInfo,
    summary="查询下载进度",
)
def download_progress(model_id: str) -> DownloadProgressInfo:
    try:
        get_spec(model_id)
    except KeyError as exc:
        raise ModelNotFoundError(str(exc)) from exc
    progress = get_download_manager().get_progress(model_id)
    return DownloadProgressInfo(**progress.model_dump())


@mgmt_router.get(
    "/models/{model_id}/download/progress/stream",
    summary="下载进度 SSE 推送",
)
def download_progress_stream(model_id: str) -> StreamingResponse:
    try:
        get_spec(model_id)
    except KeyError as exc:
        raise ModelNotFoundError(str(exc)) from exc

    manager = get_download_manager()

    async def event_stream():
        last: str | None = None
        while True:
            progress = manager.get_progress(model_id)
            payload = progress.model_dump_json()
            if payload != last:
                yield f"event: progress\ndata: {payload}\n\n"
                last = payload
            if progress.status in ("completed", "failed", "cancelled", "idle"):
                yield "event: done\ndata: {}\n\n"
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@mgmt_router.delete(
    "/models/{model_id}/download",
    response_model=DownloadProgressInfo,
    summary="取消下载",
)
async def cancel_download(model_id: str) -> DownloadProgressInfo:
    try:
        get_spec(model_id)
    except KeyError as exc:
        raise ModelNotFoundError(str(exc)) from exc
    progress = await get_download_manager().cancel(model_id)
    return DownloadProgressInfo(**progress.model_dump())


# =============================================================================
# 进程生命周期
# =============================================================================
@mgmt_router.post("/models/{model_id}/start", response_model=ModelInfo, summary="启动模型")
async def start_model(model_id: str) -> ModelInfo:
    try:
        get_spec(model_id)
    except KeyError as exc:
        raise ModelNotFoundError(str(exc)) from exc
    state = await get_process_manager().start(model_id)
    return to_model_info(get_spec(model_id), state)


@mgmt_router.post("/models/{model_id}/stop", response_model=ModelInfo, summary="停止模型")
async def stop_model(model_id: str) -> ModelInfo:
    try:
        get_spec(model_id)
    except KeyError as exc:
        raise ModelNotFoundError(str(exc)) from exc
    state = await get_process_manager().stop(model_id)
    return to_model_info(get_spec(model_id), state)


@mgmt_router.post("/models/{model_id}/restart", response_model=ModelInfo, summary="重启模型")
async def restart_model(model_id: str) -> ModelInfo:
    try:
        get_spec(model_id)
    except KeyError as exc:
        raise ModelNotFoundError(str(exc)) from exc
    state = await get_process_manager().restart(model_id)
    return to_model_info(get_spec(model_id), state)


@mgmt_router.get("/models/{model_id}/status", response_model=ModelInfo, summary="查询运行状态")
def model_status(model_id: str) -> ModelInfo:
    try:
        spec = get_spec(model_id)
    except KeyError as exc:
        raise ModelNotFoundError(str(exc)) from exc
    return to_model_info(spec, get_process_manager().get_state(model_id))


@mgmt_router.get("/models/{model_id}/logs", response_model=ModelLogs, summary="查看进程日志尾部")
def model_logs(
    model_id: str,
    lines: int = Query(default=0, ge=0, le=5000, description="0 表示使用默认行数"),
) -> ModelLogs:
    try:
        get_spec(model_id)
    except KeyError as exc:
        raise ModelNotFoundError(str(exc)) from exc
    manager = get_process_manager()
    count = lines or settings.log_tail_lines
    return ModelLogs(
        model_id=model_id,
        lines=count,
        content=manager.tail_log(model_id, count),
        log_path=str(manager.log_path_of(model_id)),
    )


# =============================================================================
# 资源监控
# =============================================================================
@mgmt_router.get("/system/metrics", response_model=ResourceMetrics, summary="资源监控")
def system_metrics() -> ResourceMetrics:
    manager = get_process_manager()
    processes = [ProcessUsage(**item) for item in manager.resource_usage()]
    memory = psutil.virtual_memory()
    return ResourceMetrics(
        running_models=manager.running_count,
        max_running_models=settings.max_running_models,
        port_pool_start=settings.port_pool_start,
        port_pool_end=settings.port_pool_end,
        system_cpu_percent=psutil.cpu_percent(interval=None),
        system_memory_percent=memory.percent,
        system_memory_used_mb=round(memory.used / (1024 * 1024), 1),
        system_memory_total_mb=round(memory.total / (1024 * 1024), 1),
        processes=processes,
    )


@public_router.get("/api/system/health", summary="服务探活")
def health() -> dict[str, object]:
    manager = get_process_manager()
    return {
        "status": "ok",
        "running_models": manager.running_count,
        "downloaded_models": sum(
            1 for state in manager.list_states() if state.downloaded
        ),
    }


# =============================================================================
# API Key 管理
# =============================================================================
@mgmt_router.post("/keys", response_model=KeyCreated, summary="生成 API Key")
def create_api_key(
    payload: KeyCreateRequest,
    session: Session = Depends(get_session),
) -> KeyCreated:
    record, plain = create_key(session, payload.name)
    return KeyCreated(**to_key_info(record).model_dump(), key=plain)


@mgmt_router.get("/keys", response_model=list[KeyInfo], summary="API Key 列表")
def get_api_keys(session: Session = Depends(get_session)) -> list[KeyInfo]:
    return [to_key_info(record) for record in list_keys(session)]


@mgmt_router.delete("/keys/{key_id}", summary="删除 API Key")
def remove_api_key(key_id: int, session: Session = Depends(get_session)) -> dict[str, object]:
    removed = delete_key(session, key_id)
    if not removed:
        raise ModelNotFoundError(f"API Key {key_id} 不存在")
    return {"deleted": key_id}


# =============================================================================
# 网关：流式 ASR WebSocket 转发
# =============================================================================
async def _authorize_ws(websocket: WebSocket) -> bool:
    if not settings.require_api_key:
        return True
    key = extract_key(websocket)
    if not key:
        return False
    session = next(get_session())
    try:
        return verify_key(session, key)
    finally:
        session.close()


def _resolve_internal_port(model_id: str) -> int:
    try:
        get_spec(model_id)
    except KeyError as exc:
        raise ModelNotFoundError(str(exc)) from exc
    port = get_process_manager().port_of(model_id)
    if port is None:
        raise ModelNotRunningError(
            f"模型 {model_id} 未运行，请先调用 POST /api/models/{model_id}/start"
        )
    return port


@gw_router.websocket("/ws/asr/{model_id}")
async def asr_websocket_proxy(websocket: WebSocket, model_id: str) -> None:
    """把外部 WS 连接双向转发到内部 sherpa-onnx 流式识别进程。"""
    await websocket.accept()

    if not await _authorize_ws(websocket):
        await websocket.close(code=WS_CLOSE_UNAUTHORIZED, reason="API Key 无效")
        return

    try:
        port = _resolve_internal_port(model_id)
    except ModelNotFoundError as exc:
        await websocket.close(code=WS_CLOSE_MODEL_NOT_FOUND, reason=str(exc)[:120])
        return
    except ModelNotRunningError as exc:
        await websocket.close(code=WS_CLOSE_MODEL_NOT_RUNNING, reason=str(exc)[:120])
        return

    upstream_url = f"ws://127.0.0.1:{port}/"
    try:
        async with websockets.connect(upstream_url, max_size=None, open_timeout=10) as upstream:
            await _pump(websocket, upstream)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001 - 上游异常需要反馈给客户端
        logger.warning("转发模型 %s 的 WS 连接失败: %s", model_id, exc)
        with contextlib.suppress(Exception):
            await websocket.close(code=WS_CLOSE_UPSTREAM_ERROR, reason=str(exc)[:120])


async def _pump(websocket: WebSocket, upstream) -> None:
    """双向透传 WebSocket 消息。"""

    async def client_to_upstream() -> None:
        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break
                if message.get("text") is not None:
                    await upstream.send(message["text"])
                elif message.get("bytes") is not None:
                    await upstream.send(message["bytes"])
        finally:
            with contextlib.suppress(Exception):
                await upstream.close()

    async def upstream_to_client() -> None:
        try:
            async for message in upstream:
                if isinstance(message, bytes):
                    await websocket.send_bytes(message)
                else:
                    await websocket.send_text(message)
        finally:
            with contextlib.suppress(Exception):
                await websocket.close()

    tasks = [
        asyncio.create_task(client_to_upstream(), name="ws:c2u"),
        asyncio.create_task(upstream_to_client(), name="ws:u2c"),
    ]
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    for task in done:
        with contextlib.suppress(WebSocketDisconnect, Exception):
            task.result()


# =============================================================================
# 网关：TTS HTTP 转发
# =============================================================================
@gw_router.post("/api/tts/{model_id}", dependencies=[Depends(require_api_key)], summary="语音合成")
async def tts_proxy(model_id: str, payload: TtsRequest, request: Request):
    """把文本转发到内部 TTS 进程，流式回传音频。"""
    port = _resolve_internal_port(model_id)
    spec = get_spec(model_id)
    if spec.type != "tts":
        raise ModelNotFoundError(f"模型 {model_id} 不是 TTS 模型（type={spec.type}）")

    url = f"http://127.0.0.1:{port}/tts"
    client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0))
    try:
        upstream = await client.send(
            client.build_request("POST", url, json=payload.model_dump()),
            stream=True,
        )
    except httpx.HTTPError as exc:
        await client.aclose()
        return JSONResponse(
            status_code=502,
            content={"detail": f"调用内部 TTS 进程失败: {exc}"},
        )

    if upstream.status_code >= 400:
        body = await upstream.aread()
        await upstream.aclose()
        await client.aclose()
        return JSONResponse(
            status_code=502,
            content={"detail": f"内部 TTS 进程返回 {upstream.status_code}: {body[:500].decode('utf-8', 'replace')}"},
        )

    media_type = upstream.headers.get("content-type", "audio/wav")

    async def iterator():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(iterator(), media_type=media_type)
