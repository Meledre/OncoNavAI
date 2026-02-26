from __future__ import annotations

from backend.app.api import (
    routes_admin,
    routes_analyze,
    routes_case_import,
    routes_health,
    routes_patient,
    routes_report,
    routes_session,
)
from backend.app.config import load_settings
from backend.app.exceptions import (
    AuthorizationError,
    NotFoundError,
    RateLimitError,
    ValidationError,
)
from backend.app.service import OncoService

_settings = load_settings()
_service = OncoService(_settings)


def get_service() -> OncoService:
    return _service


try:
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse

    app = FastAPI(title="OncoAI", version="0.1.0")

    if routes_health.router is not None:
        app.include_router(routes_health.router)
    if routes_analyze.router is not None:
        app.include_router(routes_analyze.router)
    if routes_admin.router is not None:
        app.include_router(routes_admin.router)
    if routes_case_import.router is not None:
        app.include_router(routes_case_import.router)
    if routes_patient.router is not None:
        app.include_router(routes_patient.router)
    if routes_session.router is not None:
        app.include_router(routes_session.router)
    if routes_report.router is not None:
        app.include_router(routes_report.router)

    @app.exception_handler(ValidationError)
    async def validation_error_handler(_: Request, exc: ValidationError):
        return JSONResponse(status_code=400, content={"error": str(exc)})

    @app.exception_handler(AuthorizationError)
    async def authorization_error_handler(_: Request, exc: AuthorizationError):
        return JSONResponse(status_code=403, content={"error": str(exc)})

    @app.exception_handler(RateLimitError)
    async def rate_limit_error_handler(_: Request, exc: RateLimitError):
        return JSONResponse(status_code=429, content={"error": str(exc)})

    @app.exception_handler(NotFoundError)
    async def not_found_error_handler(_: Request, exc: NotFoundError):
        return JSONResponse(status_code=404, content={"error": str(exc)})

except ModuleNotFoundError:  # pragma: no cover
    app = None
