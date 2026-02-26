from __future__ import annotations

import http.client
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any


def test_e2e_smoke_supports_case_flow_mode() -> None:
    script = Path(__file__).resolve().parents[2] / "scripts" / "e2e_smoke.py"
    text = script.read_text()
    assert '--case-flow' in text
    assert '--gastric-flow' in text
    assert '--auth-mode' in text
    assert '/api/case/import' in text
    assert '/api/case/import/runs' in text
    assert '/api/case/import/' in text
    assert '/api/case/' in text
    assert 'case_id' in text
    assert "ONCO_SMOKE_" in text
    assert "_USERNAME" in text
    assert "_PASSWORD" in text
    assert "ONCO_SMOKE_IDP_SECRET" in text
    assert "SESSION_IDP_HS256_SECRET" in text
    assert "ONCO_SMOKE_IDP_ADMIN_TOKEN" in text
    assert "ONCO_SMOKE_IDP_CLINICIAN_TOKEN" in text
    assert "_build_hs256_idp_token" in text
    assert "_require_idp_claim_checks" in text
    assert "idp_user_id_missing" in text
    assert "idp_user_id_invalid_format" in text
    assert "idp_claims_missing_identity_or_role_not_allowed" in text
    assert "idp_issuer_mismatch" in text
    assert "idp_audience_mismatch" in text
    assert "idp_token_expired" in text
    assert "idp_token_not_yet_valid" in text
    assert "idp_iat_in_future" in text
    assert "idp_jti_missing" in text
    assert "idp_token_replay_detected" in text
    assert "idp_invalid_jwt_format" in text
    assert "idp_alg_not_allowed" in text
    assert "idp_signature_invalid_hs256" in text
    assert "idp_signature_invalid_rs256" in text
    assert "idp_mode_external_auth" in text
    assert "idp login endpoint contract check" in text
    assert "idp token-missing contract check" in text
    assert "BFF_RATE_LIMITED" in text
    assert "login_rate_limited" in text
    assert "retry-after" in text
    assert "ONCO_SMOKE_REQUIRE_IDP_NEGATIVE" in text
    assert "ONCO_SMOKE_IDP_NEG_TOKEN_MISSING_USER_ID" in text
    assert "ONCO_SMOKE_IDP_NEG_TOKEN_INVALID_USER_ID" in text
    assert "ONCO_SMOKE_IDP_NEG_TOKEN_INVALID_ROLE" in text
    assert "ONCO_SMOKE_IDP_NEG_TOKEN_ISSUER_MISMATCH" in text
    assert "ONCO_SMOKE_IDP_NEG_TOKEN_AUDIENCE_MISMATCH" in text
    assert "ONCO_SMOKE_IDP_NEG_TOKEN_EXPIRED" in text
    assert "ONCO_SMOKE_IDP_NEG_TOKEN_NOT_YET_VALID" in text
    assert "ONCO_SMOKE_IDP_NEG_TOKEN_IAT_IN_FUTURE" in text
    assert "ONCO_SMOKE_IDP_NEG_TOKEN_MISSING_JTI" in text
    assert "ONCO_SMOKE_IDP_NEG_TOKEN_REPLAY" in text
    assert "ONCO_SMOKE_IDP_NEG_TOKEN_MALFORMED" in text
    assert "ONCO_SMOKE_IDP_NEG_TOKEN_ALG_NOT_ALLOWED" in text
    assert "ONCO_SMOKE_IDP_NEG_TOKEN_INVALID_SIGNATURE" in text
    assert '"jti"' in text
    assert "/api/session/audit/export" in text
    assert "/api/session/me" in text
    assert "format=json" in text
    assert "format=csv" in text
    assert "max_events=1" in text
    assert "max_events=abc" in text
    assert "max_pages=0" in text
    assert "limit=-1" in text
    assert "BFF_BAD_REQUEST" in text
    assert "error_code" in text
    assert "BFF_AUTH_REQUIRED" in text
    assert "session me auth-required check failed" in text
    assert "session revoke auth-required check failed" in text
    assert "session me auth-required payload must include reason=auth_required" in text
    assert "session revoke auth-required payload must include reason=auth_required" in text
    assert "session revoke admin-role check failed" in text
    assert "session revoke missing-user-id check failed" in text
    assert "payload/header correlation mismatch" in text
    assert "x-correlation-id" in text
    assert "correlation_id" in text
    assert "csrf check failed" in text
    assert "csrf_origin_mismatch" in text
    assert "ONCO_SMOKE_CHECK_SESSION_CSRF" in text
    assert "/api/session/audit/summary" in text
    assert "session_audit_summary_total_events" in text
    assert "incident_level" in text
    assert "incident_score" in text
    assert "incident_signals" in text
    assert "session_audit_summary_alerts_count" in text
    assert "text/csv" in text
    assert "audit_export_json_events" in text
    assert "x-onco-export-truncated" in text
    assert "x-onco-export-truncated-reason" in text
    assert "/api/session/revoke" in text
    assert "=smoke_csv_formula_user" in text
    assert "spreadsheet-formula guard prefix" in text
    assert "audit_export_truncated_events" in text
    assert "_request_json_with_role_retry" in text
    assert "_http_call_with_role_retry" in text
    assert "_invalidate_role_cookie" in text
    assert "ONCOAI_GASTRIC_PACK_DIR" in text
    assert "analyze_next_steps_case_pdf_stomach_case_id_minzdrav.json" in text or "sources_used" in text
    assert "--multi-onco-flow" in text
    assert "--routing-baseline-candidates" in text
    assert "--min-routing-reduction" in text
    assert "--require-vector-backend" in text
    assert "--require-embedding-backend" in text
    assert "--require-reranker-backend" in text
    assert "--require-report-generation-path" in text
    assert "--pdf-page-flow" in text
    assert "--skip-pdf-page-flow" in text
    assert "pdf page-flow" in text
    assert "ONCO_SMOKE_HTTP_TIMEOUT_SEC" in text
    assert "ONCO_SMOKE_ANALYZE_HTTP_TIMEOUT_SEC" in text
    assert "routing_meta" in text
    assert "routing_reduction_ratio" in text
    assert "routing_meta_baseline_candidate_chunks" in text
    assert "gastric flow expected evidence from both sources" in text
    assert "multi-onco flow expected at least one citation" in text
    assert "patient endpoint leaked doctor_report" in text
    assert "/api/admin/docs/" in text
    assert "/rechunk" in text
    assert "/approve" in text
    assert "/index" in text
    assert "ONCO_SMOKE_EXERCISE_ADMIN_RELEASE_WORKFLOW" in text


def _load_e2e_smoke_module() -> ModuleType:
    script = Path(__file__).resolve().parents[2] / "scripts" / "e2e_smoke.py"
    spec = importlib.util.spec_from_file_location("onco_e2e_smoke_test_module", script)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load scripts/e2e_smoke.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_multi_onco_flow_uploads_only_selected_case_docs(monkeypatch: Any) -> None:
    module = _load_e2e_smoke_module()
    uploaded_doc_ids: list[str] = []

    def _fake_upload(
        _base_url: str,
        payload: dict,
        *,
        payload_path: Path,
        action_label: str = "upload",
    ) -> None:
        _ = payload_path
        _ = action_label
        uploaded_doc_ids.append(str(payload.get("doc_id") or ""))

    def _fake_request_json(*, method: str, url: str, headers: dict | None = None, payload: dict | None = None) -> tuple[int, dict]:
        _ = method
        _ = headers
        _ = payload
        if url.endswith("/api/case/import-file"):
            return 200, {"case_id": "case-c16", "import_run_id": "import-c16"}
        if url.endswith("/api/analyze"):
            return 200, {
                "doctor_report": {
                    "issues": [{"issue_id": "i1", "citation_ids": ["c1", "c2"]}],
                    "citations": [
                        {"citation_id": "c1", "source_id": "minzdrav"},
                        {"citation_id": "c2", "source_id": "russco"},
                    ],
                },
                "patient_explain": {"sources_used": ["minzdrav", "russco"]},
                "run_meta": {
                    "routing_meta": {
                        "resolved_cancer_type": "gastric_cancer",
                        "match_strategy": "icd10_prefix",
                    }
                },
            }
        if url.endswith("/api/patient/analyze"):
            return 200, {
                "patient_explain": {"summary": "ok"},
                "run_meta": {"routing_meta": {"resolved_cancer_type": "gastric_cancer"}},
            }
        raise AssertionError(f"unexpected URL in smoke test stub: {url}")

    monkeypatch.setattr(module, "_upload_doc_from_payload", _fake_upload)
    monkeypatch.setattr(module, "_run_admin_doc_release_workflow", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "_request_json", _fake_request_json)
    monkeypatch.setattr(module, "_role_headers", lambda role, base_url, extra=None: {})
    monkeypatch.setattr(module, "_collect_pack_citation_metrics", lambda analyze_payload: (1, ["minzdrav", "russco"], 1))

    result = module._run_multi_onco_flow(
        "http://localhost:3000",
        max_attempts=1,
        min_routing_reduction=0.0,
        selected_cases=["C16"],
    )

    assert result["cases"][0]["label"] == "C16"
    assert uploaded_doc_ids
    assert all("c16_" in doc_id for doc_id in uploaded_doc_ids)
    assert not any(("c34_" in doc_id or "c50_" in doc_id) for doc_id in uploaded_doc_ids)


def test_poll_reindex_uses_extended_start_timeout(monkeypatch: Any) -> None:
    module = _load_e2e_smoke_module()
    calls: list[dict[str, Any]] = []

    def _fake_request_json(
        *,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        payload: dict | None = None,
        timeout: int | None = None,
    ) -> tuple[int, dict]:
        _ = headers
        _ = payload
        calls.append({"method": method, "url": url, "timeout": timeout})
        if method == "POST" and url.endswith("/api/admin/reindex"):
            return 200, {"job_id": "job-1"}
        if method == "GET" and url.endswith("/api/admin/reindex/job-1"):
            return 200, {"status": "done"}
        raise AssertionError(f"unexpected call in _poll_reindex test: method={method} url={url}")

    monkeypatch.setattr(module, "_request_json", _fake_request_json)
    monkeypatch.setattr(module, "_role_headers", lambda role, base_url, extra=None: {})

    payload = module._poll_reindex("http://localhost:3000", max_attempts=1)

    assert payload["status"] == "done"
    assert len(calls) >= 2
    assert calls[0]["method"] == "POST"
    assert calls[0]["timeout"] == max(module.DEFAULT_HTTP_TIMEOUT_SEC, 600)


def test_poll_reindex_retries_start_on_timeout(monkeypatch: Any) -> None:
    module = _load_e2e_smoke_module()
    calls: list[dict[str, Any]] = []
    post_attempts = {"count": 0}

    def _fake_request_json(
        *,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        payload: dict | None = None,
        timeout: int | None = None,
    ) -> tuple[int, dict]:
        _ = headers
        _ = payload
        calls.append({"method": method, "url": url, "timeout": timeout})
        if method == "POST" and url.endswith("/api/admin/reindex"):
            post_attempts["count"] += 1
            if post_attempts["count"] == 1:
                raise TimeoutError("timed out")
            return 200, {"job_id": "job-2"}
        if method == "GET" and url.endswith("/api/admin/reindex/job-2"):
            return 200, {"status": "done"}
        raise AssertionError(f"unexpected call in _poll_reindex timeout-retry test: method={method} url={url}")

    monkeypatch.setattr(module, "_request_json", _fake_request_json)
    monkeypatch.setattr(module, "_role_headers", lambda role, base_url, extra=None: {})

    payload = module._poll_reindex("http://localhost:3000", max_attempts=1)

    assert payload["status"] == "done"
    assert post_attempts["count"] == 2


def test_pdf_page_flow_validates_doctor_and_patient_contracts(monkeypatch: Any) -> None:
    module = _load_e2e_smoke_module()

    monkeypatch.setattr(
        module,
        "_pdf_flow_input",
        lambda pack_dir, case_file="": ("sample.pdf", "cGRm", "application/pdf"),
    )

    def _fake_request_json_with_role_retry(
        *,
        method: str,
        url: str,
        base_url: str,
        role: str,
        payload: dict | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[int, dict]:
        _ = method
        _ = base_url
        _ = role
        _ = payload
        _ = extra_headers
        if url.endswith("/api/case/import-file"):
            return 200, {"case_id": "case-pdf", "import_run_id": "run-pdf", "status": "SUCCESS"}
        if url.endswith("/api/analyze"):
            return 200, {
                "doctor_report": {
                    "issues": [{"issue_id": "i1", "citation_ids": ["c1", "c2"]}],
                    "citations": [
                        {"citation_id": "c1", "source_id": "minzdrav"},
                        {"citation_id": "c2", "source_id": "russco"},
                    ],
                },
                "patient_explain": {"summary": "patient preview"},
                "run_meta": {"routing_meta": {"match_strategy": "icd10_prefix", "resolved_cancer_type": "gastric_cancer"}},
            }
        if url.endswith("/api/patient/analyze"):
            return 200, {
                "case_id": "patient-case",
                "import_run_id": "patient-run",
                "patient_explain": {"summary": "patient summary"},
                "run_meta": {"routing_meta": {"match_strategy": "icd10_prefix", "resolved_cancer_type": "gastric_cancer"}},
            }
        raise AssertionError(f"unexpected URL in pdf flow test: {url}")

    monkeypatch.setattr(module, "_request_json_with_role_retry", _fake_request_json_with_role_retry)

    result = module._run_pdf_page_flow("http://localhost:3000", pack_dir="/tmp/pack")

    assert result["doctor_case_id"] == "case-pdf"
    assert result["doctor_import_run_id"] == "run-pdf"
    assert result["doctor_issues_count"] >= 1
    assert result["doctor_citations_count"] >= 1
    assert set(result["doctor_sources_used"]) == {"minzdrav", "russco"}
    assert result["patient_summary_present"] is True


def test_poll_reindex_retries_start_on_remote_disconnect(monkeypatch: Any) -> None:
    module = _load_e2e_smoke_module()
    post_attempts = {"count": 0}

    def _fake_request_json(
        *,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        payload: dict | None = None,
        timeout: int | None = None,
    ) -> tuple[int, dict]:
        _ = headers
        _ = payload
        _ = timeout
        if method == "POST" and url.endswith("/api/admin/reindex"):
            post_attempts["count"] += 1
            if post_attempts["count"] == 1:
                raise http.client.RemoteDisconnected("Remote end closed connection without response")
            return 200, {"job_id": "job-rd"}
        if method == "GET" and url.endswith("/api/admin/reindex/job-rd"):
            return 200, {"status": "done"}
        raise AssertionError(f"unexpected call in _poll_reindex remote-disconnect test: method={method} url={url}")

    monkeypatch.setattr(module, "_request_json", _fake_request_json)
    monkeypatch.setattr(module, "_role_headers", lambda role, base_url, extra=None: {})

    payload = module._poll_reindex("http://localhost:3000", max_attempts=1)

    assert payload["status"] == "done"
    assert post_attempts["count"] == 2


def test_request_json_applies_extended_timeout_for_analyze_routes(monkeypatch: Any) -> None:
    module = _load_e2e_smoke_module()
    observed_timeouts: list[int] = []

    def _fake_http_call(
        *,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        timeout: int = 0,
    ) -> tuple[int, str]:
        _ = method
        _ = url
        _ = headers
        _ = body
        observed_timeouts.append(int(timeout))
        return 200, "{}"

    monkeypatch.setattr(module, "_http_call", _fake_http_call)

    status_1, payload_1 = module._request_json(
        method="POST",
        url="http://localhost:3000/api/analyze",
        payload={"request_id": "req-1"},
    )
    status_2, payload_2 = module._request_json(
        method="POST",
        url="http://localhost:3000/api/patient/analyze",
        payload={"request_id": "req-2"},
    )

    assert status_1 == 200
    assert status_2 == 200
    assert payload_1 == {}
    assert payload_2 == {}
    assert observed_timeouts == [
        module.DEFAULT_ANALYZE_HTTP_TIMEOUT_SEC,
        module.DEFAULT_ANALYZE_HTTP_TIMEOUT_SEC,
    ]


def test_request_json_keeps_default_timeout_for_non_analyze_routes(monkeypatch: Any) -> None:
    module = _load_e2e_smoke_module()
    observed_timeout = {"value": 0}

    def _fake_http_call(
        *,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        timeout: int = 0,
    ) -> tuple[int, str]:
        _ = method
        _ = url
        _ = headers
        _ = body
        observed_timeout["value"] = int(timeout)
        return 200, "{}"

    monkeypatch.setattr(module, "_http_call", _fake_http_call)

    status, payload = module._request_json(
        method="GET",
        url="http://localhost:3000/api/admin/docs",
    )

    assert status == 200
    assert payload == {}
    assert observed_timeout["value"] == module.DEFAULT_HTTP_TIMEOUT_SEC


def test_collect_pack_citation_metrics_supports_legacy_issue_evidence_shape() -> None:
    module = _load_e2e_smoke_module()
    analyze_payload = {
        "doctor_report": {
            "issues": [
                {
                    "issue_id": "ISS-1",
                    "severity": "important",
                    "evidence": [
                        {
                            "source_set": "mvp_guidelines_ru_2025",
                            "chunk_id": "chunk-1",
                        }
                    ],
                }
            ],
            "citations": [],
        },
        "patient_explain": {"sources_used": []},
    }

    citation_count, sources_used, issues_count = module._collect_pack_citation_metrics(analyze_payload)

    assert issues_count == 1
    assert citation_count == 1
    assert sources_used == ["mvp_guidelines_ru_2025"]


def test_collect_pack_citation_metrics_includes_routing_meta_sources() -> None:
    module = _load_e2e_smoke_module()
    analyze_payload = {
        "doctor_report": {"issues": [], "citations": []},
        "run_meta": {"routing_meta": {"source_ids": ["minzdrav", "russco"]}},
        "patient_explain": {"sources_used": []},
    }

    citation_count, sources_used, issues_count = module._collect_pack_citation_metrics(analyze_payload)

    assert issues_count == 0
    assert citation_count == 0
    assert sources_used == ["minzdrav", "russco"]
