import asyncio
from unittest.mock import MagicMock

import pytest
from minio.error import S3Error
from pydantic import SecretStr, ValidationError

from erp.platform.config import Settings
from erp.platform.config.settings import Environment
from erp.platform.errors import ApplicationError
from erp.platform.storage.minio import MAX_OBJECT_BYTES, MinioStorage


def test_minio_private_policy_limits_and_response_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    monkeypatch.setattr("erp.platform.storage.minio.Minio", lambda *args, **kwargs: client)
    storage = MinioStorage(Settings())
    with pytest.raises(ApplicationError, match="anonymous"):
        storage._private_bucket()
    denied = S3Error(MagicMock(), "AccessDenied", "Denied", "resource", "request", "host")
    client.get_bucket_policy.side_effect = denied
    with pytest.raises(S3Error):
        storage._private_bucket()
    private = S3Error(MagicMock(), "NoSuchBucketPolicy", "Private", "resource", "request", "host")
    client.get_bucket_policy.side_effect = private
    for content in (b"", b"x" * (MAX_OBJECT_BYTES + 1)):
        with pytest.raises(ValueError, match="10 MiB"):
            asyncio.run(storage.put("key", content))
    response = MagicMock()
    response.read.return_value = b"x" * (MAX_OBJECT_BYTES + 1)
    client.get_object.return_value = response
    with pytest.raises(ValueError, match="size limit"):
        asyncio.run(storage.get("key"))
    response.close.assert_called_once()
    response.release_conn.assert_called_once()
    asyncio.run(storage.delete("key"))
    client.remove_object.assert_called_once()


def test_storage_requires_secret_and_production_tls() -> None:
    with pytest.raises(ValidationError, match="secret key"):
        Settings(import_storage_access_key="scoped")
    with pytest.raises(ValidationError, match="TLS"):
        Settings(
            environment=Environment.PRODUCTION,
            import_storage_access_key="scoped",
            import_storage_secret_key=SecretStr("secret"),
            import_storage_secure=False,
        )
