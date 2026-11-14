"""Object storage behind one small interface. Keys are always tenant-prefixed."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, Protocol

from app.core.config import get_settings


def media_key(tenant_id: uuid.UUID, asset_id: uuid.UUID, name: str) -> str:
    safe = "".join(ch for ch in name if ch.isalnum() or ch in "._-")
    safe = re.sub(r"\.{2,}", ".", safe).lstrip(".")[:100] or "file"
    return f"tenants/{tenant_id}/media/{asset_id}/{safe}"


def key_belongs_to(key: str, tenant_id: uuid.UUID) -> bool:
    return key.startswith(f"tenants/{tenant_id}/") and ".." not in key


class Storage(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...


class LocalStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("invalid storage key")
        return path

    def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()


class S3Storage:
    """Any S3-compatible service (AWS S3, Cloudflare R2, MinIO, ...). Objects stay private."""

    def __init__(self, *, bucket: str, client: Any) -> None:
        self.bucket = bucket
        self.client = client

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def get(self, key: str) -> bytes:
        body: bytes = self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        return body


def get_storage() -> Storage:
    s = get_settings()
    if s.storage_backend == "s3":
        import boto3

        client = boto3.client(
            "s3",
            endpoint_url=s.s3_endpoint_url or None,
            region_name=s.s3_region,
            aws_access_key_id=s.s3_access_key or None,
            aws_secret_access_key=s.s3_secret_key or None,
        )
        return S3Storage(bucket=s.s3_bucket, client=client)
    return LocalStorage(s.storage_local_root)
