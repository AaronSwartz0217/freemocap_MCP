"""Minimal MCP server launcher — only loads our added routes + MCP.

Bypasses the full FreeMoCap dependency chain (skellycam, skellyforge, etc.)
so we can verify the MCP endpoints work with just fastapi + fastapi-mcp + mediapipe.
"""
import sys
import logging

# Mock missing skelly packages before importing freemocap
sys.path.insert(0, r"d:\本地动捕环境\freemocap_MCP\_mock_deps")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, r"d:\本地动捕环境\freemocap_MCP")

from freemocap.api.http.mocap.pose_2d_router import pose_2d_router
from freemocap.api.http.storage.storage_router import storage_router
from freemocap.api.http.tasks.tasks_router import tasks_router
from freemocap.api.http.mocap.mocap_3d_router import mocap_3d_router
from freemocap.api.mcp.server import register_mcp_server

app = FastAPI(title="FreeMoCap MCP (minimal)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(pose_2d_router, prefix="/pose-2d")
app.include_router(storage_router, prefix="/storage")
app.include_router(tasks_router, prefix="/tasks")
app.include_router(mocap_3d_router, prefix="/mocap-3d")

# Register MCP AFTER routes
register_mcp_server(app)

@app.get("/")
async def root():
    return {"status": "ok", "mcp": "/mcp", "docs": "/docs"}

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting minimal FreeMoCap MCP server on port 8000")
    logger.info("MCP streamable HTTP: http://localhost:8000/mcp")
    logger.info("MCP SSE:             http://localhost:8000/sse")
    logger.info("Swagger docs:        http://localhost:8000/docs")
    uvicorn.run(app, host="0.0.0.0", port=8000)
