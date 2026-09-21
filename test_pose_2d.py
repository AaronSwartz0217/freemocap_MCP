"""Local test for the 2D pose endpoints.

Loads pose_2d_router.py directly (bypassing freemocap/__init__.py which needs
skellylogs), mounts it on a minimal FastAPI app, then:
  1. POST /pose-2d/image -> saves the returned skeleton PNG
  2. POST /pose-2d/json  -> prints the landmark JSON
"""
import importlib.util
import io
import sys
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI

REPO_ROOT = Path(r"d:\本地动捕环境\freemocap_MCP")
TEST_IMAGE = Path(
    r"D:\本地动捕环境\FreeMoCap\resources\app.asar.unpacked\freemocap_server\_internal\matplotlib\mpl-data\sample_data\grace_hopper.jpg"
)

spec = importlib.util.spec_from_file_location(
    "pose_2d_router",
    REPO_ROOT / "freemocap" / "api" / "http" / "mocap" / "pose_2d_router.py",
)
pose_2d_mod = importlib.util.module_from_spec(spec)
sys.modules["pose_2d_router"] = pose_2d_mod
spec.loader.exec_module(pose_2d_mod)
pose_2d_router = pose_2d_mod.pose_2d_router

app = FastAPI()
app.include_router(pose_2d_router)

import asyncio

async def main():
    config = uvicorn.Config(app=app, host="127.0.0.1", port=8098, log_level="error")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    for _ in range(30):
        if server.started:
            break
        await asyncio.sleep(0.1)
    await asyncio.sleep(0.3)

    try:
        image_bytes = TEST_IMAGE.read_bytes()
        async with httpx.AsyncClient(base_url="http://127.0.0.1:8098", timeout=30.0) as client:
            # 1. /pose-2d/image
            r = await client.post("/pose-2d/image", files={"file": ("test.jpg", image_bytes, "image/jpeg")})
            print(f"[image] POST /pose-2d/image -> {r.status_code} (content-type={r.headers.get('content-type')})")
            if r.status_code == 200:
                out = REPO_ROOT / "test_pose_2d_output.png"
                out.write_bytes(r.content)
                print(f"         skeleton saved -> {out}  ({len(r.content)} bytes)")
            else:
                print(f"         body: {r.text[:300]}")

            # 2. /pose-2d/json
            r = await client.post("/pose-2d/json", files={"file": ("test.jpg", image_bytes, "image/jpeg")})
            print(f"\n[json]  POST /pose-2d/json  -> {r.status_code}")
            if r.status_code == 200:
                data = r.json()
                print(f"         detector={data['detector']}, landmark_count={data['landmark_count']}")
                print(f"         first 3 landmarks:")
                for lm in data["landmarks"][:3]:
                    print(f"           idx={lm['index']:2d}  x={lm['x']:.4f}  y={lm['y']:.4f}  vis={lm['visibility']:.3f}")
                print("\n✅ 2D pose endpoints working")
            else:
                print(f"         body: {r.text[:300]}")
    finally:
        server.should_exit = True
        await server_task

asyncio.run(main())
