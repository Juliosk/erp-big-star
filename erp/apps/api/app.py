"""FastAPI application factory."""

from fastapi import FastAPI

from erp.platform.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the public HTTP application."""
    resolved_settings = settings or get_settings()
    application = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    application.state.settings = resolved_settings
    return application


app = create_app()

__all__ = ["app", "create_app"]
