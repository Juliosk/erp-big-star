"""MinIO adapter: private bucket, bounded reads, no public or presigned URLs."""

import asyncio
import hashlib
from io import BytesIO

from minio import Minio
from minio.error import S3Error
from urllib3 import PoolManager

from erp.platform.config import Settings
from erp.platform.errors import ApplicationError
from erp.platform.storage.objects import StoredObject

MAX_OBJECT_BYTES = 10 * 1024 * 1024
XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class MinioStorage:
    def __init__(self, settings: Settings) -> None:
        self._bucket = settings.import_storage_bucket
        self._client = Minio(
            settings.import_storage_endpoint,
            access_key=settings.import_storage_access_key,
            secret_key=settings.import_storage_secret_key.get_secret_value(),
            secure=settings.import_storage_secure,
            http_client=PoolManager(timeout=10.0, retries=False),
        )

    def _private_bucket(self) -> None:
        # Deployment provisions the bucket. Never create or change its policy in a request.
        try:
            self._client.get_bucket_policy(self._bucket)
        except S3Error as error:
            if error.code == "NoSuchBucketPolicy":
                return
            raise
        raise ApplicationError(
            code="IMPORT_STORAGE_NOT_PRIVATE",
            message="Import storage must have no anonymous bucket policy.",
            status_code=503,
        )

    async def put(self, key: str, content: bytes) -> StoredObject:
        if not 1 <= len(content) <= MAX_OBJECT_BYTES:
            raise ValueError("Object must contain 1 byte to 10 MiB.")
        await asyncio.to_thread(self._private_bucket)
        await asyncio.to_thread(
            self._client.put_object,
            self._bucket,
            key,
            BytesIO(content),
            len(content),
            content_type=XLSX_CONTENT_TYPE,
        )
        return StoredObject(key, hashlib.sha256(content).hexdigest(), len(content))

    def _read(self, key: str) -> bytes:
        self._private_bucket()
        response = self._client.get_object(self._bucket, key)
        try:
            content = response.read(MAX_OBJECT_BYTES + 1)
            if len(content) > MAX_OBJECT_BYTES:
                raise ValueError("Stored object exceeds the size limit.")
            return bytes(content)
        finally:
            response.close()
            response.release_conn()

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._read, key)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._client.remove_object, self._bucket, key)


__all__ = ["XLSX_CONTENT_TYPE", "MinioStorage"]
