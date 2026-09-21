"""
End-to-end test for the 3D mocap task (in-process backend, simulated pipeline).

Loads modules via importlib (bypassing freemocap/__init__.py which needs skellylogs).
Forces FMC_TASK_QUEUE_BACKEND=inprocess so no Redis is required.
The real pipeline is unavailable in this env, so mocap.run_3d falls back to
the simulated pipeline that still reports real stage progress.
"""
import asyncio
import importlib.util
import os
import sys
import tempfile
from pathlib import Path
from types import ModuleType

import httpx
import uvicorn
from fastapi import FastAPI

REPO_ROOT = Path(r"d:\本地动捕环境\freemocap_MCP")

os.environ["FMC_TASK_QUEUE_BACKEND"] = "inprocess"

# --- Stub package hierarchy ---
freemocap_pkg = ModuleType("freemocap")
freemocap_pkg.__path__ = [str(REPO_ROOT / "freemocap")]
sys.modules["freemocap"] = freemocap_pkg

services_pkg = ModuleType("freemocap.services")
services_pkg.__path__ = [str(REPO_ROOT / "freemocap" / "services")]
sys.modules["freemocap.services"] = services_pkg

api_pkg = ModuleType("freemocap.api")
api_pkg.__path__ = [str(REPO_ROOT / "freemocap" / "api")]
sys.modules["freemocap.api"] = api_pkg

http_pkg = ModuleType("freemocap.api.http")
http_pkg.__path__ = [str(REPO_ROOT / "freemocap" / "api" / "http")]
sys.modules["freemocap.api.http"] = http_pkg

tasks_http_pkg = ModuleType("freemocap.api.http.tasks")
tasks_http_pkg.__path__ = [str(REPO_ROOT / "freemocap" / "api" / "http" / "tasks")]
sys.modules["freemocap.api.http.tasks"] = tasks_http_pkg

mocap_http_pkg = ModuleType("freemocap.api.http.mocap")
mocap_http_pkg.__path__ = [str(REPO_ROOT / "freemocap" / "api" / "http" / "mocap")]
sys.modules["freemocap.api.http.mocap"] = mocap_http_pkg

# Load task_queue (registers demo + mocap.run_3d tasks)
spec = importlib.util.spec_from_file_location(
    "freemocap.services.task_queue",
    REPO_ROOT / "freemocap" / "services" / "task_queue.py",
)
task_queue_mod = importlib.util.module_from_spec(spec)
sys.modules["freemocap.services.task_queue"] = task_queue_mod
spec.loader.exec_module(task_queue_mod)

# Load mocap_3d_service
spec = importlib.util.spec_from_file_location(
    "freemocap.services.mocap_3d_service",
    REPO_ROOT / "freemocap" / "services" / "mocap_3d_service.py",
)
mocap3d_mod = importlib.util.module_from_spec(spec)
sys.modules["freemocap.services.mocap_3d_service"] = mocap3d_mod
spec.loader.exec_module(mocap3d_mod)

# Load tasks_router
spec = importlib.util.spec_from_file_location(
    "freemocap.api.http.tasks.tasks_router",
    REPO_ROOT / "freemocap" / "api" / "http" / "tasks" / "tasks_router.py",
)
router_mod = importlib.util.module_from_spec(spec)
sys.modules["freemocap.api.http.tasks.tasks_router"] = router_mod
spec.loader.exec_module(router_mod)
tasks_router = router_mod.tasks_router

# Load mocap_3d_router
spec = importlib.util.spec_from_file_location(
    "freemocap.api.http.mocap.mocap_3d_router",
    REPO_ROOT / "freemocap" / "api" / "http" / "mocap" / "mocap_3d_router.py",
)
m3d_mod = importlib.util.module_from_spec(spec)
sys.modules["freemocap.api.http.mocap.mocap_3d_router"] = m3d_mod
spec.loader.exec_module(m3d_mod)
mocap_3d_router = m3d_mod.mocap_3d_router

app = FastAPI()
app.include_router(tasks_router)
app.include_router(mocap_3d_router)


async def main():
    config = uvicorn.Config(app=app, host="127.0.0.1", port=8099, log_level="error")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    for _ in range(30):
        if server.started:
            break
        await asyncio.sleep(0.1)
    await asyncio.sleep(0.3)

    try:
        # Create a fake recording folder
        video_dir = Path(tempfile.mkdtemp(prefix="fmc_3d_test_"))

        async with httpx.AsyncClient(base_url="http://127.0.0.1:8099", timeout=30.0) as client:
            # 1. List task types — should include mocap.run_3d
            r = await client.get("/tasks/types")
            print(f"[types]    -> {r.status_code}  {r.json()}")
            assert r.status_code == 200
            assert "mocap.run_3d" in r.json()["task_types"]

            # 2. Submit 3D mocap task via the convenience endpoint
            r = await client.post("/mocap-3d/run", json={
                "video_dir": str(video_dir),
                "tracker": "mediapipe",
            })
            print(f"[submit 3d] -> {r.status_code}  {r.json()}")
            assert r.status_code == 200
            task_id = r.json()["task_id"]
            assert r.json()["task_type"] == "mocap.run_3d"

            # 3. Poll status, capturing the stage progression
            seen_stages = []
            final_state = None
            for i in range(60):
                r = await client.get(f"/tasks/{task_id}")
                assert r.status_code == 200
                data = r.json()
                state = data["state"]
                progress = data["progress"]
                msg = data["message"]
                if i % 3 == 0 or state in ("SUCCESS", "FAILURE"):
                    print(f"[poll {i:02d}]  -> state={state} progress={progress:.2f} msg={msg}")
                if state == "PROGRESS" and msg and msg not in seen_stages:
                    seen_stages.append(msg)
                if state in ("SUCCESS", "FAILURE", "REVOKED"):
                    final_state = state
                    break
                await asyncio.sleep(0.1)

            assert final_state == "SUCCESS", f"expected SUCCESS, got {final_state}"

            # Verify we saw progress through multiple stages
            print(f"\nStages observed: {seen_stages[:8]}...")
            assert len(seen_stages) >= 3, "Expected progress through multiple stages"

            # 4. Get result
            r = await client.get(f"/tasks/{task_id}/result")
            print(f"[result]   -> {r.status_code}")
            result = r.json()["result"]
            print(f"           video_dir={result.get('video_dir')}")
            print(f"           output_dir={result.get('output_dir')}")
            print(f"           skeleton_3d_path={result.get('skeleton_3d_path')}")
            print(f"           simulated={result.get('simulated')}")
            assert result.get("simulated") is True  # real pipeline needs skellytracker
            assert result.get("skeleton_3d_path") is not None

            # 5. Test missing video_dir
            r = await client.post("/mocap-3d/run", json={"video_dir": "/nonexistent/path"})
            print(f"[bad dir]  -> {r.status_code}")
            assert r.status_code == 400

        print("\n✅ 3D mocap task endpoints all passed (simulated pipeline)")
    finally:
        server.should_exit = True
        await server_task


asyncio.run(main())
