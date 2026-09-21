"""Storage pool HTTP endpoints.

Endpoints:
  POST   /storage/upload      — upload a file, returns object key + download URL
  GET    /storage/download/{key} — download a stored file by its key
  GET    /storage/url/{key}   — get a download URL (presigned for S3)
  DELETE /storage/{key}       — delete a stored object
  GET    /storage/info/{key}  — check whether an object exists
"""

import logging
import mimetypes

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import Response

from freemocap.services.storage import generate_object_key, get_storage_backend

logger = logging.getLogger(__name__)

storage_router = APIRouter(prefix="/storage", tags=["Storage"])

# Cache the backend on first use; re-create only if env changes at runtime.
_backend_instance = None


def _backend():
    global _backend_instance
    if _backend_instance is None:
        _backend_instance = get_storage_backend()
    return _backend_instance


@storage_router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    prefix: str = Query(default="uploads", description="Storage key prefix / folder"),
) -> dict:
    """Upload a file to the storage pool.

    Returns a unique object ``key`` and a ``download_url`` that can be used to
    retrieve the file later. The original filename's extension is preserved.
    """
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file uploaded.")

    key = generate_object_key(prefix=prefix, filename=file.filename)
    content_type = file.content_type or mimetypes.guess_type(file.filename or "")[0]
    _backend().put_object(key, data, content_type=content_type)

    download_url = _backend().get_download_url(key)
    logger.info(f"[storage] uploaded {file.filename} -> {key} ({len(data)} bytes)")

    return {
        "success": True,
        "key": key,
        "filename": file.filename,
        "size_bytes": len(data),
        "content_type": content_type,
        "download_url": download_url,
    }


@storage_router.get("/download/{key:path}")
async def download_file(key: str) -> Response:
    """Download a stored object by its key."""
    try:
        data = _backend().get_object(key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Object not found: {key}")

    content_type, _ = mimetypes.guess_type(key)
    return Response(
        content=data,
        media_type=content_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{key.split("/")[-1]}"'},
    )


@storage_router.get("/url/{key:path}")
async def get_url(key: str, expires_in: int = Query(default=3600, ge=60, le=604800)) -> dict:
    """Return a download URL for the object.

    For the S3 backend this is a presigned URL valid for ``expires_in`` seconds.
    For the local backend it returns the app's direct download endpoint.
    """
    if not _backend().object_exists(key):
        raise HTTPException(status_code=404, detail=f"Object not found: {key}")
    url = _backend().get_download_url(key, expires_in=expires_in)
    return {"success": True, "key": key, "download_url": url, "expires_in": expires_in}


@storage_router.delete("/{key:path}")
async def delete_file(key: str) -> dict:
    """Delete a stored object."""
    if not _backend().object_exists(key):
        raise HTTPException(status_code=404, detail=f"Object not found: {key}")
    _backend().delete_object(key)
    return {"success": True, "key": key, "deleted": True}


@storage_router.get("/info/{key:path}")
async def object_info(key: str) -> dict:
    """Check whether an object exists."""
    exists = _backend().object_exists(key)
    return {"success": True, "key": key, "exists": exists}
