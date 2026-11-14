from __future__ import annotations

import logging
import secrets
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.discovery_routes import ALL_DISCOVERY_ROUTERS
from app.api.v1.editorial_routes import router as editorial_router
from app.api.v1.media_routes import router as media_router
from app.api.v1.research_routes import router as research_router
from app.api.v1.routers import ALL_ROUTERS
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.session import new_session

log = logging.getLogger("janaki")


def _error(
    status: int, code: str, message: str, request: Request, details: dict[str, object] | None = None
) -> JSONResponse:
    body: dict[str, object] = {
        "error": {
            "code": code,
            "message": message,
            "request_id": getattr(request.state, "request_id", None),
        }
    }
    if details:
        body["error"]["details"] = details  # type: ignore[index]
    return JSONResponse(status_code=status, content=body)


def create_app() -> FastAPI:
    settings = get_settings()
    docs_enabled = settings.environment != "production"
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Multi-tenant AI-assisted newsroom and CMS. Phases 1-5.",
        docs_url="/api/docs" if docs_enabled else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if docs_enabled else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("x-request-id", "")
        rid = incoming if 0 < len(incoming) <= 64 and incoming.isalnum() else secrets.token_hex(8)
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if not request.url.path.startswith("/api/docs"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; frame-ancestors 'none'"
            )
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError) -> JSONResponse:
        return _error(exc.status_code, exc.code, exc.message, request, exc.details or None)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()]
        return _error(
            422, "validation_error", "Request validation failed.", request, {"fields": fields}
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _error(exc.status_code, "http_error", str(exc.detail), request)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error", extra={"request_id": request.state.request_id})
        return _error(500, "internal_error", "An unexpected error occurred.", request)

    @app.get("/health", tags=["ops"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", tags=["ops"])
    def ready() -> JSONResponse:
        db = new_session()
        try:
            db.execute(text("SELECT 1"))
            return JSONResponse({"status": "ready"})
        except Exception:
            return JSONResponse({"status": "unavailable"}, status_code=503)
        finally:
            db.close()

    for router in [
        *ALL_ROUTERS,
        *ALL_DISCOVERY_ROUTERS,
        research_router,
        editorial_router,
        media_router,
    ]:
        app.include_router(router, prefix="/api/v1")
    return app


app = create_app()
