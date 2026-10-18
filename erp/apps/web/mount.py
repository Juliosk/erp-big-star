"""Static UI is public; every data request uses the protected official APIs."""

from pathlib import Path

from fastapi import FastAPI
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Message, Receive, Scope, Send


class WebFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        if path.rstrip("/") == "treasury":
            path = "index.html"
        return await super().get_response(path, scope)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def secured_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (
                            b"content-security-policy",
                            b"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
                        ),
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"no-referrer"),
                        (b"cache-control", b"no-store"),
                    ]
                )
                message = {**message, "headers": headers}
            await send(message)

        await super().__call__(scope, receive, secured_send)


def mount_web(application: FastAPI) -> None:
    application.mount(
        "/ui", WebFiles(directory=Path(__file__).parent / "static", html=True), name="product-web"
    )


__all__ = ["mount_web"]
