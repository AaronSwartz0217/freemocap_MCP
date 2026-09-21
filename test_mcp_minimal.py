"""Standalone test to verify the MCP server mounting works.

Loads freemocap/api/mcp/server.py directly (bypassing freemocap/__init__.py
which pulls in skellylogs) to verify the fastapi-mcp integration in isolation.
"""
import asyncio
import importlib.util
import sys
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI

REPO_ROOT = Path(r"d:\本地动捕环境\freemocap_MCP")

# Load the MCP server module directly without triggering freemocap/__init__.py
spec = importlib.util.spec_from_file_location(
    "freemocap_mcp_server",
    REPO_ROOT / "freemocap" / "api" / "mcp" / "server.py",
)
mcp_server_mod = importlib.util.module_from_spec(spec)
sys.modules["freemocap_mcp_server"] = mcp_server_mod
spec.loader.exec_module(mcp_server_mod)
register_mcp_server = mcp_server_mod.register_mcp_server


def build_app() -> FastAPI:
    app = FastAPI(title="FreeMoCap MCP Test")

    @app.get("/health")
    def health() -> dict:
        return {"alive": True}

    register_mcp_server(app)
    return app


async def main() -> None:
    app = build_app()

    config = uvicorn.Config(app=app, host="127.0.0.1", port=8099, log_level="error")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())

    for _ in range(30):
        if server.started:
            break
        await asyncio.sleep(0.1)
    await asyncio.sleep(0.3)

    try:
        async with httpx.AsyncClient(base_url="http://127.0.0.1:8099") as client:
            # 1. Baseline REST health check
            r = await client.get("/health")
            print(f"[REST] GET /health -> {r.status_code} {r.json()}")
            assert r.status_code == 200

            # 2. MCP initialize handshake
            r = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "test-client", "version": "0.1.0"},
                    },
                },
                headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
            )
            print(f"[MCP] initialize -> {r.status_code}")
            session_id = r.headers.get("Mcp-Session-Id")
            print(f"       Mcp-Session-Id: {session_id}")
            if r.status_code == 200:
                data = r.json()
                print(f"       serverInfo: {data.get('result', {}).get('serverInfo')}")

            # 3. MCP tools/list
            headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
            if session_id:
                headers["Mcp-Session-Id"] = session_id
            r = await client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                headers=headers,
            )
            print(f"[MCP] tools/list -> {r.status_code}")
            if r.status_code == 200:
                tools = r.json().get("result", {}).get("tools", [])
                tool_names = [t["name"] for t in tools]
                print(f"       tools: {tool_names}")
                assert any("health" in name for name in tool_names), "health tool not exposed via MCP"
                print("\n✅ MCP server verification passed — /health exposed as MCP tool")
            else:
                print(f"       body: {r.text[:500]}")
    finally:
        server.should_exit = True
        await server_task


if __name__ == "__main__":
    asyncio.run(main())
