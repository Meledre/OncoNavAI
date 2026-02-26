from __future__ import annotations

from typing import Any

from backend.app.service import OncoService


def analyze_handler(service: OncoService, payload: dict[str, Any], role: str, client_id: str) -> dict[str, Any]:
    return service.analyze(payload=payload, role=role, client_id=client_id)


try:
    from fastapi import APIRouter, Header, Request
    from fastapi.concurrency import run_in_threadpool

    from backend.app.security.demo_token import ensure_demo_token

    router = APIRouter()

    @router.post("/analyze")
    async def analyze_fastapi(
        request: Request,
        x_role: str = Header(default="clinician"),
        x_client_id: str = Header(default="anonymous"),
        x_demo_token: str = Header(default=""),
    ):
        payload = await request.json()
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        return await run_in_threadpool(
            analyze_handler,
            service,
            payload=payload,
            role=x_role,
            client_id=x_client_id,
        )

except ModuleNotFoundError:  # pragma: no cover
    router = None
