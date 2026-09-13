# Sherpa Model Hub — 项目设计文档

> 一个基于 sherpa-onnx 的轻量级语音模型管理平台：网页选择/下载/部署 ONNX 语音模型（ASR 流式识别 + TTS），
> 其他服务通过统一 API/WebSocket 调用，Docker Compose 一键部署。

---

## 一、项目定位

解决的问题：市面上没有现成的"Ollama 式"工具专门给 ONNX 语音模型用。本项目做一个**薄管理层**，
把 sherpa-onnx 的多个模型实例管理起来，提供网页操作和统一 API 入口。

不重新造推理引擎的轮子——sherpa-onnx 已经把流式 ASR/TTS 推理做得很好，本项目只负责：
1. 模型的"选择 - 下载 - 生命周期管理"
2. 对外提供**一个稳定的 API 网关**，屏蔽底层多进程/多端口的复杂性

---

## 二、总体架构

```
┌─────────────────────────────────────────────────────────┐
│                      浏览器 (管理界面)                     │
│                 Next.js + TypeScript + MUI                │
└───────────────────────┬───────────────────────────────────┘
                         │ HTTP/WS
┌───────────────────────▼───────────────────────────────────┐
│                    FastAPI 后端 (核心)                     │
│  ┌────────────┐ ┌──────────────┐ ┌──────────────────────┐ │
│  │ 模型仓库模块 │ │ 下载管理模块  │ │  进程管理模块(Runner) │ │
│  │ registry.py│ │ downloader.py│ │   process_manager.py │ │
│  └────────────┘ └──────────────┘ └──────────┬───────────┘ │
│  ┌──────────────────────────────────────────▼───────────┐ │
│  │           API 网关 / WS 转发层 (gateway.py)            │ │
│  └──────────────────────────────┬───────────────────────┘ │
└─────────────────────────────────┼───────────────────────────┘
                                  │ 内部转发(动态端口)
        ┌─────────────────────────┼─────────────────────────┐
        ▼                         ▼                         ▼
┌───────────────┐       ┌───────────────┐       ┌───────────────┐
│ sherpa-onnx    │       │ sherpa-onnx    │       │ sherpa-onnx    │
│ ASR 进程 :7001 │       │ TTS 进程 :7002 │       │ ASR 进程 :7003 │
│ (流式 Zipformer)│      │ (VITS)         │       │ (Paraformer)   │
└───────────────┘       └───────────────┘       └───────────────┘

外部服务 ──API Key/统一入口──▶ FastAPI 网关 /ws/asr/{model_id}, /api/tts/{model_id}
```

技术栈延续你现有习惯，降低上手成本：
- 前端：Next.js + TypeScript + MUI
- 后端：FastAPI（Python）
- 推理引擎：sherpa-onnx（作为子进程被管理，不重写）
- 状态存储：SQLite（轻量，单机够用，无需额外部署 DB）
- 部署：Docker Compose + Nginx（复用你在 devops-mcp-server 项目里的部署模式）

---

## 三、核心模块设计

### 1. 模型仓库模块（Registry）
- 维护一份 `models.yaml`：预置可选模型清单（流式 ASR / 非流式 ASR / TTS），每条包含：
  - `id`、`name`、`type`（asr-streaming / asr-offline / tts）
  - 下载源地址（优先 ModelScope，HuggingFace 作为备用，国内访问更稳）
  - 文件清单（encoder/decoder/joiner/tokens 等）
  - 启动参数模板（sherpa-onnx 对应 CLI 参数）
  - 预估内存占用（用于前端展示 + 后续资源控制）
- 提供 API：`GET /api/models` 返回目录（含"是否已下载""是否运行中"状态）

### 2. 下载管理模块（Downloader）
- 后台异步任务下载模型文件到 `./models/{model_id}/`
- 支持下载进度查询（轮询或 SSE 推送）
- 校验文件完整性（简单的文件大小/数量校验即可，不必上 checksum）
- 失败重试机制（网络问题在国内环境很常见）

### 3. 进程管理模块（Process Manager / Runner）
- 核心职责：启动/停止/重启 sherpa-onnx 对应的 server 进程
- 每个运行中的模型占用一个内部端口（从端口池分配，如 7001-7099）
- 维护进程状态表（运行中/已停止/异常），定时健康检查（进程存活 + 简单探活请求）
- 异常自动重启（借鉴你在 devops-mcp-server 里做的健康检查思路）
- **资源互斥策略**（小服务器关键点）：同时运行的模型数量设上限（可配置，默认 1-2 个），
  超过限制时新启动请求需要排队或提示"请先停止其他模型"

### 4. API 网关 / WS 转发层（Gateway）
- 对外暴露**稳定路径**，屏蔽内部动态端口：
  - `WS /ws/asr/{model_id}` → 转发到对应 sherpa-onnx 进程的 WebSocket 端口，做流式音频转写
  - `POST /api/tts/{model_id}` → 转发到 TTS 进程，返回音频
  - `GET /api/models`、`POST /api/models/{id}/download`、`POST /api/models/{id}/start`、`POST /api/models/{id}/stop`
- WS 转发用 FastAPI + `websockets` 库手写代理即可，不依赖 nginx 做动态路由（避免频繁改 nginx 配置）

### 5. 前端管理界面
- 模型列表页：分类展示（ASR 流式 / ASR 离线 / TTS），显示下载/运行状态
- 模型详情：参数说明、内存占用预估、下载进度条
- 操作按钮：下载 / 启动 / 停止 / 查看日志
- 简单的资源监控面板：当前运行进程的 CPU/内存占用（用 `psutil` 采集）
- API Key 管理页：生成/查看用于外部服务调用网关的 Key

---

## 四、关键技术难点与应对

| 难点 | 应对方案 |
|---|---|
| 动态端口的 WS 转发 | FastAPI 层手写代理转发，不用 nginx 做动态 upstream |
| 不同模型启动参数差异大 | `models.yaml` 里用参数模板 + 变量占位符，Runner 渲染后拼接 CLI 命令 |
| 国内下载 HuggingFace 不稳定 | 优先 ModelScope 源，配置文件里做多源 fallback |
| 小服务器内存有限，多模型并发 | 运行数量上限 + 排队机制 + 前端显式提示资源占用 |
| 进程崩溃/僵死 | 健康检查 + 自动重启 + 前端可见的异常状态 |
| 外部服务鉴权 | 简单 API Key 机制（Header 校验），不必上 OAuth |

---

## 五、目录结构建议

```
sherpa-model-hub/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── registry.py          # 模型仓库读取/查询
│   │   ├── downloader.py        # 下载任务管理
│   │   ├── process_manager.py   # sherpa-onnx 进程生命周期
│   │   ├── gateway.py           # 对外 API/WS 网关
│   │   ├── models.py            # SQLite ORM (SQLModel/SQLAlchemy)
│   │   ├── auth.py               # API Key 校验
│   │   └── config/
│   │       └── models.yaml      # 预置模型目录配置
│   ├── models/                  # 下载的模型文件存放目录（挂载卷）
│   └── requirements.txt
├── frontend/
│   ├── app/
│   │   ├── models/page.tsx          # 模型列表页
│   │   ├── models/[id]/page.tsx     # 模型详情页
│   │   ├── keys/page.tsx            # API Key 管理页
│   │   └── layout.tsx
│   ├── components/
│   │   ├── ModelCard.tsx
│   │   ├── DownloadProgress.tsx
│   │   └── ResourceMonitor.tsx
│   ├── lib/api.ts                    # 封装后端 API 调用
│   └── package.json
├── docker-compose.yml
├── Dockerfile.backend
├── Dockerfile.frontend
└── README.md
```

---

## 六、Docker Compose 设计要点
- `backend` 容器：内含 sherpa-onnx 可执行文件 + FastAPI，挂载 `models/` 卷持久化已下载模型
- `frontend` 容器：Next.js 生产构建（`next build` + `next start`，或导出静态资源交给 Nginx），并通过 Nginx（或 Next.js 自带的 rewrites/proxy 配置）反代 `/api`、`/ws` 到 backend
- 数据卷：`models/`、SQLite 数据库文件都要挂载，避免容器重建丢数据
- 环境变量：模型存储路径、最大并发模型数、API Key 密钥等可配置

---

## 七、开发任务清单（TODO，供 AI 编程工具执行）

> 使用方式：按 Phase 顺序交给 AI 编程工具（如 Claude Code）逐项实现，每个 Phase 完成后本地验证再进入下一个。

### Phase 0：项目初始化
- [ ] 初始化 monorepo 结构（`backend/` + `frontend/`），按上面目录结构建立骨架
- [ ] 后端：FastAPI 项目初始化，配置 `requirements.txt`（fastapi, uvicorn, sqlmodel, httpx, psutil, pyyaml, websockets）
- [ ] 前端：Next.js（App Router）+ TypeScript 项目初始化，接入 MUI（`@mui/material` + `@mui/icons-material`）
- [ ] 编写 `models.yaml` 初始版本，先内置 2-3 个模型（1 个流式 ASR、1 个 TTS）用于联调

### Phase 1：模型仓库 + 下载模块
- [ ] 实现 `registry.py`：解析 `models.yaml`，提供模型列表查询函数
- [ ] 实现 SQLite 数据模型：`ModelState`（model_id, downloaded, download_progress, running, port, pid, last_error）
- [ ] 实现 `downloader.py`：异步下载任务（用 `httpx` 流式下载 + 进度回调），支持从 ModelScope/HuggingFace 拉取
- [ ] API：`GET /api/models`（返回目录+状态）、`POST /api/models/{id}/download`、`GET /api/models/{id}/download/progress`
- [ ] 单元测试：模拟下载一个小文件验证进度追踪逻辑

### Phase 2：进程管理模块
- [ ] 实现 `process_manager.py`：
  - [ ] 端口分配池（7001-7099，记录占用情况）
  - [ ] 根据 `models.yaml` 里的参数模板拼接 sherpa-onnx 启动命令
  - [ ] 用 `subprocess.Popen` 启动进程，记录 pid，写入数据库
  - [ ] 健康检查：定时任务（`asyncio` 后台任务）探测进程存活 + 简单请求验活
  - [ ] 异常自动重启逻辑（重试次数上限，避免死循环拉起崩溃进程）
  - [ ] 并发数量限制：启动前检查当前运行模型数是否超过配置上限
- [ ] API：`POST /api/models/{id}/start`、`POST /api/models/{id}/stop`、`GET /api/models/{id}/status`

### Phase 3：API 网关 / WS 转发
- [ ] 实现 `gateway.py`：
  - [ ] `WS /ws/asr/{model_id}`：接收外部连接，建立到内部 sherpa-onnx 进程端口的 WS 连接，双向转发数据
  - [ ] `POST /api/tts/{model_id}`：转发文本到内部 TTS 进程，返回音频流
  - [ ] 处理模型未运行时的报错提示（引导先调用 start）
- [ ] 实现 `auth.py`：API Key 生成、存储、Header 校验中间件
- [ ] API：`POST /api/keys`（生成）、`GET /api/keys`（列表）、`DELETE /api/keys/{id}`

### Phase 4：前端管理界面（Next.js + MUI）
- [ ] 模型列表页（`app/models/page.tsx`）：用 MUI `Card`/`Chip` 展示分类、状态标签（未下载/已下载/运行中）、操作按钮
- [ ] 下载进度：轮询或 SSE，用 MUI `LinearProgress` 展示实时进度
- [ ] 模型详情页（`app/models/[id]/page.tsx`）：展示参数、内存预估、日志尾部内容
- [ ] 启动/停止操作 + 二次确认弹窗（MUI `Dialog`，尤其是停止运行中模型时）
- [ ] API Key 管理页面（`app/keys/page.tsx`）：用 MUI `Table` 展示 Key 列表，生成/删除操作
- [ ] 简单资源监控卡片（当前运行进程数、CPU/内存占用，用 `psutil` 在后端采集后前端用 MUI `Card` + 简单图表展示）
- [ ] API 请求统一封装在 `lib/api.ts`，`app/` 内页面通过它调用后端接口（避免每个组件里裸写 fetch）

### Phase 5：Docker 化与集成联调
- [ ] 编写 `Dockerfile.backend`（含 sherpa-onnx 可执行文件安装步骤）
- [ ] 编写 `Dockerfile.frontend`（多阶段构建：build + nginx 提供静态资源）
- [ ] 编写 `docker-compose.yml`，挂载模型存储卷和数据库文件卷
- [ ] 联调测试：从外部服务通过 WS 调用一次完整的流式识别流程
- [ ] 编写 README：部署步骤、API 文档、模型新增方式说明

### Phase 6（可选增强，视需求再做）
- [ ] 支持自定义模型接入（用户上传自己的 ONNX 模型 + 手动填写启动参数）
- [ ] 支持多机部署时的模型分发（当前设计默认单机）
- [ ] 接入 Prometheus/简单日志采集做更完善的监控
- [ ] 下载校验加入 checksum 校验

---

## 八、给 AI 编程工具的补充说明（Prompt 提示）

将本文档直接提供给 AI 编程工具时，建议附加以下约束，避免它跑偏：

1. **不要重新实现语音识别/合成逻辑**，所有推理都通过调用 sherpa-onnx 官方发布的可执行文件完成，本项目只做进程管理和 API 转发。
2. 优先保证 **Phase 0-3（后端核心）** 的正确性，前端可以先用最简单的表格+按钮实现，不追求美观。
3 . 每个 Phase 完成后运行一次端到端验证（哪怕是手动 curl / wscat 测试），确认可用再进入下一阶段，不要一次性把所有模块都写完再联调。
4. 涉及进程管理和端口分配的代码要重点写测试或手动验证步骤，这是本项目最容易出 bug 的地方。