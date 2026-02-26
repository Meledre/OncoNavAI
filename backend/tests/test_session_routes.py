from __future__ import annotations

from backend.app.api.routes_session import (
    session_audit_read_handler,
    session_audit_summary_handler,
    session_audit_write_handler,
    session_check_handler,
    session_idp_replay_reserve_handler,
    session_revoke_handler,
)


class _FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, object]] = []

    def session_check_access(self, *, session_id: str, user_id: str, issued_at: int) -> dict[str, object]:
        self.calls.append(("session_check_access", session_id, user_id))
        return {"allowed": True, "reason": "ok", "issued_at": issued_at}

    def session_revoke(self, *, role: str, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(("session_revoke", role, payload))
        return {"ok": True, "scope": payload.get("scope", "self")}

    def session_record_audit(self, *, role: str, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(("session_record_audit", role, payload))
        return {"ok": True, "event_id": "evt-1"}

    def session_audit(self, *, role: str, limit: int, filters: dict[str, str], cursor: str = "") -> dict[str, object]:
        self.calls.append(("session_audit", role, limit, filters, cursor))
        return {"count": 0, "limit": limit, "events": [], "next_cursor": ""}

    def session_audit_summary(
        self,
        *,
        role: str,
        window_hours: int,
        from_ts: str = "",
        to_ts: str = "",
    ) -> dict[str, object]:
        self.calls.append(("session_audit_summary", role, window_hours, from_ts, to_ts))
        return {"window_hours": window_hours, "total_events": 2}

    def session_reserve_idp_jti(self, *, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(("session_reserve_idp_jti", payload))
        return {"allowed": True, "reason": "ok"}


def test_session_routes_delegate_to_service() -> None:
    service = _FakeService()

    check = session_check_handler(
        service,
        payload={"session_id": "sess-1", "user_id": "user-1", "issued_at": 123},
    )
    revoke = session_revoke_handler(
        service,
        role="admin",
        payload={"scope": "user", "user_id": "user-1"},
    )
    write = session_audit_write_handler(
        service,
        role="clinician",
        payload={"event": "login_success", "outcome": "allow", "correlation_id": "corr-1"},
    )
    replay = session_idp_replay_reserve_handler(
        service,
        payload={"jti_hash": "sha256:test-jti-1", "exp": 4_102_444_800, "user_id": "idp:clinician"},
    )
    summary = session_audit_summary_handler(
        service,
        role="admin",
        window_hours=24,
        from_ts="2026-02-19T00:00:00+00:00",
        to_ts="2026-02-19T23:59:59+00:00",
    )
    read = session_audit_read_handler(
        service,
        role="admin",
        limit=25,
        cursor="cursor-1",
        filters={
            "outcome": "deny",
            "correlation_id": "corr-1",
            "reason": "idp",
            "event": "login_rejected",
            "user_id": "u-1",
            "reason_group": "auth",
            "from_ts": "2026-02-19T00:00:00+00:00",
            "to_ts": "2026-02-19T23:59:59+00:00",
        },
    )

    assert check["allowed"] is True
    assert revoke["ok"] is True
    assert write["event_id"] == "evt-1"
    assert replay["allowed"] is True
    assert summary["total_events"] == 2
    assert read["limit"] == 25

    assert ("session_check_access", "sess-1", "user-1") in service.calls
    assert ("session_revoke", "admin", {"scope": "user", "user_id": "user-1"}) in service.calls
    assert (
        "session_record_audit",
        "clinician",
        {"event": "login_success", "outcome": "allow", "correlation_id": "corr-1"},
    ) in service.calls
    assert (
        "session_reserve_idp_jti",
        {"jti_hash": "sha256:test-jti-1", "exp": 4_102_444_800, "user_id": "idp:clinician"},
    ) in service.calls
    assert (
        "session_audit_summary",
        "admin",
        24,
        "2026-02-19T00:00:00+00:00",
        "2026-02-19T23:59:59+00:00",
    ) in service.calls
    assert (
        "session_audit",
        "admin",
        25,
        {
            "outcome": "deny",
            "correlation_id": "corr-1",
            "reason": "idp",
            "event": "login_rejected",
            "user_id": "u-1",
            "reason_group": "auth",
            "from_ts": "2026-02-19T00:00:00+00:00",
            "to_ts": "2026-02-19T23:59:59+00:00",
        },
        "cursor-1",
    ) in service.calls
