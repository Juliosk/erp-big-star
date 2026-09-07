"""Environment-backed application settings."""

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, PositiveInt, SecretStr
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
    enable_platform_test_endpoint: bool | None = None

    @property
    def platform_test_endpoint_enabled(self) -> bool:
        """Enable the disposable golden-flow endpoint only outside production by default."""
        if self.enable_platform_test_endpoint is not None:
            return self.enable_platform_test_endpoint
        return self.environment in {Environment.LOCAL, Environment.TEST}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide immutable configuration source."""
    return Settings()


__all__ = ["Environment", "LogLevel", "Settings", "get_settings"]
