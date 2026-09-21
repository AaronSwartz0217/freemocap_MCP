"""MCP (Model Context Protocol) server for FreeMoCap.

Exposes the FreeMoCap FastAPI REST endpoints as MCP tools so that AI Agent
platforms can invoke motion-capture capabilities (health check, video import,
2D/3D processing, calibration, etc.) through the standard MCP protocol.

Uses `fastapi-mcp`, which automatically converts registered FastAPI routes into
MCP tools. The MCP transport endpoints are mounted at:
  * ``/mcp``  — Streamable HTTP transport (preferred for HTTP clients)
  * ``/sse``  — Server-Sent Events transport
"""

import logging

from fastapi import FastAPI

logger = logging.getLogger(__name__)


def register_mcp_server(app: FastAPI) -> None:
    """Create and mount the MCP server on the given FastAPI application.

    Must be called *after* all application routes have been registered so that
    ``fastapi-mcp`` can discover them and expose them as MCP tools.
    """
    try:
        from fastapi_mcp import FastApiMCP
    except ImportError:
        logger.warning(
            "fastapi-mcp is not installed — MCP server will not be available. "
            "Install it with: pip install fastapi-mcp"
        )
        return

    mcp = FastApiMCP(
        fastapi=app,
        name="FreeMoCap MCP",
        description=(
            "FreeMoCap markerless motion capture exposed as MCP tools. "
            "Provides health check, video import, 2D pose extraction, "
            "3D skeleton reconstruction, camera calibration, and more."
        ),
    )

    # Streamable HTTP transport (MCP 2025-06-18 spec) — mounted at /mcp
    mcp.mount_http(mount_path="/mcp")
    # SSE transport — mounted at /sse
    mcp.mount_sse(mount_path="/sse")

    logger.info("MCP server mounted at /mcp (HTTP streamable) and /sse (SSE)")
