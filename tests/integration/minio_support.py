"""Real MinIO fixture owns an exclusive random private bucket and its objects."""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

from minio import Minio
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from erp.platform.config import Settings
from erp.platform.storage.minio import MinioStorage


class LocalMinioSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    minio_root_user: str = ""
    minio_root_password: SecretStr = SecretStr("")
    minio_api_port: int = 9000


@contextmanager
def minio_storage() -> Iterator[MinioStorage]:
    local = LocalMinioSettings()
    bucket = f"erp-import-test-{uuid4().hex}"
    endpoint = f"127.0.0.1:{local.minio_api_port}"
    client = Minio(
        endpoint, local.minio_root_user, local.minio_root_password.get_secret_value(), secure=False
    )
    client.make_bucket(bucket)
    settings = Settings(
        import_storage_endpoint=endpoint,
        import_storage_bucket=bucket,
        import_storage_access_key=local.minio_root_user,
        import_storage_secret_key=local.minio_root_password,
        import_storage_secure=False,
    )
    try:
        yield MinioStorage(settings)
    finally:
        # Only keys in the bucket created by this context. No shared bucket is touched.
        for item in client.list_objects(bucket, recursive=True):
            assert item.object_name is not None
            client.remove_object(bucket, item.object_name)
        client.remove_bucket(bucket)
