from __future__ import annotations

from pathlib import Path


def test_quality_gates_workflow_has_required_e2e_smoke_gate() -> None:
    workflow = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "quality-gates.yml"
    text = workflow.read_text()

    assert "e2e-smoke-gate:" in text
    assert "Start backend + frontend (demo mode)" in text
    assert "python3 scripts/e2e_smoke.py" in text
    assert "--schema-version 0.2" in text
    assert "--auth-mode demo" in text
    assert "ONCO_SMOKE_CHECK_LOGIN_RATE_LIMIT: \"true\"" in text
    assert "ONCO_SMOKE_LOGIN_RATE_LIMIT_PROBE_ATTEMPTS: \"120\"" in text
    assert "ONCO_SMOKE_CHECK_SESSION_CSRF: \"true\"" in text
    assert "E2E case-flow gate" in text
    assert "--case-flow" in text
    assert "Session incident gate (demo)" in text
    assert "scripts/session_incident_gate.py" in text
    assert "--fail-on-level high" in text
    assert "--min-import-data-mode-coverage 1.0" in text
    assert "--min-recall-like 0.90" in text
    assert "--min-precision 0.80" in text
    assert "--min-f1 0.85" in text
    assert "--min-throughput-cases-per-hour 20" in text
    assert "--min-top3-acceptance-rate 0.90" in text
    assert "--min-sus-score 80" in text
    assert "--top3-scorecard reports/review/top3_acceptance_scorecard.json" in text
    assert "--sus-input reports/review/sus_scorecard.json" in text
    assert "--max-rewrite-required-rate 0.0" in text


def test_quality_gates_workflow_has_idp_case_flow_compat_steps() -> None:
    workflow = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "quality-gates.yml"
    text = workflow.read_text()

    assert "idp-smoke-compat:" in text
    assert "IdP case-flow smoke (token exchange)" in text
    assert "idp-rs256-smoke-compat:" in text
    assert "IdP case-flow smoke (RS256/JWKS token exchange)" in text
    assert "SMOKE_IDP_NEG_TOKEN_MISSING_USER_ID" in text
    assert "SMOKE_IDP_NEG_TOKEN_INVALID_USER_ID" in text
    assert "SMOKE_IDP_NEG_TOKEN_INVALID_ROLE" in text
    assert "SMOKE_IDP_NEG_TOKEN_ISSUER_MISMATCH" in text
    assert "SMOKE_IDP_NEG_TOKEN_AUDIENCE_MISMATCH" in text
    assert "SMOKE_IDP_NEG_TOKEN_EXPIRED" in text
    assert "SMOKE_IDP_NEG_TOKEN_NOT_YET_VALID" in text
    assert "SMOKE_IDP_NEG_TOKEN_IAT_IN_FUTURE" in text
    assert "SMOKE_IDP_NEG_TOKEN_MISSING_JTI" in text
    assert "SMOKE_IDP_NEG_TOKEN_REPLAY_1" in text
    assert "SMOKE_IDP_NEG_TOKEN_REPLAY_2" in text
    assert "SMOKE_IDP_NEG_TOKEN_ALG_NOT_ALLOWED" in text
    assert "SMOKE_IDP_NEG_TOKEN_INVALID_SIGNATURE" in text
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
    assert "ONCO_SMOKE_IDP_NEG_TOKEN_ALG_NOT_ALLOWED" in text
    assert "ONCO_SMOKE_IDP_NEG_TOKEN_INVALID_SIGNATURE" in text


def test_quality_gates_workflow_has_security_gate_job() -> None:
    workflow = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "quality-gates.yml"
    text = workflow.read_text()

    assert "security-gates:" in text
    assert "Security hygiene scan (secrets + sbom manifest)" in text
    assert "python scripts/security_gate.py" in text
    assert "Install pip-audit" in text
    assert "pip-audit -r backend/requirements.txt" in text
    assert "npm audit --audit-level=high --omit=dev" in text
