from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse


_STATIC_ROOT = Path(__file__).with_name("static")
_CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "connect-src 'self'",
        "media-src 'self'",
        "img-src 'self' data:",
        "object-src 'none'",
        "base-uri 'none'",
        "frame-ancestors 'none'",
        "form-action 'self'",
    )
)


def register_ui(application: FastAPI) -> None:
    @application.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(
            _STATIC_ROOT / "index.html",
            media_type="text/html",
            headers={
                "Cache-Control": "no-cache",
                "Content-Security-Policy": _CONTENT_SECURITY_POLICY,
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @application.get("/assets/app.css", include_in_schema=False)
    async def stylesheet() -> FileResponse:
        return FileResponse(
            _STATIC_ROOT / "app.css",
            media_type="text/css",
            headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"},
        )

    @application.get("/assets/app.js", include_in_schema=False)
    async def javascript() -> FileResponse:
        return FileResponse(
            _STATIC_ROOT / "app.js",
            media_type="text/javascript",
            headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"},
        )
