from __future__ import annotations

from pathlib import Path


def _frontend_path(*parts: str) -> Path:
    return Path(__file__).resolve().parents[2] / "frontend" / "app" / "api" / Path(*parts)


def test_bff_routes_use_shared_proxy_helper() -> None:
    routes = [
        _frontend_path("analyze", "route.ts"),
        _frontend_path("admin", "docs", "route.ts"),
        _frontend_path("admin", "upload", "route.ts"),
        _frontend_path("admin", "reindex", "route.ts"),
        _frontend_path("admin", "reindex", "[job_id]", "route.ts"),
        _frontend_path("admin", "sync", "russco", "route.ts"),
        _frontend_path("admin", "sync", "minzdrav", "route.ts"),
        _frontend_path("admin", "routing", "routes", "route.ts"),
        _frontend_path("admin", "routing", "rebuild", "route.ts"),
        _frontend_path("admin", "docs", "[doc_id]", "[doc_version]", "pdf", "route.ts"),
        _frontend_path("admin", "docs", "[doc_id]", "[doc_version]", "approve", "route.ts"),
        _frontend_path("admin", "docs", "[doc_id]", "[doc_version]", "reject", "route.ts"),
        _frontend_path("admin", "docs", "[doc_id]", "[doc_version]", "rechunk", "route.ts"),
        _frontend_path("admin", "docs", "[doc_id]", "[doc_version]", "index", "route.ts"),
        _frontend_path("case", "import", "route.ts"),
        _frontend_path("case", "import-file", "route.ts"),
        _frontend_path("case", "import", "runs", "route.ts"),
        _frontend_path("case", "import", "[import_run_id]", "route.ts"),
        _frontend_path("case", "[case_id]", "route.ts"),
        _frontend_path("patient", "analyze", "route.ts"),
        _frontend_path("report", "[slug]", "route.ts"),
        _frontend_path("report", "[slug]", "json", "route.ts"),
        _frontend_path("report", "[slug]", "html", "route.ts"),
        _frontend_path("session", "audit", "route.ts"),
        _frontend_path("session", "audit", "export", "route.ts"),
    ]
    for route in routes:
        text = route.read_text()
        assert 'from "@/lib/bff/proxy"' in text
        assert "BFF_PROXY_ERROR" not in text


def test_bff_proxy_helper_defines_error_taxonomy() -> None:
    helper = Path(__file__).resolve().parents[2] / "frontend" / "lib" / "bff" / "proxy.ts"
    text = helper.read_text()
    for code in (
        "BFF_BAD_REQUEST",
        "BFF_AUTH_REQUIRED",
        "BFF_FORBIDDEN",
        "BFF_UPSTREAM_VALIDATION_ERROR",
        "BFF_UPSTREAM_AUTH_ERROR",
        "BFF_UPSTREAM_NOT_FOUND",
        "BFF_UPSTREAM_RATE_LIMITED",
        "BFF_UPSTREAM_HTTP_ERROR",
        "BFF_UPSTREAM_NETWORK_ERROR",
    ):
        assert code in text
    assert "x-correlation-id" in text
    assert "correlation_id" in text
    assert "error_code: code" in text
    assert "requestCorrelationId" in text


def test_bff_proxy_retries_transient_network_errors() -> None:
    helper = Path(__file__).resolve().parents[2] / "frontend" / "lib" / "bff" / "proxy.ts"
    text = helper.read_text()

    assert "UPSTREAM_NETWORK_RETRY_ATTEMPTS" in text
    assert "UPSTREAM_NETWORK_RETRY_BACKOFF_MS" in text
    assert "shouldRetryNetworkError" in text
    assert "fetch failed" in text
    assert "for (let attempt = 1; attempt <= UPSTREAM_NETWORK_RETRY_ATTEMPTS; attempt += 1)" in text
    assert "await delayMs(UPSTREAM_NETWORK_RETRY_BACKOFF_MS * attempt)" in text


def test_bff_proxy_has_upstream_timeout_guard() -> None:
    helper = Path(__file__).resolve().parents[2] / "frontend" / "lib" / "bff" / "proxy.ts"
    text = helper.read_text()

    assert "UPSTREAM_FETCH_TIMEOUT_MS" in text
    assert "intFromEnv(\"ONCO_BFF_UPSTREAM_TIMEOUT_MS\"" in text
    assert "timeout after ${requestTimeoutMs}ms" in text
    assert "AbortError" in text
    assert "abortController.signal" in text


def test_bff_routes_use_server_side_roles_not_client_header() -> None:
    analyze = _frontend_path("analyze", "route.ts").read_text()
    assert 'allowedRoles: ["clinician", "admin"]' in analyze
    assert "request," in analyze
    assert "getRoleFromRequest" not in analyze

    for route in (
        _frontend_path("case", "import", "route.ts"),
        _frontend_path("case", "import-file", "route.ts"),
        _frontend_path("case", "import", "runs", "route.ts"),
        _frontend_path("case", "import", "[import_run_id]", "route.ts"),
        _frontend_path("case", "[case_id]", "route.ts"),
    ):
        text = route.read_text()
        assert 'allowedRoles: ["clinician", "admin"]' in text
        assert "request," in text
        assert "getRoleFromRequest" not in text

    patient_analyze = _frontend_path("patient", "analyze", "route.ts").read_text()
    assert 'allowedRoles: ["patient", "admin", "clinician"]' in patient_analyze
    assert "request," in patient_analyze
    assert "getRoleFromRequest" not in patient_analyze

    for route in (
        _frontend_path("admin", "docs", "route.ts"),
        _frontend_path("admin", "upload", "route.ts"),
        _frontend_path("admin", "reindex", "route.ts"),
        _frontend_path("admin", "reindex", "[job_id]", "route.ts"),
        _frontend_path("admin", "sync", "russco", "route.ts"),
        _frontend_path("admin", "sync", "minzdrav", "route.ts"),
        _frontend_path("admin", "routing", "routes", "route.ts"),
        _frontend_path("admin", "routing", "rebuild", "route.ts"),
        _frontend_path("admin", "docs", "[doc_id]", "[doc_version]", "approve", "route.ts"),
        _frontend_path("admin", "docs", "[doc_id]", "[doc_version]", "reject", "route.ts"),
        _frontend_path("admin", "docs", "[doc_id]", "[doc_version]", "rechunk", "route.ts"),
        _frontend_path("admin", "docs", "[doc_id]", "[doc_version]", "index", "route.ts"),
    ):
        text = route.read_text()
        assert 'allowedRoles: ["admin"]' in text
        assert "request," in text
        assert "getRoleFromRequest" not in text


def test_bff_role_cookie_is_signed_and_verified() -> None:
    frontend_root = Path(__file__).resolve().parents[2] / "frontend"
    proxy_text = (frontend_root / "proxy.ts").read_text()
    bff_text = (frontend_root / "lib" / "bff" / "proxy.ts").read_text()
    role_cookie_text = (frontend_root / "lib" / "security" / "role_cookie.ts").read_text()

    # proxy.ts should resolve existing signed session and never derive role from URL path.
    assert "resolveSessionFromRequest" in proxy_text
    assert "issueRoleCookies" not in proxy_text
    assert "getPageRole" not in proxy_text

    # Shared helper should define access/refresh signed cookies and secret usage.
    assert "SESSION_ACCESS_COOKIE_NAME" in role_cookie_text
    assert "SESSION_REFRESH_COOKIE_NAME" in role_cookie_text
    assert "ROLE_COOKIE_SECRET" in role_cookie_text
    assert "resolveSignedRoleFromRequest" not in role_cookie_text
    assert "ROLE_COOKIE_NAME" not in role_cookie_text
    assert "ROLE_SIG_COOKIE_NAME" not in role_cookie_text

    # BFF proxy should rely on signed session resolver, not trust plain role cookie.
    assert "resolveSessionFromRequest" in bff_text
    assert "BFF_AUTH_REQUIRED" in bff_text


def test_frontend_has_explicit_session_endpoints() -> None:
    frontend_root = Path(__file__).resolve().parents[2] / "frontend"
    login_route = frontend_root / "app" / "api" / "session" / "login" / "route.ts"
    logout_route = frontend_root / "app" / "api" / "session" / "logout" / "route.ts"
    me_route = frontend_root / "app" / "api" / "session" / "me" / "route.ts"

    assert login_route.exists()
    assert logout_route.exists()
    assert me_route.exists()

    login_text = login_route.read_text()
    logout_text = logout_route.read_text()
    me_text = me_route.read_text()

    assert "issueRoleSessionCookies" in login_text
    assert "error_code" in login_text
    assert "clearRoleSessionCookies" in logout_text
    assert "resolveSessionFromRequest" in me_text
    assert "error_code" in me_text


def test_frontend_contracts_include_v0_3_run_meta_fields() -> None:
    frontend_root = Path(__file__).resolve().parents[2] / "frontend"
    types_text = (frontend_root / "lib" / "contracts" / "types.ts").read_text()
    validate_text = (frontend_root / "lib" / "contracts" / "validate.ts").read_text()

    for field in ("report_generation_path", "fallback_reason", "retrieval_engine"):
        assert field in types_text
        assert field in validate_text


def test_admin_reindex_bff_route_allows_long_running_requests() -> None:
    route = _frontend_path("admin", "reindex", "route.ts").read_text()
    assert "export const maxDuration = 300" in route
    assert "timeoutMs: 900000" in route


def test_analyze_bff_routes_allow_extended_upstream_timeout() -> None:
    analyze_route = _frontend_path("analyze", "route.ts").read_text()
    patient_analyze_route = _frontend_path("patient", "analyze", "route.ts").read_text()

    assert "timeoutMs: 420000" in analyze_route
    assert "timeoutMs: 420000" in patient_analyze_route
