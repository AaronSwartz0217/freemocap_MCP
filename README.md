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
| 形态 | Electron 桌面应用 | 独立 MCP Server（FastAPI 服务） |
| 前端 | React + Electron | **去除**，仅保留后端 |
| 调用方式 | GUI 点击 | MCP 工具调用（JSON-RPC over HTTP/SSE） |
| 输出 | 必须跑完整 3D 管线 | 新增 **2D 独立通道**，可只输出 2D 姿态 |
| 存储 | 本地文件系统 | 存储抽象层（Local + S3/MinIO） |
| 任务 | 同步阻塞 | 异步任务队列（进程内线程池 / Celery + Redis） |

### 范围

**包含**
- FreeMoCap Python 后端剥离与独立部署
- MCP Server 包装（`fastapi-mcp`）
- 2D 姿态输出通道（单图检测，输出骨架图 + 关键点 JSON）
- 存储池集成（Local + S3/MinIO 双后端）
- 异步任务队列（进程内降级 + Celery/Redis 支持，含进度上报）
- 3D 动捕管线封装（异步任务提交 + 进度查询）

**不包含**
- FreeMoCap 前端（Electron/React）的维护
- 新的姿态估计算法开发
- 新的 3D 重建算法开发
- AI Agent 平台本身的开发
- 多租户隔离、GPU 调度、生产化容器编排

## 当前状态

> **最新更新**：2026-09-21 — P6 完整 3D 管线封装完成，`POST /mocap-3d/run` 可提交 3D 动捕任务（video_dir + calibration_path），通过 `mocap.run_3d` 任务类型异步执行，5 阶段进度上报（加载视频→2D检测→同步→3D三角化→导出）；无 skellytracker 环境自动降级为模拟管线验证流程。
>
> **可用性**：✅ MCP 协议层 + 2D 单图姿势检测 + 存储池（local/S3）+ 任务队列（进程内降级）+ 3D 动捕任务提交/进度查询可正常使用；真实 3D 管线需云端环境（skellytracker + skellycam + 多机位视频）验证。

## 更新日志

| 日期 | 阶段 | 更新内容 | 状态 | 可用性 |
|---|---|---|---|---|
| 2026-09-21 | P6 | 完整 3D 管线云端封装：新增 `mocap_3d_service.py` 封装 posthoc mocap 管线，注册 `mocap.run_3d` 任务类型；新增 `mocap_3d_router` 提供 `POST /mocap-3d/run` 端点；5 阶段进度上报（loading_videos→detection_2d→synchronization→triangulation_3d→exporting）；无 skellytracker 时自动降级为模拟管线 | ✅ 已完成 | ✅ 任务提交与进度查询可用，真实管线待云端验证 |
| 2026-09-21 | P5 | 任务队列：新增 `freemocap/services/task_queue.py`，`InProcessTaskQueue`（线程池，开发降级）+ `CeleryTaskQueue`（Redis broker/backend）；`tasks_router` 提供提交/状态轮询/结果获取/取消端点；内置 `demo.echo`、`demo.long_task` 测试任务支持进度上报 | ✅ 已完成 | ✅ 进程内后端验证通过，Celery 后端待 Redis 环境验证 |
| 2026-09-21 | P4 | 存储池集成：新增 `freemocap/services/storage.py` 抽象层（`LocalStorageBackend` + `S3StorageBackend`），`storage_router` 提供上传/下载/URL/删除/存在性检查端点；后端由 `FMC_STORAGE_BACKEND` 环境变量切换，S3 凭证全部走环境变量不硬编码 | ✅ 已完成 | ✅ 本地后端验证通过，S3 后端待 MinIO 环境验证 |
| 2026-09-21 | P3 | 新增 2D 姿势检测路由 `pose_2d_router`：`POST /pose-2d/image` 上传图片返回 OpenPose 风格骨架 PNG（黑底+彩色骨骼+关节圆圈），`POST /pose-2d/json` 返回 33 个 MediaPipe 关键点；使用 MediaPipe Pose 检测 + OpenCV 绘制 | ✅ 已完成 | ✅ 单图 2D 姿势检测可用 |
| 2026-09-21 | P2 | 集成 `fastapi-mcp`，将 FastAPI 路由自动暴露为 MCP 工具；挂载 `/mcp`（Streamable HTTP）和 `/sse`（SSE）传输端点；`initialize` + `tools/list` 握手验证通过 | ✅ 已完成 | ✅ MCP 端点可连通，现有 REST 端点自动成为 MCP 工具 |
| 2026-09-21 | P0~P1 | 仓库 fork 初始化；重写 README（AGPLv3 声明、项目介绍、架构）；确认后端 `__main__.py` 可独立作为 FastAPI 服务运行 | ✅ 已完成 | ✅ 后端可独立启动 |

> P7~P12（2D 增强 / 多租户 / GPU 调度 / 生产化部署 / 测试验收 / 文档交付）已取消，当前 P0~P6 已满足核心目标：动捕能力通过 MCP 协议暴露给 AI Agent 平台调用。

## 总体架构

```text
┌─────────────────────────────────────────────────────────────┐
│                    AI Agent 平台 (MCP Host)                  │
│  ┌─────────────┐  ┌─────────────┐  ┌───────────────────┐   │
│  │ LLM 核心    │  │ 任务规划器  │  │ MCP Client        │   │
│  └─────────────┘  └─────────────┘  └─────────┬─────────┘   │
│                                              │             │
│  ┌───────────────────────────────────────────┼───────────┐ │
│  │              存储池 (Local / S3)           │           │ │
│  │  uploads/...  outputs/...                 │           │ │
│  └───────────────────────────────────────────┼───────────┘ │
└──────────────────────────────────────────────┼─────────────┘
                                               │ MCP (JSON-RPC)
                                               │ HTTP/SSE
                                               ▼
┌─────────────────────────────────────────────────────────────┐
│              FreeMoCap MCP Server (FastAPI)                   │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  MCP 工具层 (fastapi-mcp)                              │  │
│  │  pose-2d / mocap-3d / storage / tasks                 │  │
│  └──────────────────────┬────────────────────────────────┘  │
│                         ▼                                   │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  任务队列（进程内线程池 / Celery + Redis）              │  │
│  │  支持进度上报、状态查询、结果获取、取消                 │  │
│  └──────────────────────┬────────────────────────────────┘  │
│                         ▼                                   │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  FreeMoCap 核心能力                                    │  │
│  │  2D: MediaPipe Pose → 骨架图 + 关键点 JSON            │  │
│  │  3D: posthoc pipeline → 3D 骨架（需 skellytracker）   │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## MCP 工具清单

通过 `fastapi-mcp`，所有 FastAPI 路由自动暴露为 MCP 工具。MCP Client 连接后可通过 `tools/list` 获取完整工具列表。

> **连接地址**：
> - Streamable HTTP: `http://<host>:8000/mcp`
> - SSE: `http://<host>:8000/sse`

### 2D 姿势检测

| 端点 | MCP 工具名 | 输入 | 输出 |
|---|---|---|---|
| `POST /pose-2d/image` | `post_pose_2d_image` | `file` (图片) | OpenPose 风格骨架 PNG |
| `POST /pose-2d/json` | `post_pose_2d_json` | `file` (图片) | 33 个 MediaPipe 关键点 JSON |

### 3D 动捕

| 端点 | MCP 工具名 | 输入 | 输出 |
|---|---|---|---|
| `POST /mocap-3d/run` | `post_mocap_3d_run` | `video_dir`, `calibration_path?`, `tracker?` | `task_id`（异步任务） |

### 存储池

| 端点 | MCP 工具名 | 输入 | 输出 |
|---|---|---|---|
| `POST /storage/upload` | `post_storage_upload` | `file`, `prefix?` | `{key, download_url, size_bytes}` |
| `GET /storage/download/{key}` | `get_storage_download_key` | `key` | 文件二进制 |
| `GET /storage/url/{key}` | `get_storage_url_key` | `key` | `{url}`（S3 预签名） |
| `DELETE /storage/{key}` | `delete_storage_key` | `key` | `{deleted: true}` |
| `GET /storage/info/{key}` | `get_storage_info_key` | `key` | `{exists: true/false}` |

### 异步任务

| 端点 | MCP 工具名 | 输入 | 输出 |
|---|---|---|---|
| `GET /tasks/types` | `get_tasks_types` | 无 | 已注册任务类型列表 |
| `POST /tasks/submit` | `post_tasks_submit` | `task_type`, `payload` | `task_id` |
| `GET /tasks/{task_id}` | `get_tasks_task_id` | `task_id` | `{state, progress, message, result}` |
| `GET /tasks/{task_id}/result` | `get_tasks_task_id_result` | `task_id` | 任务结果数据 |
| `DELETE /tasks/{task_id}` | `delete_tasks_task_id` | `task_id` | `{cancelled: true}` |

### 已注册任务类型

| 任务类型 | 说明 |
|---|---|
| `demo.echo` | 回显 payload（测试用） |
| `demo.long_task` | 模拟长任务，定期上报进度（测试用） |
| `mocap.run_3d` | 完整 3D 动捕管线（video_dir → 3D 骨架） |

## 技术栈

| 组件 | 技术选型 | 职责 |
|---|---|---|
| MCP Server | FastAPI + `fastapi-mcp` | 暴露 MCP 工具 |
| 任务队列 | 进程内线程池 / Celery + Redis | 异步任务处理 + 进度上报 |
| 存储池 | 本地文件系统 / S3/MinIO | 文件存储 |
| 2D 姿势检测 | MediaPipe Pose + OpenCV | 关键点检测 + 骨架绘制 |
| 3D 动捕 | FreeMoCap posthoc pipeline | 多机位视频 → 3D 骨架 |

## 已完成阶段

| 阶段 | 名称 | 状态 |
|---|---|---|
| P0~P1 | 仓库初始化 + 后端独立 | ✅ |
| P2 | MCP 集成（`/mcp`, `/sse`） | ✅ |
| P3 | 2D 管道（单图姿势检测） | ✅ |
| P4 | 存储池（Local + S3/MinIO） | ✅ |
| P5 | 任务队列（进程内 + Celery 降级） | ✅ |
| P6 | 3D 管线封装（异步任务 + 进度） | ✅ |

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
   # 服务启动于 http://localhost:8000
   ```

> 本分支已去除上游的 Electron/React 前端，仅保留 Python 后端。前端能力通过 MCP 协议由 AI Agent 平台提供。

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
