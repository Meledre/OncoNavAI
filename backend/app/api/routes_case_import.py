from __future__ import annotations

import base64
from typing import Any

from backend.app.exceptions import ValidationError
from backend.app.service import OncoService


def case_import_handler(service: OncoService, role: str, payload: dict[str, Any]) -> dict[str, Any]:
    return service.case_import(role=role, payload=payload)


def case_get_handler(service: OncoService, role: str, case_id: str) -> dict[str, Any]:
    return service.get_case(role=role, case_id=case_id)


def case_import_run_get_handler(service: OncoService, role: str, import_run_id: str) -> dict[str, Any]:
    return service.get_case_import_run(role=role, import_run_id=import_run_id)


def case_import_runs_list_handler(service: OncoService, role: str, limit: int = 20) -> dict[str, Any]:
    runs = service.list_case_import_runs(role=role, limit=limit)
    return {"runs": runs, "count": len(runs), "limit": max(1, min(int(limit), 100))}


def case_import_file_base64_handler(service: OncoService, role: str, payload: dict[str, Any]) -> dict[str, Any]:
    return service.case_import_file_base64(role=role, payload=payload)


def case_import_batch_file_base64_handler(service: OncoService, role: str, payload: dict[str, Any]) -> dict[str, Any]:
    return service.case_import_batch_file_base64(role=role, payload=payload)


try:
    from fastapi import APIRouter, Header, Query, Request
    from fastapi.concurrency import run_in_threadpool

    from backend.app.security.demo_token import ensure_demo_token

    router = APIRouter(prefix="/case")

    @router.post("/import")
    async def case_import_fastapi(
        request: Request,
        x_role: str = Header(default="clinician"),
        x_demo_token: str = Header(default=""),
    ):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        payload = await request.json()
        return await run_in_threadpool(
            case_import_handler,
            service,
            role=x_role,
            payload=payload,
        )

    @router.post("/import-file-base64")
    async def case_import_file_base64_fastapi(
        request: Request,
        x_role: str = Header(default="clinician"),
        x_demo_token: str = Header(default=""),
    ):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        payload = await request.json()

        if not isinstance(payload, dict):
            raise ValidationError("Payload must be an object")
        filename = str(payload.get("filename") or "").strip()
        content_base64 = str(payload.get("content_base64") or "").strip()
        if not filename:
            raise ValidationError("filename is required")
        if not content_base64:
            raise ValidationError("content_base64 is required")
        try:
            # Validate payload shape early and keep original content for service method.
            base64.b64decode(content_base64, validate=True)
        except Exception as exc:  # noqa: BLE001
            raise ValidationError("Invalid content_base64 payload") from exc

        return await run_in_threadpool(
            case_import_file_base64_handler,
            service,
            role=x_role,
            payload=payload,
        )

    @router.post("/import/batch")
    async def case_import_batch_file_base64_fastapi(
        request: Request,
        x_role: str = Header(default="clinician"),
        x_demo_token: str = Header(default=""),
    ):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValidationError("Payload must be an object")
        files = payload.get("files")
        if not isinstance(files, list) or not files:
            raise ValidationError("files is required and must be non-empty array")
        for item in files:
            if not isinstance(item, dict):
                raise ValidationError("Each files entry must be an object")
            filename = str(item.get("filename") or "").strip()
            content_base64 = str(item.get("content_base64") or "").strip()
            if not filename or not content_base64:
                raise ValidationError("Each files entry must include filename and content_base64")
            try:
                base64.b64decode(content_base64, validate=True)
            except Exception as exc:  # noqa: BLE001
                raise ValidationError(f"Invalid content_base64 payload for file: {filename or '<unknown>'}") from exc

        return await run_in_threadpool(
            case_import_batch_file_base64_handler,
            service,
            role=x_role,
            payload=payload,
        )

    @router.get("/import/runs")
    def case_import_runs_list_fastapi(
        limit: int = Query(default=20, ge=1, le=100),
        x_role: str = Header(default="clinician"),
        x_demo_token: str = Header(default=""),
    ):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        return case_import_runs_list_handler(service, role=x_role, limit=limit)

    @router.get("/import/{import_run_id}")
    def case_import_run_get_fastapi(
        import_run_id: str,
        x_role: str = Header(default="clinician"),
        x_demo_token: str = Header(default=""),
    ):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        return case_import_run_get_handler(service, role=x_role, import_run_id=import_run_id)

    @router.get("/{case_id}")
    def case_get_fastapi(case_id: str, x_role: str = Header(default="clinician"), x_demo_token: str = Header(default="")):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        return case_get_handler(service, role=x_role, case_id=case_id)

except ModuleNotFoundError:  # pragma: no cover
    router = None
