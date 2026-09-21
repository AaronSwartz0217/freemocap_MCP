"""Storage pool abstraction for FreeMoCap MCP.

Provides a uniform interface for storing and retrieving files (uploads,
pipeline outputs, skeleton images, etc.) on either the local filesystem
(development) or an S3-compatible service such as MinIO / AWS S3 (production).

Backends are selected at runtime via the ``FMC_STORAGE_BACKEND`` environment
variable:
  * ``local`` (default) — stores files under ``FMC_STORAGE_LOCAL_DIR``
  * ``s3``  — uses boto3 against ``FMC_S3_ENDPOINT`` with the configured bucket

All credentials and endpoints are read from environment variables — never
hard-code them in the source tree.
"""

from __future__ import annotations

import io
import logging
import os
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger(__name__)


class StorageBackend(ABC):
    """Abstract storage backend interface."""

    @abstractmethod
    def put_object(self, key: str, data: bytes, content_type: str | None = None) -> str:
        """Store ``data`` under ``key`` and return the (possibly normalized) key."""

    @abstractmethod
    def get_object(self, key: str) -> bytes:
        """Return the raw bytes stored under ``key``."""

    @abstractmethod
    def get_download_url(self, key: str, expires_in: int = 3600) -> str:
        """Return a URL that can be used to download the object.

        For the local backend this is a direct ``/storage/download/{key}`` URL
        served by the FastAPI app; for S3 it is a presigned URL.
        """

    @abstractmethod
    def delete_object(self, key: str) -> None:
        """Delete the object stored under ``key`` (no-op if missing)."""

    @abstractmethod
    def object_exists(self, key: str) -> bool:
        """Return True if an object with ``key`` exists."""


# ---------------------------------------------------------------------------
# Local filesystem backend
# ---------------------------------------------------------------------------

class LocalStorageBackend(StorageBackend):
    """Store files on the local filesystem under a base directory.

    Keys are interpreted as relative paths; nested keys (containing ``/``)
    create the corresponding subdirectories.
    """

    def __init__(self, base_dir: str | Path):
        self._base_dir = Path(base_dir).expanduser().resolve()
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        # Prevent path traversal: strip leading slashes and resolve under base.
        safe = key.lstrip("/").replace("\\", "/")
        path = (self._base_dir / safe).resolve()
        if not str(path).startswith(str(self._base_dir)):
            raise ValueError(f"Invalid storage key (path traversal): {key}")
        return path

    def put_object(self, key: str, data: bytes, content_type: str | None = None) -> str:
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        logger.info(f"[storage:local] put {key} ({len(data)} bytes)")
        return key

    def get_object(self, key: str) -> bytes:
        path = self._path_for(key)
        if not path.is_file():
            raise FileNotFoundError(f"Object not found: {key}")
        return path.read_bytes()

    def get_download_url(self, key: str, expires_in: int = 3600) -> str:
        # Served by the storage router's download endpoint.
        return f"/storage/download/{key}"

    def delete_object(self, key: str) -> None:
        path = self._path_for(key)
        if path.is_file():
            path.unlink()
            logger.info(f"[storage:local] deleted {key}")

    def object_exists(self, key: str) -> bool:
        return self._path_for(key).is_file()


# ---------------------------------------------------------------------------
# S3 / MinIO backend
# ---------------------------------------------------------------------------

class S3StorageBackend(StorageBackend):
    """Store files on an S3-compatible service (AWS S3, MinIO, etc.)."""

    def __init__(
        self,
        endpoint: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
    ):
        import boto3

        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )
        # Ensure bucket exists (MinIO requires explicit creation).
        try:
            self._client.head_bucket(Bucket=bucket)
        except Exception:
            self._client.create_bucket(Bucket=bucket)
            logger.info(f"[storage:s3] created bucket '{bucket}'")

    def put_object(self, key: str, data: bytes, content_type: str | None = None) -> str:
        extra = {}
        if content_type:
            extra["ContentType"] = content_type
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, **extra)
        logger.info(f"[storage:s3] put {key} ({len(data)} bytes)")
        return key

    def get_object(self, key: str) -> bytes:
        resp = self._client.get_object(Bucket=self._bucket, Key=key)
        return resp["Body"].read()

    def get_download_url(self, key: str, expires_in: int = 3600) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    def delete_object(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)
        logger.info(f"[storage:s3] deleted {key}")

    def object_exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_storage_backend() -> StorageBackend:
    """Return the configured storage backend based on environment variables.

    Environment variables:
      FMC_STORAGE_BACKEND   — "local" (default) or "s3"
      FMC_STORAGE_LOCAL_DIR — local base directory (default: ./freemocap_storage)
      FMC_S3_ENDPOINT       — S3/MinIO endpoint URL, e.g. http://minio:9000
      FMC_S3_BUCKET         — bucket name
      FMC_S3_ACCESS_KEY     — access key id
      FMC_S3_SECRET_KEY     — secret access key
      FMC_S3_REGION         — region (default: us-east-1)
    """
    backend = os.environ.get("FMC_STORAGE_BACKEND", "local").lower()

    if backend == "s3":
        endpoint = os.environ.get("FMC_S3_ENDPOINT", "")
        bucket = os.environ.get("FMC_S3_BUCKET", "freemocap")
        access_key = os.environ.get("FMC_S3_ACCESS_KEY", "")
        secret_key = os.environ.get("FMC_S3_SECRET_KEY", "")
        region = os.environ.get("FMC_S3_REGION", "us-east-1")
        if not endpoint or not access_key or not secret_key:
            raise RuntimeError(
                "FMC_STORAGE_BACKEND=s3 requires FMC_S3_ENDPOINT, "
                "FMC_S3_ACCESS_KEY, and FMC_S3_SECRET_KEY to be set."
            )
        return S3StorageBackend(
            endpoint=endpoint,
            bucket=bucket,
            access_key=access_key,
            secret_key=secret_key,
            region=region,
        )

    local_dir = os.environ.get("FMC_STORAGE_LOCAL_DIR", "./freemocap_storage")
    return LocalStorageBackend(base_dir=local_dir)


def generate_object_key(prefix: str = "", filename: str | None = None) -> str:
    """Generate a unique object key.

    Args:
        prefix: optional folder prefix (e.g. "uploads" or "uploads/user123").
        filename: original filename; if provided, its extension is preserved.
    """
    ext = ""
    if filename:
        ext = Path(filename).suffix
    unique = uuid.uuid4().hex
    parts = [p for p in (prefix.strip("/"), unique + ext) if p]
    return "/".join(parts)
