"""FastAPI 应用入口。

启动顺序：
1. 建表、加载并校验 ``models.yaml``
2. 校正数据库中模型的「已下载」状态
3. 清理上一次遗留的孤儿进程，重置运行态
4. 启动健康检查后台任务

退出时停止所有子进程与下载任务。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__
from .config import settings
from .db import init_db
from .downloader import get_download_manager, validate_registry_downloads
from .errors import HubError
from .gateway import gw_router, mgmt_router, public_router
from .process_manager import get_process_manager
from .registry import get_registry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger("sherpa-model-hub")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    registry = get_registry()
    validate_registry_downloads()

    manager = get_process_manager()
    manager.reconcile()
    await manager.start_health_loop()

    logger.info(
        "Sherpa Model Hub 已启动 | 模型数量=%s 模型目录=%s 端口池=%s-%s 并发上限=%s 网关鉴权=%s",
        len(registry),
        settings.model_dir,
        settings.port_pool_start,
        settings.port_pool_end,
        settings.max_running_models,
        "开启" if settings.require_api_key else "关闭",
    )
    try:
        yield
    finally:
        logger.info("正在关闭：停止子进程与下载任务…")
        await get_download_manager().shutdown()
        await manager.shutdown()


app = FastAPI(
    title="Sherpa Model Hub",
    description=(
        "基于 sherpa-onnx 的轻量级语音模型管理平台：网页选择/下载/部署 ONNX 语音模型，"
        "其他服务通过统一 API/WebSocket 调用。"
    ),
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


@app.exception_handler(HubError)
async def hub_error_handler(request: Request, exc: HubError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": exc.code},
    )


app.include_router(public_router)
app.include_router(mgmt_router)
app.include_router(gw_router)


@app.get("/", tags=["系统"], summary="服务信息")
def root() -> dict[str, object]:
    registry = get_registry()
    return {
        "name": "sherpa-model-hub",
        "version": __version__,
        "models": len(registry),
        "docs": "/docs",
        "endpoints": {
            "list_models": "GET /api/models",
            "download": "POST /api/models/{model_id}/download",
            "start": "POST /api/models/{model_id}/start",
            "stop": "POST /api/models/{model_id}/stop",
            "asr_websocket": "WS /ws/asr/{model_id}",
            "tts": "POST /api/tts/{model_id}",
            "keys": "GET/POST /api/keys",
            "metrics": "GET /api/system/metrics",
        },
    }


def run() -> None:
    """``python -m app.main`` 的入口。"""
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    run()
