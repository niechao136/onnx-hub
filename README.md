# Sherpa Model Hub

基于 [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) 的轻量级语音模型管理平台。

市面上的模型管理工具（如 Ollama）基本只服务 LLM，ONNX 语音模型缺少"选择 → 下载 → 部署 → 调用"的一站式体验。
本项目做一个**薄管理层**：不重写推理引擎，只负责 **模型仓库 / 下载 / 进程生命周期管理**，并对外提供
**一个稳定的 API 网关**，屏蔽底层多进程、动态端口的复杂性。

```
浏览器管理界面 (Next.js + MUI)
        │ HTTP (SSE 下载进度)
        ▼
FastAPI 后端 ── registry.py      模型仓库（models.yaml）
             ├─ downloader.py    下载任务（多镜像 fallback + 重试 + 进度）
             ├─ process_manager.py 端口池 / 启动停止 / 健康检查 / 自动重启 / 并发限制
             ├─ gateway.py       稳定网关：WS /ws/asr/{id}、POST /api/tts/{id}
             └─ auth.py          API Key（只存哈希）
        │ 内部转发（动态端口 7001-7099）
        ▼
sherpa-onnx 子进程（ASR 流式 / ASR 离线 / TTS），推理 100% 由官方可执行文件 / 官方 Python API 完成
```

---

## 一、目录结构

```
onnx-hub/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 入口 + lifespan
│   │   ├── config.py            # 配置（HUB_ 前缀环境变量）
│   │   ├── db.py                # SQLite 引擎/会话
│   │   ├── models.py            # SQLModel：ModelState / DownloadTask / ApiKey
│   │   ├── registry.py          # models.yaml 解析与命令模板渲染
│   │   ├── downloader.py        # 下载任务管理（进度 / 重试 / 多镜像）
│   │   ├── process_manager.py   # 端口池 + 子进程生命周期 + 健康检查
│   │   ├── gateway.py           # 管理接口 + WS/HTTP 网关转发
│   │   ├── auth.py              # API Key 生成与校验
│   │   ├── errors.py            # 统一业务异常
│   │   ├── schemas.py           # 请求/响应模型
│   │   ├── runners/tts_server.py# TTS 的 HTTP 薄封装（基于官方 OfflineTts API）
│   │   └── config/models.yaml   # 预置模型目录（新增模型只改这个文件）
│   ├── tests/                   # pytest（registry / downloader / process_manager / api）
│   └── models/                  # 下载的模型文件（运行期生成，不入库）
├── frontend/
│   ├── app/                     # App Router：/models、/models/[id]、/keys
│   ├── components/              # ModelCard / DownloadProgress / ResourceMonitor / AppShell …
│   ├── lib/                     # api.ts（统一请求封装）、types.ts、format.ts
│   └── package.json
├── deploy/nginx.conf            # 可选统一入口（含 WS 升级）
├── pyproject.toml               # 后端依赖与工具配置（唯一依赖声明处）
├── uv.lock                      # 依赖锁定文件（由 uv 维护，应提交）
├── Dockerfile.backend
├── Dockerfile.frontend
├── docker-compose.yml
└── .env.example
```

> **依赖管理**：后端 Python 依赖**只在根 `pyproject.toml` 声明**（`[project].dependencies`
> 为运行时依赖、`[dependency-groups].dev` 为测试依赖），由 uv 锁定到 `uv.lock`；
> 前端依赖仍在 `frontend/package.json`。
> 增删依赖请用 `uv add <pkg>` / `uv add --dev <pkg>`，不要手工编辑锁文件。

---

## 二、快速开始

### 方式 A：Docker Compose（推荐）

```bash
# 1) 可选：复制环境变量模板
cp .env.example .env

# 2) 构建并启动
docker compose up -d --build

# 3) 如需单端口统一入口（前端 + /api + /ws，推荐生产使用）
docker compose --profile proxy up -d
```

启动后：

| 服务 | 地址 | 说明 |
|---|---|---|
| 管理界面 | http://localhost:3000 | 或经 Nginx：http://localhost:10100 |
| 后端 API 文档 | http://localhost:8000/docs | Swagger UI |
| WS 网关 | ws://localhost:8000/ws/asr/{model_id} | 需直连后端端口或经 Nginx /ws |

> 模型文件挂在 `models` 卷（容器内 `/data/models`），SQLite 与日志挂在 `hub-data` 卷（`/hubdata`），
> 容器重建不会丢数据。

### 方式 B：本地开发

后端（Python ≥ 3.11，需要 [uv](https://docs.astral.sh/uv/)）：

```bash
# 在仓库根目录安装依赖（读取 pyproject.toml，创建根 .venv 并生成/校验 uv.lock）
uv sync

# 启动服务（uvicorn 需要以 backend 为工作目录，才能找到 app 包）
cd backend
uv run --project .. uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 或者激活虚拟环境后启动（Windows / Linux 分别对应 .venv\Scripts 与 .venv/bin）
#   ..\.venv\Scripts\Activate.ps1  ;  python -m uvicorn app.main:app --port 8000 --reload
```

前端（Node ≥ 20）：

```bash
cd frontend
npm install
cp .env.example .env.local     # 按需修改
npm run dev                    # http://localhost:3000
```

### 安装推理运行时

- **ASR（流式/离线）**：需要 sherpa-onnx 官方预编译可执行文件
  `sherpa-onnx-online-websocket-server`、`sherpa-onnx-offline-websocket-server`。
  从 [sherpa-onnx releases](https://github.com/k2-fsa/sherpa-onnx/releases) 下载对应平台的压缩包，
  解压后把 `bin/` 加入 `PATH`（Docker 镜像已自动完成）。
- **TTS**：官方未提供 TTS server 可执行文件，因此本项目附带 `app/runners/tts_server.py`
  （仅做 HTTP 协议适配，推理调用官方 `sherpa_onnx.OfflineTts`）：
  ```bash
  # 可选依赖，不写进 pyproject 以免所有人都被迫下载大 wheel；
  # 如需固化到依赖里，用 uv add sherpa-onnx（会同步更新 uv.lock）
  uv pip install sherpa-onnx
  ```

> 未安装运行时不影响平台本身运行：下载、列表、Key 管理仍可用，启动模型时会返回明确的
> `未找到可执行文件 ...` 错误提示。

---

## 三、配置项（环境变量）

全部支持 `HUB_` 前缀，或写入 `backend/.env`。

| 变量 | 默认值 | 说明 |
|---|---|---|
| `HUB_MODEL_DIR` | `backend/models` | 已下载模型存放目录（Docker：`/data/models`） |
| `HUB_DATA_DIR` | `backend/data` | SQLite 与日志目录（Docker：`/hubdata`） |
| `HUB_DB_PATH` | `data_dir/hub.db` | SQLite 文件路径 |
| `HUB_MODELS_CONFIG` | `app/config/models.yaml` | 模型目录配置 |
| `HUB_PORT_POOL_START` / `HUB_PORT_POOL_END` | `7001` / `7099` | 内部端口池范围 |
| `HUB_MAX_RUNNING_MODELS` | `2` | 同时运行的模型数量上限，超限直接给出提示 |
| `HUB_START_TIMEOUT` | `60` | 启动后等待端口就绪的超时（秒） |
| `HUB_STOP_TIMEOUT` | `10` | 优雅停止等待时间（秒），超时强杀 |
| `HUB_HEALTH_CHECK_INTERVAL` | `10` | 健康检查周期（秒） |
| `HUB_MAX_RESTART_ATTEMPTS` | `3` | 异常自动重启次数上限，避免死循环拉起崩溃进程 |
| `HUB_DOWNLOAD_RETRIES` | `3` | 单文件下载重试次数（在镜像之间轮换） |
| `HUB_DOWNLOAD_TIMEOUT` | `60` | 下载请求超时（秒） |
| `HUB_DOWNLOAD_BACKOFF` | `2.0` | 重试退避基数（秒），实际等待 = base × 2^n |
| `HUB_REQUIRE_API_KEY` | `true` | 网关接口是否强制校验 API Key |
| `HUB_ADMIN_KEY` | 空 | 管理接口密钥；留空表示管理接口不鉴权（内网/开发） |
| `HUB_CORS_ORIGINS` | `*` | 允许的跨域来源，逗号分隔 |
| `HUB_LOG_TAIL_LINES` | `200` | 详情页默认返回的日志行数 |

---

## 四、API 文档

### 4.1 模型仓库 / 状态

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/models` | 模型列表（含下载进度、运行状态、端口、内存预估） |
| `GET` | `/api/models/{model_id}` | 模型详情（文件清单、启动命令模板、网关路径） |
| `POST` | `/api/registry/reload` | 重新加载 `models.yaml`（改完配置无需重启） |

### 4.2 下载管理

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/models/{model_id}/download` | 开始下载（`?force=true` 强制重下） |
| `GET` | `/api/models/{model_id}/download/progress` | 查询进度（轮询） |
| `GET` | `/api/models/{model_id}/download/progress/stream` | SSE 实时推送进度 |
| `DELETE` | `/api/models/{model_id}/download` | 取消下载 |

### 4.3 进程生命周期

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/models/{model_id}/start` | 启动（自动分配内部端口，等待端口就绪） |
| `POST` | `/api/models/{model_id}/stop` | 停止（优雅退出，超时强杀，回收端口） |
| `POST` | `/api/models/{model_id}/restart` | 重启 |
| `GET` | `/api/models/{model_id}/status` | 查询状态 |
| `GET` | `/api/models/{model_id}/logs?lines=200` | 子进程日志尾部 |

### 4.4 资源监控与 API Key

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/system/health` | 探活（无鉴权） |
| `GET` | `/api/system/metrics` | 系统 CPU/内存 + 每个运行进程的 CPU/内存/运行时长/重启次数 |
| `POST` | `/api/keys` | 生成 Key（**明文只返回一次**） |
| `GET` | `/api/keys` | Key 列表（只返回前缀） |
| `DELETE` | `/api/keys/{key_id}` | 删除 Key |

### 4.5 对外网关（稳定路径）

| 方法 | 路径 | 说明 |
|---|---|---|
| `WS` | `/ws/asr/{model_id}` | 双向转发到该模型内部 ASR 进程的 WebSocket（流式识别） |
| `POST` | `/api/tts/{model_id}` | 转发文本到 TTS 进程，返回 `audio/wav` |

鉴权支持三种方式（按优先级）：`Authorization: Bearer <key>`、`X-API-Key: <key>`、
`?api_key=<key>`（浏览器 WebSocket 无法自定义 Header 时的兜底）。

模型未运行时返回明确提示：

- HTTP：`409 {"detail": "模型 xxx 未运行，请先调用 POST /api/models/xxx/start", "code": "model_not_running"}`
- WS：自定义关闭码 `4409`（未运行）、`4404`（模型不存在）、`4401`（Key 无效）、`4500`（上游异常）

---

## 五、调用示例

### 5.1 生成 API Key 并合成语音（TTS）

```bash
# 1) 生成 Key
curl -X POST http://127.0.0.1:8000/api/keys \
  -H 'Content-Type: application/json' \
  -d '{"name":"demo"}'
# => {"id":1,"name":"demo","key_prefix":"sk-hub-AbCdEf","key":"sk-hub-xxxxx..."}

# 2) 启动 TTS 模型（需先下载）
curl -X POST http://127.0.0.1:8000/api/models/vits-zh-aishell3/download
curl -X POST http://127.0.0.1:8000/api/models/vits-zh-aishell3/start

# 3) 合成语音
curl -X POST http://127.0.0.1:8000/api/tts/vits-zh-aishell3 \
  -H "X-API-Key: sk-hub-xxxxx..." \
  -H 'Content-Type: application/json' \
  -d '{"text":"你好，这是 sherpa model hub 的语音合成示例。","speaker_id":0,"speed":1.0}' \
  --output out.wav
```

### 5.2 流式识别（WebSocket）

```bash
# 先启动流式 ASR 模型
curl -X POST http://127.0.0.1:8000/api/models/zipformer-streaming-bilingual-zh-en/download
curl -X POST http://127.0.0.1:8000/api/models/zipformer-streaming-bilingual-zh-en/start

# 连接网关（音频帧格式遵循 sherpa-onnx 官方 websocket 协议：16-bit PCM、采样率 16000）
wscat -c "ws://127.0.0.1:8000/ws/asr/zipformer-streaming-bilingual-zh-en?api_key=sk-hub-xxxxx..."
```

管理界面「模型详情 → 调用方式 → 连接测试」也提供了连通性自检（验证网关转发链路是否打通）。

### 5.3 下载进度的 SSE 订阅

```bash
curl -N http://127.0.0.1:8000/api/models/vits-zh-aishell3/download/progress/stream
# event: progress
# data: {"model_id":"vits-zh-aishell3","status":"running","progress":0.33,...}
```

---

## 六、新增模型（只改 YAML，不改代码）

编辑 `backend/app/config/models.yaml`，照抄一条并替换文件清单与启动参数，然后调用
`POST /api/registry/reload`（或重启后端）即可。

```yaml
  - id: my-tts-model                 # 唯一 id，也是 URL 中的 {model_id}
    name: 我的 TTS 模型
    type: tts                        # asr-streaming | asr-offline | tts
    language: zh
    description: 说明文字
    memory_mb: 800                   # 内存预估，用于前端展示与资源提示
    tags: [tts, zh]
    source:
      repo: org/model                # 上游仓库名，替换镜像模板里的 {repo}
      mirrors:                       # 按顺序尝试，{repo}/{file} 为占位符
        - https://huggingface.co/{repo}/resolve/main/{file}
        - https://modelscope.cn/models/{repo}/resolve/master/{file}
    files:                           # 需要下载的文件，key 会成为启动参数占位符
      - { key: model,   path: model.onnx }
      - { key: tokens,  path: tokens.txt }
      - { key: lexicon, path: lexicon.txt }
    start:
      command: "{python}"            # {python} = 当前解释器；也可写官方可执行文件名/绝对路径
      args:
        - -m
        - app.runners.tts_server
        - --port={port}
        - --vits-model={model}
        - --tokens={tokens}
        - --lexicon={lexicon}
      cwd: backend_dir               # model_dir | backend_dir
      health: { kind: http, path: /health }   # 或 { kind: tcp }
      startup_grace: 1.0             # 端口就绪后额外等待，规避抖动
```

占位符：`{port}`、`{model_dir}`、`{data_dir}`、`{backend_dir}`、`{python}` 以及 `files` 中定义的每个 `key`。
配置在启动时会做校验（重复 id、空文件清单、未知占位符、key 与保留字冲突都会直接报错）。

---

## 七、测试

```bash
# 后端（41 个用例，覆盖仓库解析、下载进度/重试/多镜像、端口池、启动停止、自动重启、并发限制、API/WS）
uv run pytest -q

# 前端类型检查 + 构建
cd frontend
npm run typecheck && npm run build
```

进程管理相关用例不依赖 sherpa-onnx：用一个假 server 脚本替代真实推理进程。

---

## 八、故障排查

| 现象 | 排查方向 |
|---|---|
| 启动模型报 `未找到可执行文件 'sherpa-onnx-...'` | 未安装 sherpa-onnx release 包，或未加入 `PATH`；也可在 YAML 里写绝对路径 |
| 启动模型报 `端口 xxx 未就绪` | 响应中会附带子进程日志尾部；常见原因是模型文件缺失或参数拼错 |
| 下载失败 `HTTP 404` | 上游仓库文件清单变更，核对 `models.yaml` 中 `files.path` 是否为仓库真实文件名 |
| 下载很慢/超时 | 交换 `source.mirrors` 顺序（国内优先 ModelScope），或调大 `HUB_DOWNLOAD_TIMEOUT` |
| 启动被拒 `同时运行的模型数量已达上限` | 调大 `HUB_MAX_RUNNING_MODELS` 或先停止其他模型（小内存服务器建议保持 1-2） |
| 模型状态变成「异常」 | 连续健康检查失败或进程崩溃，已按上限自动重启；查看日志与 `last_error` |
| 网关 401 | Key 无效或 `HUB_REQUIRE_API_KEY=true` 但请求未携带 Key |
| WS 连接不上 | 浏览器需直连后端 8000 端口；或配置 `NEXT_PUBLIC_WS_BASE`、使用 Nginx（`/ws` 已带 Upgrade 头） |
| 前端页面无法访问后端 | 检查 `BACKEND_URL`（容器内应为 `http://backend:8000`），或改用 `/docs` 直接验证后端 |

---

## 九、设计约束

1. **不重新实现推理**：ASR 通过官方 `sherpa-onnx-*-websocket-server` 可执行文件完成；
   TTS 通过官方 `sherpa_onnx.OfflineTts` Python API 完成（`runners/tts_server.py` 仅做 HTTP 协议适配）。
2. **稳定路径 + 动态端口**：调用方只依赖 `/ws/asr/{model_id}`、`/api/tts/{model_id}`，
   内部端口由网关层屏蔽，WS 转发由 FastAPI 手写代理完成，不依赖 nginx 做动态 upstream。
3. **资源受控**：运行数量上限 + 端口池 + 健康检查 + 自动重启上限，适配小内存单机部署。
