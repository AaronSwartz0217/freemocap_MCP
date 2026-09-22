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

> **最新更新**：2026-09-22 — 修复三处部署问题：`run_minimal_mcp.py` 硬编码绝对路径改为 `__file__` 相对路径（跨机器可用）；`pyproject.toml` 的 `[tool.uv] override-dependencies` 将 mediapipe 从 `0.10.33` 锁定为 `0.10.14`（0.10.33 缺少 `solutions` 子模块，会导致 `/pose-2d/*` 三个端点在完整启动下全部 503）；修正 `MCP接入指南.md` Q2 中最小启动 router 数量描述（实际注册 4 个 router，暴露 14 个工具）。
>
> **可用性**：✅ MCP 协议层 + 2D 单图姿势检测（OpenPose 风格 + COCO 格式）+ 存储池（local/S3）+ 任务队列（进程内降级）+ 3D 动捕任务提交/进度查询可正常使用；真实 3D 管线需云端环境（skellytracker + skellycam + 多机位视频）验证。

## 更新日志

| 日期 | 阶段 | 更新内容 | 状态 | 可用性 |
|---|---|---|---|---|
| 2026-09-22 | 优化 | ①`blender_router.py` 新增 Blender MCP 引导机制：`ExportToBlenderResponse` 增加 `blender_mcp_guide` 字段，通过 `BLENDER_MCP_URL`/`BLENDER_MCP_COMMAND` 环境变量检测 Blender MCP 连接信息，引导 AI Agent 在生成 `.blend` 后连接 Blender MCP 做后处理；②README 新增"3D 模式支持说明"矩阵（单目 3D / 多机位 3D / RTMPose 2D-only）；③`blender_router.py` 四个端点 docstring 添加 MCP 使用提示（限制条件、前置检查、调用顺序） | ✅ 已完成 | ✅ |
| 2026-09-22 | 优化 | ①`_mediapipe_to_coco_keypoints` 预建 COCO→MediaPipe 反向映射列表（`_COCO_TO_MEDIAPIPE`），将每帧转换从 O(n²) 嵌套循环降为 O(1) 索引；②`MCP接入指南.md` Q4 更新为"已通过 pyproject.toml override 修复，uv sync 自动安装 0.10.14"，与实际配置一致 | ✅ 已完成 | ✅ |
| 2026-09-22 | 修复 | 修复三处部署问题：①`run_minimal_mcp.py` 硬编码绝对路径改为 `os.path.dirname(os.path.abspath(__file__))` 相对路径；②`pyproject.toml` `[tool.uv] override-dependencies` 将 `mediapipe==0.10.33` 改为 `0.10.14`（0.10.33 缺 `solutions` 子模块，完整启动下 `/pose-2d/*` 三端点全部 503）；③`MCP接入指南.md` Q2 修正最小启动 router 数量（实际注册 4 个，暴露 14 个工具） | ✅ 已完成 | ✅ 完整启动 + 最小启动 2D 能力均可用 |
| 2026-09-22 | P3+ | 新增 COCO 格式骨架图端点 `POST /pose-2d/coco`：MCP 友好（base64 输入/输出），MediaPipe 33 关键点 → COCO 17 关键点映射，返回 COCO 风格骨架 PNG + 关键点 JSON + COCO 兼容标注（keypoints 扁平数组 + num_keypoints）；修复 `_detect_pose` 返回类型问题（MediaPipe `RepeatedCompositeContainer` → `list`）以通过 beartype 检查；MCP 协议端到端调用验证通过 | ✅ 已完成 | ✅ MCP 调用生成 COCO 骨架图验证通过 |
| 2026-09-21 | P6 | 完整 3D 管线云端封装：新增 `mocap_3d_service.py` 封装 posthoc mocap 管线，注册 `mocap.run_3d` 任务类型；新增 `mocap_3d_router` 提供 `POST /mocap-3d/run` 端点；5 阶段进度上报（loading_videos→detection_2d→synchronization→triangulation_3d→exporting）；无 skellytracker 时自动降级为模拟管线 | ✅ 已完成 | ✅ 任务提交与进度查询可用，真实管线待云端验证 |
| 2026-09-21 | P5 | 任务队列：新增 `freemocap/services/task_queue.py`，`InProcessTaskQueue`（线程池，开发降级）+ `CeleryTaskQueue`（Redis broker/backend）；`tasks_router` 提供提交/状态轮询/结果获取/取消端点；内置 `demo.echo`、`demo.long_task` 测试任务支持进度上报 | ✅ 已完成 | ✅ 进程内后端验证通过，Celery 后端待 Redis 环境验证 |
| 2026-09-21 | P4 | 存储池集成：新增 `freemocap/services/storage.py` 抽象层（`LocalStorageBackend` + `S3StorageBackend`），`storage_router` 提供上传/下载/URL/删除/存在性检查端点；后端由 `FMC_STORAGE_BACKEND` 环境变量切换，S3 凭证全部走环境变量不硬编码 | ✅ 已完成 | ✅ 本地后端验证通过，S3 后端待 MinIO 环境验证 |
| 2026-09-21 | P3 | 新增 2D 姿势检测路由 `pose_2d_router`：`POST /pose-2d/image` 上传图片返回 OpenPose 风格骨架 PNG（黑底+彩色骨骼+关节圆圈），`POST /pose-2d/json` 返回 33 个 MediaPipe 关键点；使用 MediaPipe Pose 检测 + OpenCV 绘制 | ✅ 已完成 | ✅ 单图 2D 姿势检测可用 |
| 2026-09-21 | P2 | 集成 `fastapi-mcp`，将 FastAPI 路由自动暴露为 MCP 工具；挂载 `/mcp`（Streamable HTTP）和 `/sse`（SSE）传输端点；`initialize` + `tools/list` 握手验证通过 | ✅ 已完成 | ✅ MCP 端点可连通，现有 REST 端点自动成为 MCP 工具 |
| 2026-09-21 | P0~P1 | 仓库 fork 初始化；重写 README（AGPLv3 声明、项目介绍、架构）；确认后端 `__main__.py` 可独立作为 FastAPI 服务运行 | ✅ 已完成 | ✅ 后端可独立启动 |

> P7~P12（2D 增强 / 多租户 / GPU 调度 / 生产化部署 / 测试验收 / 文档交付）已取消，当前 P0~P6 已满足核心目标：动捕能力通过 MCP 协议暴露给 AI Agent 平台调用。

## 详细更新过程

### 2026-09-22 — 3D 模式说明 + Blender MCP 提示与引导

**需求**：标注 3D 单视频/多机位模式支持内容；Blender 导出端点添加 MCP 使用提示；生成 `.blend` 后引导 AI Agent 连接 Blender MCP 做后处理。

**实现**：

1. **README 新增"3D 模式支持说明"矩阵**
   - 单目视频 3D（`tracker=mediapipe`，无需标定，MediaPipe 单目深度）
   - 多机位 3D（`tracker=mediapipe`，Charuco 标定，多视角三角测量）
   - 多机位 2D-only（`tracker=rtmpose`，Z 轴=0，有警告）

2. **`blender_router.py` 端点 docstring 添加 MCP 提示**
   - `/blender/detect`：导出前先调用检测 Blender
   - `/blender/export`：只支持 `mediapipe`（RTMPose 会 ValueError）；需要 `output_data/mediapipe_body_3d_xyz.npy`；后台模式运行
   - `/blender/addon/install`：可选，`/export` 不需要装 addon
   - `/blender/open`：需要图形界面，无头服务器用 `/export`

3. **Blender MCP 引导机制**
   - 新增 `BlenderMCPGuide` 模型：`available`、`transport`（stdio/sse/http）、`command`/`url`、`capabilities`、`next_step_hint`
   - 新增 `_detect_blender_mcp()` 函数：检测 `BLENDER_MCP_URL` 或 `BLENDER_MCP_COMMAND` 环境变量
   - `/blender/export` 返回 `blender_mcp_guide` 字段，引导 AI Agent 连接 Blender MCP 做材质/渲染/FBX 导出

### 2026-09-22 — COCO 格式骨架图端点（MCP 友好）

**需求**：通过 MCP 协议调用生成 COCO 格式（17 关键点）骨架图。

**实现步骤**：

1. **COCO 关键点映射**
   - 定义 COCO 17 关键点名称（nose, eyes, ears, shoulders, elbows, wrists, hips, knees, ankles）
   - 建立 MediaPipe 33 关键点 → COCO 17 关键点的索引映射表
   - 定义 COCO 标准骨架连接（19 条骨骼连线）和配色

2. **新增端点 `POST /pose-2d/coco`**
   - 输入：`CocoPoseRequest`（`image_base64` 字符串，支持 `data:image/png;base64,...` 前缀）
   - 处理：base64 解码 → MediaPipe 检测 → 转换为 COCO 关键点 → 绘制 COCO 骨架图
   - 输出：
     - `skeleton_image_base64` — COCO 风格骨架 PNG（黑底 + 彩色骨架）
     - `keypoints` — 17 个 COCO 关键点（name, x, y, visibility）
     - `coco_annotations` — COCO 兼容标注（keypoints 扁平数组 [x,y,v,...] + num_keypoints + category_id）

3. **Bug 修复**
   - **问题**：MediaPipe 返回的 `result.pose_landmarks.landmark` 是 `RepeatedCompositeContainer` 类型，不满足 `_detect_pose` 的 `list[Any] | None` 类型注解，被 `beartype` 拦截返回 500
   - **修复**：`return list(result.pose_landmarks.landmark)`，转换为 Python 原生 list

4. **MCP 协议端到端验证**
   - `initialize` 握手 → 获取 `Mcp-Session-Id`
   - `notifications/initialized` 通知
   - `tools/list` → 返回 14 个工具（新增 `pose_2d_coco_pose_2d_pose_2d_coco_post`）
   - `tools/call` → 传入测试图片 base64，成功返回 17 个 COCO 关键点 + 骨架图
   - 验证结果：所有关键点 visibility > 0.6，骨架图正确绘制

5. **文档与提交**
   - 更新 README：当前状态、更新日志、MCP 工具清单、接入指引
   - commit `0ee6b959` 推送到 GitHub

### 2026-09-22 — 部署问题修复（路径 / mediapipe 版本 / 指南）

**背景**：代码审查中发现三处影响可复现部署的问题。

**修复 1：`run_minimal_mcp.py` 硬编码绝对路径**
- **问题**：脚本中 `sys.path.insert(0, r"d:\本地动捕环境\freemocap_MCP\_mock_deps")` 写死了开发机路径，换机器/换目录直接失败
- **修复**：改用 `_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))`，`_mock_deps` 和项目根目录均基于脚本位置解析
- **commit**：`126df511`

**修复 2：mediapipe 版本冲突（0.10.33 → 0.10.14）**
- **问题**：`pyproject.toml` 的 `[tool.uv] override-dependencies` 锁定 `mediapipe==0.10.33`，而 0.10.33 移除了 `solutions` 子模块。`pose_2d_router.py` 的导入守卫中 `mp.solutions.pose.Pose()` 抛 `AttributeError`，同一 try 块内 `cv2` 被一并置 None，导致完整启动下 `/pose-2d/image`、`/pose-2d/json`、`/pose-2d/coco` 三个端点全部 503
- **修复**：将 override 改为 `mediapipe==0.10.14`（最后一个含 `solutions` 的版本），并添加注释说明原因。此修改落入 `pyproject.toml`，`uv sync` 可复现，无需手动 `uv pip install` 补丁
- **commit**：`cc2d85ee`

**修复 3：`MCP接入指南.md` Q2 描述错误**
- **问题**：指南 Q2 称最小启动脚本"只注册了 `pose_2d_router`"，实际注册了 4 个 router（pose_2d、storage、tasks、mocap_3d）
- **修复**：Q2 改为对照表，标注最小启动暴露 14 个工具、完整启动暴露 48+ 个工具
- **commit**：`cc2d85ee`

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
| `POST /pose-2d/coco` | `post_pose_2d_coco` | `image_base64` (base64 图片) | COCO 17 关键点骨架图（base64）+ 关键点 JSON + COCO 兼容标注 |

### 3D 动捕

| 端点 | MCP 工具名 | 输入 | 输出 |
|---|---|---|---|
| `POST /mocap-3d/run` | `post_mocap_3d_run` | `video_dir`, `calibration_path?`, `tracker?` | `task_id`（异步任务） |

#### 3D 模式支持说明

| 模式 | 输入要求 | tracker | 深度来源 | 输出 |
|---|---|---|---|---|
| **单目视频 3D** | 单个视频文件/目录，无需标定 | `mediapipe` | MediaPipe 单目深度估计（`monocular_mediapipe`） | 3D 骨架（有 Z 轴，但绝对尺度不精确） |
| **多机位 3D** | 多个同步视频 + Charuco 标定文件 `.toml` | `mediapipe`（推荐） | 多视角三角测量（精确 3D） | 精确 3D 骨架 + 重投影误差 |
| **多机位 2D-only** | 多个同步视频 + 标定文件 | `rtmpose` | 无（Z 轴 = 0） | 扁平骨架（仅 2D 投影） |

**注意事项**：
- 单目 3D 模式下 `calibration_path` 可省略，MediaPipe 会从单帧估计深度，但绝对尺度（米）可能不准确，适合相对运动分析
- 多机位 3D 需要 Charuco 板标定（5×3 网格，54mm 方块），`calibration_path` 指向标定 `.toml` 文件
- `rtmpose` 不产生深度数据，仅输出 2D 关键点，Z 轴全为 0，选择时会收到警告
- 所有模式输出 `.npy` 格式 3D 关键点数据，Blender 导出仅支持 `mediapipe` 模式

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
   # 方式 A：完整启动（需要 uv sync 安装全部依赖，含 skelly 全家桶）
   uv run python -m freemocap

   # 方式 B：最小启动（仅需 fastapi + fastapi-mcp + mediapipe + opencv，无需 skelly 依赖）
   python run_minimal_mcp.py
   ```
   服务启动于 `http://localhost:8000`

> 本分支已去除上游的 Electron/React 前端，仅保留 Python 后端。前端能力通过 MCP 协议由 AI Agent 平台提供。

## MCP 接入指引

> **给 AI IDE / MCP Client 接入方**：如果你连接 `/mcp` 得到 `404 Not Found`，请先阅读本节。

### 根因：不要连接桌面安装包

FreeMoCap **桌面安装包**（alpha.23 及更早）是 PyInstaller 打包产物，**不含 MCP 代码**，其 `/mcp` 和 `/sse` 端点不存在。MCP 能力是本分支（`freemocap_MCP`）新增的，必须用**本仓库代码**启动服务。

| 你连的是什么 | `/mcp` 结果 | 说明 |
|---|---|---|
| 桌面安装包（`freemocap_server.exe`） | ❌ 404 | 打包产物不含 MCP |
| 本仓库 `python -m freemocap` | ✅ 200 | 完整后端，需 skelly 依赖 |
| 本仓库 `python run_minimal_mcp.py` | ✅ 200 | 最小后端，仅需 fastapi+mediapipe |

### 步骤 1：启动本仓库的服务

**方式 A — 完整启动（推荐生产环境）**
```bash
git clone git@github.com:AaronSwartz0217/freemocap_MCP.git
cd freemocap_MCP
uv sync              # 安装全部依赖（skellycam/skellyforge/skellytracker 等，从 GitHub 拉取）
uv run python -m freemocap
```

**方式 B — 最小启动（快速验证 MCP，无需 skelly 依赖）**
```bash
git clone git@github.com:AaronSwartz0217/freemocap_MCP.git
cd freemocap_MCP
pip install fastapi fastapi-mcp uvicorn mediapipe opencv-python-headless numpy python-multipart boto3 celery redis
python run_minimal_mcp.py
```

启动后应看到日志：`MCP server mounted at /mcp (HTTP streamable) and /sse (SSE)`

### 步骤 2：MCP Client 连接配置

| 配置项 | 值 |
|---|---|
| 传输方式 | **Streamable HTTP**（首选）或 SSE |
| URL | `http://<host>:8000/mcp`（Streamable HTTP） |
| SSE URL | `http://<host>:8000/sse` |
| 协议版本 | `2025-06-18` |

**Trae IDE / Cursor 等 AI IDE 的 MCP 配置示例**（JSON）：
```json
{
  "mcpServers": {
    "freemocap": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

### 步骤 3：验证连通

服务启动后，`tools/list` 应返回 **14 个工具**：
- `pose_2d_coco_pose_2d_*` — COCO 格式骨架图（MCP 推荐，base64 输入/输出）
- `pose_2d_image_pose_2d_*` — 2D 骨架图（OpenPose 风格，需文件上传）
- `pose_2d_json_pose_2d_*` — 2D 关键点 JSON
- `upload_file_storage_*` / `download_file_storage_*` 等 — 存储池
- `submit_task_tasks_*` / `get_task_status_tasks_*` 等 — 任务队列
- `run_3d_mocap_mocap_3d_*` — 3D 动捕

**命令行验证**（需带 `Mcp-Session-Id` 头，MCP 协议要求）：
```bash
# 1. initialize 握手（响应头含 Mcp-Session-Id）
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'

# 2. 用返回的 session id 发送 initialized 通知 + tools/list
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: <session id>" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'

curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: <session id>" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'

# 3. 调用 COCO 骨架图工具（image_base64 为图片的 base64 编码）
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: <session id>" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"pose_2d_coco_pose_2d_pose_2d_coco_post","arguments":{"image_base64":"<base64图片数据>"}}}'
```

**COCO 工具返回值**：
- `skeleton_image_base64` — COCO 风格骨架 PNG（黑底彩色骨架）的 base64 编码
- `keypoints` — 17 个 COCO 关键点（name, x, y, visibility）
- `coco_annotations` — COCO 兼容标注（keypoints 扁平数组 [x,y,v,...] + num_keypoints + category_id）

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
