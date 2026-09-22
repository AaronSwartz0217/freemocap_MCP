# FreeMoCap MCP 接入指南（给 AI IDE / MCP Client 接入方）

> 本文档面向希望通过 MCP 协议调用 FreeMoCap 动捕能力的 AI IDE / Agent 平台开发者。

---

## 1. 项目简介

**FreeMoCap MCP** 是一个将 FreeMoCap（开源无标记动作捕捉系统）后端封装为 MCP 服务的项目。通过 `fastapi-mcp`，所有 FastAPI 路由自动暴露为 MCP 工具，AI Agent 可直接调用 2D 姿态检测、3D 动捕、存储池、任务队列等能力。

- **仓库**：https://github.com/AaronSwartz0217/freemocap_MCP
- **协议**：MCP (Model Context Protocol)，Streamable HTTP 或 SSE 传输
- **许可证**：AGPLv3

---

## 2. 核心能力

| 能力 | 说明 | 输入 | 输出 |
|---|---|---|---|
| **2D COCO 骨架图** ⭐推荐 | MCP 友好，base64 输入/输出 | base64 图片 | COCO 17 关键点骨架图(base64) + 关键点 JSON + COCO 标注 |
| **2D OpenPose 骨架图** | 图片上传 | multipart 文件 | OpenPose 风格骨架 PNG |
| **2D 关键点 JSON** | 图片上传 | multipart 文件 | 33 个 MediaPipe 关键点 |
| **存储池** | local/S3 双后端 | 文件 | 上传/下载/URL/删除 |
| **任务队列** | 进程内/Celery 双后端 | 任务参数 | 提交/状态/结果/取消 |
| **3D 动捕** | 多机位视频 3D 重建 | 视频目录 | 3D 骨架数据(.npy/.glb/.csv/.json) |

---

## 3. 启动服务

### 方式 A — 最小启动（快速验证 MCP，推荐首次接入）

无需 skellycam/skellytracker 等重型依赖，仅需 fastapi + mediapipe：

```bash
git clone git@github.com:AaronSwartz0217/freemocap_MCP.git
cd freemocap_MCP
pip install fastapi fastapi-mcp uvicorn mediapipe==0.10.14 opencv-python-headless numpy python-multipart boto3 celery redis
python run_minimal_mcp.py
```

启动后日志应包含：`MCP server mounted at /mcp (HTTP streamable) and /sse (SSE)`

### 方式 B — 完整启动（生产环境，包含上游 3D 管线）

```bash
git clone git@github.com:AaronSwartz0217/freemocap_MCP.git
cd freemocap_MCP
uv sync              # 安装全部依赖（含 skellycam/skellyforge/skellytracker）
uv run python -m freemocap
```

> ⚠️ **不要连接桌面安装包**：FreeMoCap 桌面安装包（alpha.23 及更早）不含 MCP 代码，`/mcp` 返回 404。必须用本仓库代码启动服务。

---

## 4. MCP Client 连接配置

| 配置项 | 值 |
|---|---|
| 传输方式 | **Streamable HTTP**（首选）或 SSE |
| URL | `http://<host>:8000/mcp` |
| SSE URL | `http://<host>:8000/sse` |
| 协议版本 | `2025-06-18` |

### AI IDE 配置示例（JSON）

**Trae / Cursor / Claude Desktop 等支持 URL 型 MCP 的 IDE：**
```json
{
  "mcpServers": {
    "freemocap": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

---

## 5. 连通验证

服务启动后，`tools/list` 应返回 **14 个工具**。

### 命令行验证（curl）

MCP 协议要求先 `initialize` 获取 `Mcp-Session-Id`，再携带该头调用后续方法。

```bash
# 步骤 1：initialize 握手（响应头含 Mcp-Session-Id）
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'

# 步骤 2：发送 initialized 通知（需带上一步返回的 Mcp-Session-Id）
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: <上一步返回的session id>" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'

# 步骤 3：列出工具
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: <session id>" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
```

成功后应看到 14 个工具，核心工具包括：

| 工具名 | 功能 |
|---|---|
| `pose_2d_coco_pose_2d_pose_2d_coco_post` | COCO 骨架图（MCP 推荐，base64） |
| `pose_2d_image_pose_2d_image_post` | OpenPose 骨架图 |
| `pose_2d_json_pose_2d_json_post` | 33 关键点 JSON |
| `upload_file_storage_upload_post` | 文件上传到存储池 |
| `download_file_storage_download__key__get` | 从存储池下载文件 |
| `submit_task_tasks_submit_post` | 提交异步任务 |
| `get_task_status_tasks__task_id__get` | 查询任务状态 |
| `run_3d_mocap_mocap_3d_run_post` | 提交 3D 动捕任务 |

---

## 6. 调用示例：生成 COCO 骨架图

这是最常用的 MCP 工具，接受 base64 图片，返回 COCO 17 关键点骨架图。

### MCP tools/call 请求

```bash
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: <session id>" \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "pose_2d_coco_pose_2d_pose_2d_coco_post",
      "arguments": {
        "image_base64": "<图片的base64编码，可带data:image/png;base64,前缀>"
      }
    }
  }'
```

### 返回值结构

```json
{
  "skeleton_image_base64": "iVBORw0KGgoAAAANSUhEUg...",  // COCO 骨架 PNG 的 base64
  "keypoints": [
    {"name": "nose",       "x": 452.3, "y": 187.5, "visibility": 0.99},
    {"name": "left_eye",   "x": 468.1, "y": 175.2, "visibility": 0.98},
    {"name": "right_eye",  "x": 437.8, "y": 176.0, "visibility": 0.97},
    {"name": "left_ear",   "x": 482.5, "y": 183.1, "visibility": 0.95},
    {"name": "right_ear",  "x": 422.3, "y": 184.7, "visibility": 0.94},
    {"name": "left_shoulder",  "x": 510.2, "y": 312.8, "visibility": 0.99},
    {"name": "right_shoulder", "x": 389.5, "y": 315.1, "visibility": 0.99},
    {"name": "left_elbow",     "x": 575.3, "y": 458.2, "visibility": 0.97},
    {"name": "right_elbow",    "x": 322.8, "y": 461.5, "visibility": 0.96},
    {"name": "left_wrist",     "x": 612.7, "y": 598.3, "visibility": 0.92},
    {"name": "right_wrist",    "x": 285.1, "y": 602.8, "visibility": 0.91},
    {"name": "left_hip",       "x": 482.1, "y": 625.7, "visibility": 0.98},
    {"name": "right_hip",      "x": 418.6, "y": 627.3, "visibility": 0.98},
    {"name": "left_knee",      "x": 502.8, "y": 812.4, "visibility": 0.96},
    {"name": "right_knee",     "x": 398.2, "y": 815.1, "visibility": 0.95},
    {"name": "left_ankle",     "x": 518.3, "y": 995.2, "visibility": 0.93},
    {"name": "right_ankle",    "x": 382.7, "y": 998.6, "visibility": 0.92}
  ],
  "coco_annotations": {
    "keypoints": [452.3, 187.5, 2, 468.1, 175.2, 2, ...],  // 17 × 3 = 51 个值
    "num_keypoints": 17,
    "category_id": 1
  }
}
```

### COCO 17 关键点说明

| 索引 | 名称 | 说明 |
|---|---|---|
| 0 | nose | 鼻子 |
| 1 | left_eye | 左眼 |
| 2 | right_eye | 右眼 |
| 3 | left_ear | 左耳 |
| 4 | right_ear | 右耳 |
| 5 | left_shoulder | 左肩 |
| 6 | right_shoulder | 右肩 |
| 7 | left_elbow | 左肘 |
| 8 | right_elbow | 右肘 |
| 9 | left_wrist | 左腕 |
| 10 | right_wrist | 右腕 |
| 11 | left_hip | 左髋 |
| 12 | right_hip | 右髋 |
| 13 | left_knee | 左膝 |
| 14 | right_knee | 右膝 |
| 15 | left_ankle | 左踝 |
| 16 | right_ankle | 右踝 |

`visibility` 含义：`0` = 未标注，`1` = 标注但不可见，`2` = 标注且可见。

---

## 7. Python 调用示例（mcp 库）

```python
import base64
import json
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def call_coco(image_path: str):
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    async with streamablehttp_client("http://localhost:8000/mcp") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 列出工具
            tools = await session.list_tools()
            print([t.name for t in tools.tools])

            # 调用 COCO 骨架图工具
            result = await session.call_tool(
                "pose_2d_coco_pose_2d_pose_2d_coco_post",
                {"image_base64": img_b64}
            )
            data = json.loads(result.content[0].text)
            return data["keypoints"], data["skeleton_image_base64"]
```

---

## 8. 常见问题

### Q1: 连接 `/mcp` 返回 404
**A**: 你连接的是 FreeMoCap 桌面安装包，不含 MCP 代码。必须用本仓库代码启动服务（见第 3 节）。

### Q2: 不同启动方式暴露的工具数不同

| 启动方式 | 注册的 router | `tools/list` 工具数 |
|---|---|---|
| **最小启动** (`run_minimal_mcp.py`) | pose_2d, storage, tasks, mocap_3d（共 4 个） | **14 个** |
| **完整启动** (`python -m freemocap`) | 全部上游 + 新增 router（共 15 个） | **48+ 个** |

最小启动注册了所有不依赖 skellycam/skellytracker 的新增路由（pose_2d、storage、tasks、mocap_3d），并非只注册 1 个。如需相机控制、录制、标定、Blender 等上游工具，用完整启动方式。

### Q3: 调用 `tools/call` 返回 400 "Missing session ID"
**A**: MCP 协议要求 `initialize` 后携带 `Mcp-Session-Id` 头。确保先调用 `initialize`，并将响应头中的 `Mcp-Session-Id` 用于后续请求。

### Q4: MediaPipe 报错 `module 'mediapipe' has no attribute 'solutions'`
**A**: mediapipe 0.10.33 缺少 solutions 子模块，降级到 0.10.14：`pip install mediapipe==0.10.14`

### Q5: Windows 下中文路径报错
**A**: 将系统代码页设为 UTF-8：`chcp 65001`，或确保项目路径不含中文。

---

## 9. 相关链接

- 项目仓库：https://github.com/AaronSwartz0217/freemocap_MCP
- MCP 官方文档：https://modelcontextprotocol.io
- fastapi-mcp：https://github.com/tadata-org/fastapi_mcp
- FreeMoCap 上游：https://github.com/freemocap/freemocap
