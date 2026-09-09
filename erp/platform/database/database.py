"""SQLAlchemy engine and session lifecycle."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import URL, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from erp.platform.config import Settings


class DatabaseUnavailableError(RuntimeError):
    """Raised when the configured database cannot answer a probe."""


class Database:
    """Own the asynchronous engine and unit-of-work session factory."""

    def __init__(self, settings: Settings) -> None:
        self._url = self.build_url(settings)
        self._engine = create_async_engine(
            self._url,
            pool_pre_ping=True,
            hide_parameters=True,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_timeout=settings.database_pool_timeout,
        )
        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            autoflush=False,
            expire_on_commit=False,
        )

    @staticmethod
    def build_url(settings: Settings) -> URL:
        """Build a password-safe PostgreSQL URL without string concatenation."""
        return URL.create(
            drivername="postgresql+asyncpg",
            username=settings.postgres_user,
            password=settings.postgres_password.get_secret_value(),
            host=settings.postgres_host,
            port=settings.postgres_port,
            database=settings.postgres_db,
        )

    @property
    def engine(self) -> AsyncEngine:
        """Expose the engine for infrastructure integrations such as Alembic."""
        return self._engine

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Provide a transaction-neutral asynchronous database session."""
        async with self._session_factory() as session:
            yield session

    async def ping(self) -> None:
        """Execute the minimal PostgreSQL readiness probe."""
        try:
            async with self._engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except (OSError, SQLAlchemyError) as error:
            raise DatabaseUnavailableError from error

    async def dispose(self) -> None:
        """Release all pooled connections."""
        await self._engine.dispose()


__all__ = ["Database", "DatabaseUnavailableError"]
