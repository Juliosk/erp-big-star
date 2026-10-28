"""Environment-backed application settings."""

from enum import StrEnum
from functools import lru_cache
from typing import Self
from uuid import UUID

from pydantic import Field, PositiveInt, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """Supported deployment environments."""

    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    """Allowed application log levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class Settings(BaseSettings):
    """Configuration loaded from environment variables and a local dotenv file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "ERP Big Star / Forma Kids"
    app_version: str = "0.1.0"
    environment: Environment = Environment.LOCAL
    debug: bool = False
    log_level: LogLevel = LogLevel.INFO
    readiness_database_timeout_seconds: float = Field(default=2.0, gt=0)
    dev_auth_enabled: bool = False
    dev_auth_token: SecretStr = SecretStr("")
    dev_auth_actor_id: UUID | None = None
    dev_auth_company_ids: tuple[UUID, ...] = ()
    dev_auth_permissions: tuple[str, ...] = (
        "admin.company.read",
        "product.product.read",
        "product.product.create",
        "product.product.update",
        "product.product.activate",
        "product.product.discontinue",
        "crm.customer.read",
        "crm.customer.create",
        "crm.customer.update",
        "crm.customer.merge",
        "inventory.balance.read",
        "inventory.availability.read",
        "inventory.reservation.manage",
        "inventory.warehouse.read",
        "inventory.warehouse.create",
        "inventory.location.read",
        "inventory.location.create",
        "inventory.pool.read",
        "inventory.pool.create",
        "inventory.lot.read",
        "inventory.lot.create",
        "inventory.adjustment.create",
        "pricing.price.simulate",
        "pricing.price.create",
        "pricing.price.activate",
        "pricing.margin.view",
        "pricing.exception.request",
        "wms.pick.execute",
        "wms.pack.execute",
        "wms.dispatch.execute",
        "wms.label.reprint",
        "wms.shortage.override",
        "workflow.request.read",
        "workflow.request.create",
        "workflow.approval.decide",
        "procurement.supplier.read",
        "procurement.supplier.manage",
        "procurement.requisition.read",
        "procurement.requisition.manage",
        "procurement.order.read",
        "procurement.order.manage",
        "procurement.receipt.read",
        "procurement.receipt.manage",
        "procurement.matching.read",
        "procurement.matching.execute",
        "fiscal.nfe.read",
        "fiscal.inbound.read",
        "fiscal.inbound.manage",
        "fiscal.nfe.issue",
        "fiscal.nfe.cancel",
        "fiscal.nfe.correct",
        "finance.payable.read",
        "finance.payable.create",
        "finance.payable.approve",
        "finance.payable.adjust",
        "finance.treasury.read",
        "finance.treasury_batch.create",
        "finance.treasury_batch.approve",
        "finance.treasury_batch.execute",
        "finance.reconciliation.read",
        "finance.reconciliation.import",
        "finance.reconciliation.execute",
        "workflow.definition.manage",
    )

    @model_validator(mode="after")
    def validate_dev_auth(self) -> Self:
        if self.dev_auth_enabled:
            if self.environment not in {Environment.LOCAL, Environment.TEST}:
                raise ValueError("Development authentication is forbidden outside local/test.")
            token = self.dev_auth_token.get_secret_value()
            if (
                not 32 <= len(token) <= 256
                or not token.isascii()
                or any(char.isspace() for char in token)
            ):
                raise ValueError(
                    "Development token must contain 32-256 non-whitespace ASCII characters."
                )
            if self.dev_auth_actor_id is None or not self.dev_auth_company_ids:
                raise ValueError(
                    "Development authentication requires an actor and explicit company IDs."
                )
        return self

    postgres_host: str = "127.0.0.1"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str = "erp_oltp"
    postgres_user: str = "erp_app"
    postgres_password: SecretStr = SecretStr("")
    database_pool_size: int = Field(default=5, ge=1)
    database_max_overflow: int = Field(default=10, ge=0)
    database_pool_timeout: float = Field(default=30.0, gt=0)

    rabbitmq_host: str = "127.0.0.1"
    rabbitmq_amqp_port: int = Field(default=5672, ge=1, le=65535)
    rabbitmq_default_user: str = "erp_app"
    rabbitmq_default_pass: SecretStr = SecretStr("")
    rabbitmq_virtual_host: str = "/"
    rabbitmq_connection_timeout_seconds: float = Field(default=5.0, gt=0)
    rabbitmq_prefetch_count: int = Field(default=20, ge=1)
    rabbitmq_events_exchange: str = "erp.events"
    rabbitmq_requests_exchange: str = "erp.requests"
    rabbitmq_retry_exchange: str = "erp.retry"
    rabbitmq_dead_letter_exchange: str = "erp.dlx"
    rabbitmq_retry_delays_ms: tuple[
        PositiveInt,
        PositiveInt,
        PositiveInt,
        PositiveInt,
    ] = (30_000, 120_000, 300_000, 900_000)
    idempotency_ttl_seconds: int = Field(default=86_400, ge=60)

    import_storage_endpoint: str = "127.0.0.1:9000"
    import_storage_bucket: str = "erp-imports"
    import_storage_access_key: str = ""
    import_storage_secret_key: SecretStr = SecretStr("")
    import_storage_secure: bool = True

    @model_validator(mode="after")
    def validate_import_storage(self) -> Self:
        if self.import_storage_access_key:
            if not self.import_storage_secret_key.get_secret_value():
                raise ValueError("Import storage requires a secret key.")
            if not self.import_storage_secure and self.environment not in {
                Environment.LOCAL,
                Environment.TEST,
            }:
                raise ValueError("Import storage requires TLS outside local/test.")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide immutable configuration source."""
    return Settings()


__all__ = ["Environment", "LogLevel", "Settings", "get_settings"]
