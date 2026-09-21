# License

本项目基于 [GNU Affero General Public License v3.0 (AGPLv3)](https://www.gnu.org/licenses/agpl-3.0.html) 开源。任何修改、分发或通过网络提供本项目服务的行为，均须以 AGPLv3 条款公开对应源代码。详见 [LICENSE](LICENSE)。

---

# FreeMoCap MCP — 云端动捕 MCP 服务（FMC-Cloud-MCP）

> 将 FreeMoCap 从桌面应用改造成云端 MCP 工具服务：去掉前端，保留后端计算能力，增加 2D 姿态输出通道，通过 MCP 协议供 AI Agent 平台调用。

## 项目概述

FreeMoCap 是一个开源无标记动作捕捉系统。本分支（`freemocap_MCP`）对其进行云端 MCP 化改造，目标是把 FreeMoCap 的 Python 后端（FastAPI）从 Electron 桌面应用中剥离出来，独立部署，并通过 [Model Context Protocol (MCP)](https://modelcontextprotocol.io) 暴露动捕工具，让 AI Agent 平台可以直接调用 2D 姿态提取与 3D 骨架重建能力。

### 核心改造方向

| 维度 | 改造前（上游 FreeMoCap） | 改造后（本分支） |
|---|---|---|
| 形态 | Electron 桌面应用 | 云端 MCP Server（Docker 容器） |
| 前端 | React + Electron | **去除**，仅保留后端 |
| 调用方式 | GUI 点击 | MCP 工具调用（JSON-RPC over HTTP/SSE） |
| 输出 | 必须跑完整 3D 管线 | 新增 **2D 独立通道**，可只输出 2D 姿态 |
| 存储 | 本地文件系统 | S3/MinIO 存储池，按 `{user_id}/{session_id}/` 隔离 |
| 任务 | 同步阻塞 | Redis + Celery 异步队列，支持进度查询 |
| 资源 | 单机 | GPU Worker 独立队列，多任务调度 |
| 租户 | 单用户 | 多租户隔离（配额 + 并发限制） |

### 范围

**包含**
- FreeMoCap Python 后端剥离与独立部署
- MCP Server 包装（`fastapi-mcp`）
- 2D 姿态输出通道开发
- 云存储（S3/MinIO）集成
- 异步任务队列（Redis + Celery）
- GPU 资源调度
- 多租户隔离
- 生产化部署（Docker Compose / K8s）

**不包含**
- FreeMoCap 前端（Electron/React）的维护
- 新的姿态估计算法开发
- 新的 3D 重建算法开发
- AI Agent 平台本身的开发

## 当前状态

> **最新更新**：2026-09-21 — P5 任务队列集成完成，支持 Celery + Redis 异步任务执行（无 Redis 时自动降级为进程内线程池）；`POST /tasks/submit`、`GET /tasks/{id}`、`GET /tasks/{id}/result`、`DELETE /tasks/{id}` 端点全部验证通过。
>
> **可用性**：✅ MCP 协议层 + 2D 单图姿势检测 + 存储池（local/S3）+ 任务队列（进程内降级可用，Celery 待 Redis 环境验证）可正常使用；完整动捕管线（视频/3D）待后续阶段实现。

## 更新日志

| 日期 | 阶段 | 更新内容 | 状态 | 可用性 |
|---|---|---|---|---|
| 2026-09-21 | P5 | 任务队列：新增 `freemocap/services/task_queue.py`，`InProcessTaskQueue`（线程池，开发降级）+ `CeleryTaskQueue`（Redis broker/backend）；`tasks_router` 提供提交/状态轮询/结果获取/取消端点；内置 `demo.echo`、`demo.long_task` 测试任务支持进度上报 | ✅ 已完成 | ✅ 进程内后端验证通过，Celery 后端待 Redis 环境验证 |
| 2026-09-21 | P4 | 存储池集成：新增 `freemocap/services/storage.py` 抽象层（`LocalStorageBackend` + `S3StorageBackend`），`storage_router` 提供上传/下载/URL/删除/存在性检查端点；后端由 `FMC_STORAGE_BACKEND` 环境变量切换，S3 凭证全部走环境变量不硬编码 | ✅ 已完成 | ✅ 本地后端验证通过，S3 后端待 MinIO 环境验证 |
| 2026-09-21 | P3 | 新增 2D 姿势检测路由 `pose_2d_router`：`POST /pose-2d/image` 上传图片返回 OpenPose 风格骨架 PNG（黑底+彩色骨骼+关节圆圈），`POST /pose-2d/json` 返回 33 个 MediaPipe 关键点；使用 MediaPipe Pose 检测 + OpenCV 绘制 | ✅ 已完成 | ✅ 单图 2D 姿势检测可用 |
| 2026-09-21 | P2 | 集成 `fastapi-mcp`，将 FastAPI 路由自动暴露为 MCP 工具；挂载 `/mcp`（Streamable HTTP）和 `/sse`（SSE）传输端点；`initialize` + `tools/list` 握手验证通过 | ✅ 已完成 | ✅ MCP 端点可连通，现有 REST 端点自动成为 MCP 工具 |
| 2026-09-21 | P0~P1 | 仓库 fork 初始化；重写 README（AGPLv3 声明、项目介绍、架构、12 阶段计划）；确认后端 `__main__.py` 可独立作为 FastAPI 服务运行 | ✅ 已完成 | ✅ 后端可独立启动 |
| — | P6 | 完整 3D 管线云端跑通 | ⏳ 待开始 | — |
| — | P7~P12 | 2D 增强 / 多租户 / GPU 调度 / 生产化部署 / 测试验收 / 文档交付 | ⏳ 待开始 | — |

## 总体架构

```text
┌─────────────────────────────────────────────────────────────┐
│                    AI Agent 平台 (MCP Host)                  │
│  ┌─────────────┐  ┌─────────────┐  ┌───────────────────┐   │
│  │ LLM 核心    │  │ 任务规划器  │  │ MCP Client        │   │
│  └─────────────┘  └─────────────┘  └─────────┬─────────┘   │
│                                              │             │
│  ┌───────────────────────────────────────────┼───────────┐ │
│  │              存储池 (S3/MinIO)             │           │ │
│  │  uploads/{user_id}/{session_id}/           │           │ │
│  │  outputs/{user_id}/{session_id}/           │           │ │
│  └───────────────────────────────────────────┼───────────┘ │
└──────────────────────────────────────────────┼─────────────┘
                                               │ MCP (JSON-RPC)
                                               │ HTTP/SSE
                                               ▼
┌─────────────────────────────────────────────────────────────┐
│              FreeMoCap MCP Server (独立容器)                  │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  MCP 工具层 (fastapi-mcp)                              │  │
│  │  ping / upload_video / process_2d / process_3d / ...  │  │
│  └──────────────────────┬────────────────────────────────┘  │
│                         ▼                                   │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  FastAPI 服务层 → Redis 队列 → 返回 task_id            │  │
│  └──────────────────────┬────────────────────────────────┘  │
│                         ▼                                   │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Celery Worker (GPU/CPU) 执行 FreeMoCap 管线           │  │
│  └──────────────────────┬────────────────────────────────┘  │
│                         ▼                                   │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  FreeMoCap 核心管线                                    │  │
│  │  M2 标定 → M3 2D跟踪 → M4 三角化 → M5 后处理 → M6 导出 │  │
│  │  + 2D 输出通道分支（M3 后可直接导出，跳过 M4/M5）       │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## MCP 工具清单

| 工具名 | 描述 | 输入 | 输出 |
|---|---|---|---|
| `ping` | 测试 MCP 连接 | 无 | `{status: "ok"}` |
| `upload_video` | 上传视频到存储池 | `user_id, session_id, file` | `{key, url}` |
| `process_2d` | 2D 姿态提取 | `session_id, detector, model_size, ...` | `{task_id}` |
| `process_3d` | 3D 骨架重建 | `session_id, calibration_key, ...` | `{task_id}` |
| `calibrate` | 相机标定 | `video_urls` | `{task_id}` |
| `get_task_status` | 查询任务状态 | `task_id` | `{status, result, progress}` |
| `get_download_url` | 获取下载链接（预签名 URL） | `key` | `{url}` |

## 技术栈

| 组件 | 技术选型 | 职责 |
|---|---|---|
| MCP Server | FastAPI + `fastapi-mcp` | 暴露 MCP 工具 |
| 任务队列 | Redis + Celery | 异步任务处理 |
| 存储池 | MinIO / S3 / OSS | 文件存储 |
| GPU Worker | Celery Worker + CUDA | 姿态估计（MediaPipe / RTMPose） |
| CPU Worker | Celery Worker | 后处理、导出 |
| 反向代理 | Nginx / Caddy | SSL、路由 |
| 容器编排 | Docker Compose / K8s | 部署 |
| 监控 | Prometheus + Grafana | 指标 |
| 日志 | Loki / ELK | 日志聚合 |

## 分阶段实施计划

| 阶段 | 名称 | 目标 |
|---|---|---|
| P0 | 准备 | 环境搭建、依赖确认 |
| P1 | 后端独立 | 剥离前端，FastAPI 独立运行 |
| P2 | MCP 最小验证 | `fastapi-mcp` 包装验证，MCP Client 可调用 ping |
| P3 | 2D 管道最小实现 | M3 后分支输出 `image_data.npy` |
| P4 | 存储池集成 | S3/MinIO 读写 |
| P5 | 任务队列 | Redis + Celery 异步任务 + 进度查询 |
| P6 | 完整 3D 管线 | M2~M6 云端跑通 |
| P7 | 2D 管道增强 | 骨架视频、静态图、多格式导出 |
| P8 | 多租户隔离 | `user_id`/`session_id` 隔离 + 配额 |
| P9 | GPU 调度 | 独立 Worker + 队列控制 |
| P10 | 生产化部署 | Docker + K8s |
| P11 | 测试与验收 | 端到端测试 |
| P12 | 文档与交付 | 运维手册、API 文档 |

关键路径：`P1 → P2 → P3 → P4 → P5 → P6 → P10 → P11 → P12`（P7/P8/P9 可并行）。

## 开发环境

> 以下为上游 FreeMoCap 的开发方式，本分支在此基础上进行 MCP 化改造。

### Python 后端

1. 安装 [`uv`](https://github.com/astral-sh/uv?tab=readme-ov-file#installation)
2. 克隆本仓库
   ```bash
   git clone git@github.com:AaronSwartz0217/freemocap_MCP.git
   cd freemocap_MCP
   ```
3. 创建虚拟环境并安装依赖
   ```bash
   uv venv
   uv sync          # 自动安装带 GPU 加速的 skellytracker（Windows/Linux）
   # 无 GPU 时：uv sync --no-default-groups --group cpu
   ```
4. 启动 Python 服务
   ```bash
   uv run python freemocap/__main__.py
   # 服务启动于 http://localhost:8005
   ```

### React GUI（上游保留，本分支不再维护）

```bash
cd freemocap-ui
npm install
npm run dev
```

## 存储结构

```text
{bucket}/
├── uploads/{user_id}/{session_id}/
│   ├── cam0.mp4, cam1.mp4, ...
│   └── calibration.toml
├── outputs/{user_id}/{session_id}/
│   ├── 2d_pose/
│   │   ├── image_data.npy / .csv / .json
│   │   └── cam*_2d_pose.mp4
│   └── 3d_skeleton/
│       └── total_3d_skeleton.npy / .csv / .json
└── temp/{session_id}/   # 处理中的临时文件，24h 自动清理
```

## 错误处理原则

遵循 FreeMoCap 的"响亮地失败"（Fail Loudly）原则：
- 内部模块让异常冒泡
- 错误信息带上下文
- 在系统边界统一处理
- 快速失败，不带病运行

## 相关链接

- FreeMoCap 官方文档：https://docs.freemocap.org
- FreeMoCap 上游仓库：https://github.com/freemocap/freemocap
- MCP 官方文档：https://modelcontextprotocol.io
- `fastapi-mcp`：https://github.com/tadata-org/fastapi_mcp

## 贡献

请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 维护者

上游 FreeMoCap：[Jon Matthis](https://github.com/jonmatthis)、[Endurance Idehen](https://github.com/endurance)

## License

本项目遵循 **GNU Affero General Public License v3.0**。详见 [LICENSE](LICENSE)。

若 AGPL 不满足你的需求，可与上游团队协商其他授权条款。
