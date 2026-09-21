"""
End-to-end test for the task queue (in-process backend).

Loads freemocap/services/task_queue.py and freemocap/api/http/tasks/tasks_router.py
directly via importlib (bypassing freemocap/__init__.py which needs skellylogs).
Forces FMC_TASK_QUEUE_BACKEND=inprocess so no Redis is required.
"""
import asyncio
import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType

import httpx
import uvicorn
from fastapi import FastAPI

REPO_ROOT = Path(r"d:\本地动捕环境\freemocap_MCP")

# Force in-process backend before any import
os.environ["FMC_TASK_QUEUE_BACKEND"] = "inprocess"

# --- Stub out the freemocap package hierarchy so relative imports resolve ---
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

# Load the task_queue service module
spec = importlib.util.spec_from_file_location(
    "freemocap.services.task_queue",
    REPO_ROOT / "freemocap" / "services" / "task_queue.py",
)
task_queue_mod = importlib.util.module_from_spec(spec)
sys.modules["freemocap.services.task_queue"] = task_queue_mod
spec.loader.exec_module(task_queue_mod)

# Load the tasks router
spec = importlib.util.spec_from_file_location(
    "freemocap.api.http.tasks.tasks_router",
    REPO_ROOT / "freemocap" / "api" / "http" / "tasks" / "tasks_router.py",
)
router_mod = importlib.util.module_from_spec(spec)
sys.modules["freemocap.api.http.tasks.tasks_router"] = router_mod
spec.loader.exec_module(router_mod)
tasks_router = router_mod.tasks_router

app = FastAPI()
app.include_router(tasks_router)


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
        async with httpx.AsyncClient(base_url="http://127.0.0.1:8098", timeout=10.0) as client:
            # 1. List task types
            r = await client.get("/tasks/types")
            print(f"[types]    -> {r.status_code}  {r.json()}")
            assert r.status_code == 200
            assert "demo.long_task" in r.json()["task_types"]

            # 2. Submit demo.long_task
            r = await client.post("/tasks/submit", json={"task_type": "demo.long_task", "payload": {"steps": 3, "delay": 0.1}})
            print(f"[submit]   -> {r.status_code}  {r.json()}")
            assert r.status_code == 200
            task_id = r.json()["task_id"]

            # 3. Poll status until done
            state = None
            progress = 0.0
            for i in range(30):
                r = await client.get(f"/tasks/{task_id}")
                assert r.status_code == 200
                data = r.json()
                state = data["state"]
                progress = data["progress"]
                print(f"[poll {i}]   -> state={state} progress={progress:.2f} msg={data['message']}")
                if state in ("SUCCESS", "FAILURE", "REVOKED"):
                    break
                await asyncio.sleep(0.1)

            assert state == "SUCCESS", f"expected SUCCESS, got {state}"
            assert abs(progress - 1.0) < 1e-6

            # 4. Get result
            r = await client.get(f"/tasks/{task_id}/result")
            print(f"[result]   -> {r.status_code}  {r.json()}")
            assert r.status_code == 200
            result = r.json()["result"]
            assert result["steps"] == 3
            assert result["done"] is True

            # 5. Test cancellation
            r = await client.post("/tasks/submit", json={"task_type": "demo.long_task", "payload": {"steps": 50, "delay": 0.05}})
            task_id2 = r.json()["task_id"]
            await asyncio.sleep(0.1)
            r = await client.delete(f"/tasks/{task_id2}")
            print(f"[cancel]   -> {r.status_code}  {r.json()}")
            assert r.status_code == 200
            assert r.json()["cancelled"] is True

            await asyncio.sleep(0.3)
            r = await client.get(f"/tasks/{task_id2}")
            state2 = r.json()["state"]
            print(f"[cancelled state] -> {state2}")
            assert state2 in ("REVOKED", "FAILURE")

            # 6. Unknown task type
            r = await client.post("/tasks/submit", json={"task_type": "nonexistent", "payload": {}})
            print(f"[unknown]  -> {r.status_code}  {r.json()}")
            assert r.status_code == 400

            # 7. Non-existent task id
            r = await client.get("/tasks/nonexistent-id")
            print(f"[404]      -> {r.status_code}")
            assert r.status_code == 404

        print("\n✅ Task queue endpoints (in-process backend) all passed")
    finally:
        server.should_exit = True
        await server_task


asyncio.run(main())
