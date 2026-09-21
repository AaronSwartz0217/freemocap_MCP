"""Local test for the storage endpoints (local backend).

Loads freemocap/services/storage.py and freemocap/api/http/storage/storage_router.py
directly via importlib (bypassing freemocap/__init__.py which needs skellylogs),
then exercises upload / download / url / info / delete against the local backend.
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

# --- Stub out the freemocap package hierarchy so relative imports resolve ---
freemocap_pkg = ModuleType("freemocap")
freemocap_pkg.__path__ = [str(REPO_ROOT / "freemocap")]
sys.modules["freemocap"] = freemocap_pkg

services_pkg = ModuleType("freemocap.services")
services_pkg.__path__ = [str(REPO_ROOT / "freemocap" / "services")]
sys.modules["freemocap.services"] = services_pkg

http_pkg = ModuleType("freemocap.api.http")
http_pkg.__path__ = [str(REPO_ROOT / "freemocap" / "api" / "http")]
sys.modules["freemocap.api.http"] = http_pkg

storage_http_pkg = ModuleType("freemocap.api.http.storage")
storage_http_pkg.__path__ = [str(REPO_ROOT / "freemocap" / "api" / "http" / "storage")]
sys.modules["freemocap.api.http.storage"] = storage_http_pkg

# Load the storage service module
spec = importlib.util.spec_from_file_location(
    "freemocap.services.storage",
    REPO_ROOT / "freemocap" / "services" / "storage.py",
)
storage_mod = importlib.util.module_from_spec(spec)
sys.modules["freemocap.services.storage"] = storage_mod
spec.loader.exec_module(storage_mod)

# Load the storage router
spec = importlib.util.spec_from_file_location(
    "freemocap.api.http.storage.storage_router",
    REPO_ROOT / "freemocap" / "api" / "http" / "storage" / "storage_router.py",
)
router_mod = importlib.util.module_from_spec(spec)
sys.modules["freemocap.api.http.storage.storage_router"] = router_mod
spec.loader.exec_module(router_mod)
storage_router = router_mod.storage_router

# Configure local backend via env vars
tmp_dir = tempfile.mkdtemp(prefix="fmc_storage_test_")
os.environ["FMC_STORAGE_BACKEND"] = "local"
os.environ["FMC_STORAGE_LOCAL_DIR"] = tmp_dir

app = FastAPI()
app.include_router(storage_router)


async def main():
    config = uvicorn.Config(app=app, host="127.0.0.1", port=8097, log_level="error")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    for _ in range(30):
        if server.started:
            break
        await asyncio.sleep(0.1)
    await asyncio.sleep(0.3)

    try:
        test_content = b"Hello, FreeMoCap storage pool!"
        async with httpx.AsyncClient(base_url="http://127.0.0.1:8097", timeout=10.0) as client:
            # 1. Upload
            r = await client.post(
                "/storage/upload",
                files={"file": ("test.txt", test_content, "text/plain")},
                params={"prefix": "uploads/test"},
            )
            print(f"[upload]   -> {r.status_code}")
            assert r.status_code == 200, r.text
            body = r.json()
            key = body["key"]
            print(f"           key={key}, size={body['size_bytes']}, url={body['download_url']}")
            assert key.startswith("uploads/test/")

            # 2. Info (exists)
            r = await client.get(f"/storage/info/{key}")
            print(f"[info]     -> {r.status_code}  exists={r.json()['exists']}")
            assert r.json()["exists"] is True

            # 3. Download
            r = await client.get(f"/storage/download/{key}")
            print(f"[download] -> {r.status_code}  bytes={len(r.content)}")
            assert r.status_code == 200
            assert r.content == test_content, "Downloaded content mismatch!"

            # 4. URL
            r = await client.get(f"/storage/url/{key}")
            print(f"[url]      -> {r.status_code}  url={r.json()['download_url']}")
            assert r.status_code == 200

            # 5. Info (non-existent)
            r = await client.get("/storage/info/does/not/exist")
            print(f"[info 404] -> {r.status_code}  exists={r.json()['exists']}")
            assert r.json()["exists"] is False

            # 6. Delete
            r = await client.delete(f"/storage/{key}")
            print(f"[delete]   -> {r.status_code}  deleted={r.json()['deleted']}")
            assert r.status_code == 200

            # 7. Info after delete
            r = await client.get(f"/storage/info/{key}")
            print(f"[info del] -> {r.status_code}  exists={r.json()['exists']}")
            assert r.json()["exists"] is False

            print("\n✅ Storage endpoints (local backend) all passed")
    finally:
        server.should_exit = True
        await server_task


asyncio.run(main())
