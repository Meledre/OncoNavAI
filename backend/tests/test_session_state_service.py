from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.app.config import Settings
from backend.app.exceptions import ValidationError
from backend.app.service import OncoService


def make_settings(root: Path) -> Settings:
    data = root / "data"
    return Settings(
        project_root=root,
        data_dir=data,
        docs_dir=data / "docs",
        reports_dir=data / "reports",
        db_path=data / "oncoai.sqlite3",
        local_core_base_url="http://localhost:8000",
        demo_token="demo-token",
        rate_limit_per_minute=10,
        llm_primary_url="",
        llm_primary_model="gpt-4o-mini",
        llm_primary_api_key="",
        llm_fallback_url="",
        llm_fallback_model="qwen2.5-7b-instruct",
        llm_fallback_api_key="",
        llm_probe_enabled=False,
        rag_engine="basic",
    )


def test_session_revoke_blocks_session_check(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    revoked = service.session_revoke(
        role="clinician",
        payload={
            "scope": "self",
            "reason": "logout",
            "sessions": [
                {
                    "session_id": "sess-1",
                    "user_id": "user:doctor",
                    "role": "clinician",
                    "exp": 4_102_444_800,
                }
            ],
        },
    )
    assert revoked["ok"] is True
    assert revoked["scope"] == "self"
    assert revoked["revoked_session_ids"] == 1

    decision = service.session_check_access(session_id="sess-1", user_id="user:doctor", issued_at=1)
    assert decision["allowed"] is False
    assert decision["reason"] == "session_revoked"


def test_session_force_logout_blocks_older_tokens_only(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    result = service.session_revoke(
        role="admin",
        payload={
            "scope": "user",
            "user_id": "user:clinician",
            "actor_user_id": "user:admin",
            "reason": "security_event",
        },
    )
    forced_after = int(result["forced_logout_after"])
    assert forced_after > 0

    blocked = service.session_check_access(
        session_id="sess-old",
        user_id="user:clinician",
        issued_at=forced_after - 1,
    )
    assert blocked["allowed"] is False
    assert blocked["reason"] == "forced_logout"

    allowed = service.session_check_access(
        session_id="sess-new",
        user_id="user:clinician",
        issued_at=forced_after + 1,
    )
    assert allowed["allowed"] is True
    assert allowed["reason"] == "ok"


def test_session_audit_roundtrip(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    written = service.session_record_audit(
        role="clinician",
        payload={
            "event": "login_success",
            "outcome": "allow",
            "correlation_id": "corr-xyz",
            "role": "clinician",
            "user_id": "user:clinician",
            "session_id": "sess-42",
            "reason": "credentials",
            "path": "/api/session/login",
        },
    )
    assert written["ok"] is True
    assert isinstance(written["event_id"], str)

    audit = service.session_audit(role="admin", limit=10)
    assert audit["count"] >= 1
    assert isinstance(audit["events"], list)
    assert audit["events"][0]["event"] == "login_success"
    assert audit["events"][0]["correlation_id"] == "corr-xyz"
    assert audit["events"][0]["reason_group"] == "auth"


def test_session_idp_replay_reserve_blocks_duplicate_jti(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    payload = {
        "jti_hash": "sha256:test-jti-1",
        "user_id": "idp:clinician",
        "exp": 4_102_444_800,
    }
    first = service.session_reserve_idp_jti(payload=payload)
    second = service.session_reserve_idp_jti(payload=payload)

    assert first["allowed"] is True
    assert first["reason"] == "ok"
    assert second["allowed"] is False
    assert second["reason"] == "idp_token_replay_detected"


def test_session_audit_supports_filters(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    service.session_record_audit(
        role="clinician",
        payload={
            "event": "login_success",
            "outcome": "allow",
            "correlation_id": "corr-allow",
            "user_id": "user:clinician",
            "reason": "idp_mode_hs256",
            "path": "/api/session/login",
        },
    )
    service.session_record_audit(
        role="clinician",
        payload={
            "event": "login_rejected",
            "outcome": "deny",
            "correlation_id": "corr-deny",
            "user_id": "user:clinician",
            "reason": "idp_alg_not_allowed",
            "path": "/api/session/login",
        },
    )
    service.session_record_audit(
        role="clinician",
        payload={
            "event": "session_refresh_rotated",
            "outcome": "info",
            "correlation_id": "corr-token",
            "user_id": "user:clinician",
            "reason": "refresh_rotation",
            "path": "/api/session/me",
        },
    )

    filtered = service.session_audit(
        role="admin",
        limit=20,
        filters={
            "outcome": "deny",
            "correlation_id": "corr-deny",
            "reason": "alg_not_allowed",
            "event": "login_rejected",
            "user_id": "user:clinician",
        },
    )
    assert filtered["count"] == 1
    assert filtered["events"][0]["event"] == "login_rejected"
    assert filtered["events"][0]["correlation_id"] == "corr-deny"
    assert filtered["events"][0]["reason_group"] == "auth"

    token_filtered = service.session_audit(
        role="admin",
        limit=20,
        filters={"reason_group": "token"},
    )
    assert token_filtered["count"] == 1
    assert token_filtered["events"][0]["correlation_id"] == "corr-token"
    assert token_filtered["events"][0]["reason_group"] == "token"


def test_session_audit_supports_cursor_pagination(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    for idx in range(3):
        service.session_record_audit(
            role="clinician",
            payload={
                "event": f"evt_{idx}",
                "outcome": "info",
                "correlation_id": f"corr-{idx}",
                "user_id": "user:clinician",
                "reason": "test",
            },
        )

    page1 = service.session_audit(role="admin", limit=2)
    assert page1["count"] == 2
    assert isinstance(page1.get("next_cursor"), str)
    assert page1["next_cursor"]

    page2 = service.session_audit(role="admin", limit=2, cursor=str(page1["next_cursor"]))
    assert page2["count"] == 1
    assert page2.get("next_cursor") in {"", None}


def test_session_audit_has_query_indexes(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    with service.store.connect() as conn:
        rows = conn.execute("PRAGMA index_list(session_audit_events)").fetchall()
    names = {str(row["name"]) for row in rows}
    expected = {
        "idx_session_audit_created_event",
        "idx_session_audit_outcome_created",
        "idx_session_audit_user_created",
        "idx_session_audit_correlation",
        "idx_session_audit_reason_group_created",
    }
    missing = expected - names
    assert not missing, f"Missing session_audit_events indexes: {sorted(missing)}"


def test_session_audit_purges_old_events_on_write(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    old_created_at = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
    service.store.save_session_audit_event(
        {
            "event_id": "evt-old",
            "event": "legacy_event",
            "outcome": "info",
            "user_id": "user:clinician",
            "reason": "legacy",
        },
        created_at=old_created_at,
    )

    service.session_record_audit(
        role="clinician",
        payload={
            "event": "login_success",
            "outcome": "allow",
            "user_id": "user:clinician",
            "reason": "credentials",
        },
    )
    payload = service.session_audit(role="admin", limit=100)
    event_ids = {str(item.get("event_id") or "") for item in payload["events"]}
    assert "evt-old" not in event_ids


def test_session_audit_supports_time_window_filters(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    now = datetime.now(timezone.utc)
    ts_old = (now - timedelta(minutes=3)).isoformat()
    ts_mid = (now - timedelta(minutes=2)).isoformat()
    ts_new = (now - timedelta(minutes=1)).isoformat()

    service.store.save_session_audit_event(
        {
            "event_id": "evt-time-old",
            "event": "evt_time_old",
            "outcome": "info",
            "user_id": "user:clinician",
            "reason": "time_old",
        },
        created_at=ts_old,
    )
    service.store.save_session_audit_event(
        {
            "event_id": "evt-time-mid",
            "event": "evt_time_mid",
            "outcome": "info",
            "user_id": "user:clinician",
            "reason": "time_mid",
        },
        created_at=ts_mid,
    )
    service.store.save_session_audit_event(
        {
            "event_id": "evt-time-new",
            "event": "evt_time_new",
            "outcome": "info",
            "user_id": "user:clinician",
            "reason": "time_new",
        },
        created_at=ts_new,
    )

    filtered = service.session_audit(
        role="admin",
        limit=20,
        filters={"from_ts": ts_mid, "to_ts": ts_mid},
    )
    event_ids = [str(item.get("event_id") or "") for item in filtered["events"]]
    assert event_ids == ["evt-time-mid"]


def test_session_audit_rejects_invalid_from_ts(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    with pytest.raises(ValidationError):
        service.session_audit(
            role="admin",
            limit=20,
            filters={"from_ts": "not-a-timestamp"},
        )


def test_session_audit_rejects_inverted_time_window(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    with pytest.raises(ValidationError):
        service.session_audit(
            role="admin",
            limit=20,
            filters={
                "from_ts": "2026-02-19T23:59:59+00:00",
                "to_ts": "2026-02-19T00:00:00+00:00",
            },
        )


def test_session_audit_summary_returns_outcomes_and_top_reasons(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    service.session_record_audit(
        role="clinician",
        payload={
            "event": "login_rejected",
            "outcome": "deny",
            "correlation_id": "corr-1",
            "user_id": "user:a",
            "reason": "idp_alg_not_allowed",
            "path": "/api/session/login",
        },
    )
    service.session_record_audit(
        role="clinician",
        payload={
            "event": "login_rejected",
            "outcome": "deny",
            "correlation_id": "corr-2",
            "user_id": "user:b",
            "reason": "idp_alg_not_allowed",
            "path": "/api/session/login",
        },
    )
    service.session_record_audit(
        role="clinician",
        payload={
            "event": "login_success",
            "outcome": "allow",
            "correlation_id": "corr-3",
            "user_id": "user:c",
            "reason": "credentials",
            "path": "/api/session/login",
        },
    )

    summary = service.session_audit_summary(role="admin", window_hours=24)
    assert int(summary.get("window_hours") or 0) == 24
    assert int(summary.get("total_events") or 0) >= 3

    outcomes = summary.get("outcome_counts") or {}
    assert int(outcomes.get("deny") or 0) >= 2
    assert int(outcomes.get("allow") or 0) >= 1

    top_reasons = summary.get("top_reasons") or []
    assert isinstance(top_reasons, list)
    assert any(str(item.get("reason") or "") == "idp_alg_not_allowed" for item in top_reasons)
    assert str(summary.get("incident_level") or "") in {"none", "low", "medium", "high"}
    assert isinstance(summary.get("alerts"), list)
    incident_signals = summary.get("incident_signals") or {}
    assert "deny_rate" in incident_signals
    assert "error_count" in incident_signals
    assert "replay_detected_count" in incident_signals
    assert "config_error_count" in incident_signals


def test_session_audit_summary_flags_incidents_when_thresholds_exceeded(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))

    for idx in range(8):
        service.session_record_audit(
            role="clinician",
            payload={
                "event": "login_rejected",
                "outcome": "deny",
                "correlation_id": f"corr-deny-{idx}",
                "user_id": "user:risk",
                "reason": "idp_token_replay_detected",
                "path": "/api/session/login",
            },
        )
    for idx in range(5):
        service.session_record_audit(
            role="clinician",
            payload={
                "event": "login_error",
                "outcome": "error",
                "correlation_id": f"corr-err-{idx}",
                "user_id": "user:risk",
                "reason": "idp_config_incomplete",
                "path": "/api/session/login",
            },
        )

    summary = service.session_audit_summary(role="admin", window_hours=24)
    assert str(summary.get("incident_level") or "") == "high"
    assert int(summary.get("incident_score") or 0) >= 75

    alerts = summary.get("alerts") or []
    assert isinstance(alerts, list)
    codes = {str(item.get("code") or "") for item in alerts if isinstance(item, dict)}
    assert "deny_rate_exceeded" in codes
    assert "error_count_exceeded" in codes
    assert "replay_detected_count_exceeded" in codes
    assert "config_error_count_exceeded" in codes

    signals = summary.get("incident_signals") or {}
    assert float(signals.get("deny_rate") or 0.0) > 0.0
    assert int(signals.get("error_count") or 0) >= 5
    assert int(signals.get("replay_detected_count") or 0) >= 8
    assert int(signals.get("config_error_count") or 0) >= 4
