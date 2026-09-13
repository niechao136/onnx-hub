"""统一异常定义。

所有业务异常都继承 ``HubError``，由 ``main.py`` 中的异常处理器统一转换成
``{"detail": "..."}`` 形式的 JSON 响应，避免在每个路由里写 try/except。
"""

from __future__ import annotations


class HubError(Exception):
    """业务异常基类。"""

    status_code: int = 500
    #: 是否在响应体中额外返回 ``code`` 字段，便于调用方分支处理
    code: str = "internal_error"

    def __init__(self, detail: str, status_code: int | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        if status_code is not None:
            self.status_code = status_code


class RegistryError(HubError):
    """models.yaml 配置错误。"""

    status_code = 500
    code = "registry_error"


class ModelNotFoundError(HubError):
    status_code = 404
    code = "model_not_found"


class ModelNotDownloadedError(HubError):
    status_code = 409
    code = "model_not_downloaded"


class ModelAlreadyRunningError(HubError):
    status_code = 409
    code = "model_already_running"


class ModelNotRunningError(HubError):
    status_code = 409
    code = "model_not_running"


class ModelAlreadyDownloadingError(HubError):
    status_code = 409
    code = "model_already_downloading"


class ResourceLimitError(HubError):
    status_code = 409
    code = "resource_limit"


class DownloadError(HubError):
    status_code = 502
    code = "download_failed"


class StartError(HubError):
    status_code = 500
    code = "start_failed"


class AuthError(HubError):
    status_code = 401
    code = "unauthorized"


class InvalidModelSpecError(HubError):
    """用户提交的模型定义不合法。"""

    status_code = 400
    code = "invalid_model_spec"


class CustomModelExistsError(HubError):
    status_code = 409
    code = "custom_model_exists"


class BuiltinModelProtectedError(HubError):
    """预置模型（models.yaml）不允许通过接口修改/删除。"""

    status_code = 400
    code = "builtin_model_protected"
