from __future__ import annotations

from typing import Any

from backend.app.service import OncoService


def session_check_handler(service: OncoService, payload: dict[str, Any]) -> dict[str, Any]:
    return service.session_check_access(
        session_id=str(payload.get("session_id") or ""),
        user_id=str(payload.get("user_id") or ""),
        issued_at=int(payload.get("issued_at") or 0),
    )


def session_revoke_handler(service: OncoService, role: str, payload: dict[str, Any]) -> dict[str, Any]:
    return service.session_revoke(role=role, payload=payload)


def session_audit_write_handler(service: OncoService, role: str, payload: dict[str, Any]) -> dict[str, Any]:
    return service.session_record_audit(role=role, payload=payload)


def session_audit_read_handler(
    service: OncoService,
    role: str,
    limit: int = 50,
    cursor: str = "",
    filters: dict[str, str] | None = None,
) -> dict[str, Any]:
    return service.session_audit(role=role, limit=limit, filters=filters or {}, cursor=cursor)


def session_audit_summary_handler(
    service: OncoService,
    role: str,
    window_hours: int = 24,
    from_ts: str = "",
    to_ts: str = "",
) -> dict[str, Any]:
    return service.session_audit_summary(
        role=role,
        window_hours=window_hours,
        from_ts=from_ts,
        to_ts=to_ts,
    )


def session_idp_replay_reserve_handler(service: OncoService, payload: dict[str, Any]) -> dict[str, Any]:
    return service.session_reserve_idp_jti(payload=payload)


try:
    from fastapi import APIRouter, Header, Query, Request
    from fastapi.concurrency import run_in_threadpool

    from backend.app.security.demo_token import ensure_demo_token

    router = APIRouter(prefix="/session")

    @router.post("/check")
    async def session_check_fastapi(request: Request, x_demo_token: str = Header(default="")):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        payload = await request.json()
        return await run_in_threadpool(session_check_handler, service, payload=payload)

    @router.post("/revoke")
    async def session_revoke_fastapi(
        request: Request,
        x_role: str = Header(default="clinician"),
        x_demo_token: str = Header(default=""),
    ):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        payload = await request.json()
        return await run_in_threadpool(
            session_revoke_handler,
            service,
            role=x_role,
            payload=payload,
        )

    @router.post("/audit")
    async def session_audit_write_fastapi(
        request: Request,
        x_role: str = Header(default="clinician"),
        x_demo_token: str = Header(default=""),
    ):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        payload = await request.json()
        return await run_in_threadpool(
            session_audit_write_handler,
            service,
            role=x_role,
            payload=payload,
        )

    @router.get("/audit")
    def session_audit_read_fastapi(
        limit: int = Query(default=50, ge=1, le=500),
        cursor: str = Query(default=""),
        outcome: str = Query(default=""),
        reason_group: str = Query(default=""),
        event: str = Query(default=""),
        reason: str = Query(default=""),
        user_id: str = Query(default=""),
        correlation_id: str = Query(default=""),
        from_ts: str = Query(default=""),
        to_ts: str = Query(default=""),
        x_role: str = Header(default="clinician"),
        x_demo_token: str = Header(default=""),
    ):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        return session_audit_read_handler(
            service,
            role=x_role,
            limit=limit,
            cursor=cursor,
            filters={
                "outcome": outcome,
                "reason_group": reason_group,
                "event": event,
                "reason": reason,
                "user_id": user_id,
                "correlation_id": correlation_id,
                "from_ts": from_ts,
                "to_ts": to_ts,
            },
        )

    @router.get("/audit/summary")
    def session_audit_summary_fastapi(
        window_hours: int = Query(default=24, ge=1, le=168),
        from_ts: str = Query(default=""),
        to_ts: str = Query(default=""),
        x_role: str = Header(default="clinician"),
        x_demo_token: str = Header(default=""),
    ):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        return session_audit_summary_handler(
            service,
            role=x_role,
            window_hours=window_hours,
            from_ts=from_ts,
            to_ts=to_ts,
        )

    @router.post("/idp/replay/reserve")
    async def session_idp_replay_reserve_fastapi(request: Request, x_demo_token: str = Header(default="")):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        payload = await request.json()
        return await run_in_threadpool(session_idp_replay_reserve_handler, service, payload=payload)

except ModuleNotFoundError:  # pragma: no cover
    router = None
