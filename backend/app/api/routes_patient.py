from __future__ import annotations

from typing import Any

from backend.app.service import OncoService


def patient_analyze_file_base64_handler(service: OncoService, role: str, payload: dict[str, Any]) -> dict[str, Any]:
    return service.patient_analyze_file_base64(role=role, payload=payload)


try:
    from fastapi import APIRouter, Header, Request
    from fastapi.concurrency import run_in_threadpool

    from backend.app.security.demo_token import ensure_demo_token

    router = APIRouter(prefix="/patient")

    @router.post("/analyze-file-base64")
    async def patient_analyze_file_base64_fastapi(
        request: Request,
        x_role: str = Header(default="patient"),
        x_demo_token: str = Header(default=""),
    ):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        payload = await request.json()
        return await run_in_threadpool(
            patient_analyze_file_base64_handler,
            service,
            role=x_role,
            payload=payload,
        )

except ModuleNotFoundError:  # pragma: no cover
    router = None
