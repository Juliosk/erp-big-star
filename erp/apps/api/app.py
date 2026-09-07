"""FastAPI application factory."""

from fastapi import FastAPI


def create_app() -> FastAPI:
    """Build the public HTTP application."""
    return FastAPI(
        title="ERP Big Star / Forma Kids",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )


app = create_app()

__all__ = ["app", "create_app"]
