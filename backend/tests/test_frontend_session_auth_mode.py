from __future__ import annotations

from pathlib import Path


def _frontend_root() -> Path:
    return Path(__file__).resolve().parents[2] / "frontend"


def test_session_auth_helper_supports_demo_credentials_and_idp_modes() -> None:
    helper = _frontend_root() / "lib" / "security" / "session_auth.ts"
    text = helper.read_text()

    assert "SESSION_AUTH_MODE" in text
    assert "SESSION_USERS_JSON" in text
    assert "SESSION_IDP_ISSUER" in text
    assert "SESSION_IDP_AUDIENCE" in text
    assert "SESSION_IDP_JWKS_URL" in text
    assert "SESSION_IDP_ALLOWED_ALGS" in text
    assert "SESSION_IDP_ALLOWED_ROLES" in text
    assert "SESSION_IDP_USER_ID_REGEX" in text
    assert "SESSION_IDP_CLOCK_SKEW_SEC" in text
    assert "SESSION_IDP_REQUIRE_JTI" in text
    assert "SESSION_IDP_REQUIRE_NBF" in text
    assert "SESSION_IDP_REPLAY_CHECK_ENABLED" in text
    assert "sessionIdpConfig" in text
    assert "hasIdpConfig" in text
    assert "resolveDemoIdentity" in text
    assert "resolveCredentialIdentity" in text
    assert "timingSafeEqual" in text


def test_login_route_uses_auth_mode_switch_and_credential_identity_resolution() -> None:
    route = _frontend_root() / "app" / "api" / "session" / "login" / "route.ts"
    text = route.read_text()

    assert "checkLoginRateLimit" in text
    assert "BFF_RATE_LIMITED" in text
    assert "login_rate_limited" in text
    assert "retry-after" in text
    assert "sessionAuthMode" in text
    assert "hasIdpConfig" in text
    assert "resolveIdpIdentityFromToken" in text
    assert "id_token is required in idp mode" in text
    assert "idp_token_missing" in text
    assert "idp_mode_external_auth" in text
    assert "idp_mode_missing_config" in text
    assert "resolveCredentialIdentity" in text
    assert "resolveDemoIdentity" in text
    assert "Credentials mode requires POST with username/password" in text
    assert "error_code" in text
    assert "correlation_id" in text
    assert "x-correlation-id" in text
    assert "requestCorrelationId" in text
    assert "ensureSameOriginRequest" in text
    assert "csrf_origin_mismatch" in text
    assert "csrf_context_missing_or_cross_site" in text


def test_login_rate_limit_module_exists() -> None:
    module = _frontend_root() / "lib" / "security" / "login_rate_limit.ts"
    text = module.read_text()

    assert "checkLoginRateLimit" in text
    assert "SESSION_LOGIN_RATE_LIMIT_PER_MINUTE" in text
    assert "SESSION_LOGIN_RATE_LIMIT_WINDOW_SEC" in text
    assert "SESSION_LOGIN_RATE_LIMIT_KEY_MODE" in text
    assert "SESSION_TRUST_PROXY_HEADERS" in text
    assert 'return "global"' in text
    assert "x-forwarded-for" in text
    assert "x-real-ip" in text
    assert "retryAfterSec" in text


def test_role_cookie_tracks_user_bound_session_fields() -> None:
    cookie = _frontend_root() / "lib" / "security" / "role_cookie.ts"
    text = cookie.read_text()

    assert "userId" in text
    assert "sessionId" in text
    assert "crypto.randomUUID()" in text
    assert "revokeSessionsFromRequest" in text
    assert "checkSessionAccess" in text
    assert "rotateSessionFromRefresh" in text
    assert "refresh_rotation" in text


def test_session_registry_and_audit_modules_exist() -> None:
    root = _frontend_root()
    registry = (root / "lib" / "security" / "session_registry.ts").read_text()
    audit = (root / "lib" / "security" / "session_audit.ts").read_text()

    assert "revokeSession" in registry
    assert "revokeUserSessions" in registry
    assert "isSessionRevoked" in registry
    assert "isUserForcedLogout" in registry
    assert "checkSessionAccess" in registry
    assert "/session/check" in registry
    assert "/session/revoke" in registry
    assert "recordSessionAudit" in audit
    assert "listSessionAudit" in audit
    assert "correlation_id" in audit
    assert "/session/audit" in audit


def test_session_revoke_and_audit_routes_exist() -> None:
    root = _frontend_root()
    revoke_route = (root / "app" / "api" / "session" / "revoke" / "route.ts").read_text()
    audit_route = (root / "app" / "api" / "session" / "audit" / "route.ts").read_text()
    audit_summary_route = (root / "app" / "api" / "session" / "audit" / "summary" / "route.ts").read_text()
    audit_export_route = (root / "app" / "api" / "session" / "audit" / "export" / "route.ts").read_text()

    assert "/api/session/revoke" in revoke_route
    assert "persistForcedLogoutUser" in revoke_route
    assert "revokeSessionsFromRequest" in revoke_route
    assert "clearRoleSessionCookies" in revoke_route
    assert "error_code" in revoke_route
    assert "reason" in revoke_route
    assert "auth_required" in revoke_route
    assert "admin_role_required" in revoke_route
    assert "user_id_required_for_scope_user" in revoke_route
    assert "correlation_id" in revoke_route
    assert "x-correlation-id" in revoke_route
    assert "requestCorrelationId" in revoke_route
    assert "ensureSameOriginRequest" in revoke_route

    assert "export async function GET" in audit_route
    assert "proxyToBackend" in audit_route
    assert "/session/audit" in audit_route
    assert "correlation_id" in audit_route
    assert "cursor" in audit_route
    assert "next_cursor" in audit_route
    assert "outcome" in audit_route
    assert "reason_group" in audit_route
    assert "event" in audit_route
    assert "reason" in audit_route
    assert "user_id" in audit_route
    assert "from_ts" in audit_route
    assert "to_ts" in audit_route

    assert "export async function GET" in audit_summary_route
    assert "proxyToBackend" in audit_summary_route
    assert "/session/audit/summary" in audit_summary_route
    assert "window_hours" in audit_summary_route

    assert "export async function GET" in audit_export_route
    assert "/session/audit" in audit_export_route
    assert "proxyToBackend" in audit_export_route
    assert "format" in audit_export_route
    assert "all" in audit_export_route
    assert "max_events" in audit_export_route
    assert "Invalid ${paramName}" in audit_export_route
    assert 'paramName: "max_events"' in audit_export_route
    assert 'paramName: "max_pages"' in audit_export_route
    assert 'paramName: "limit"' in audit_export_route
    assert "from_ts" in audit_export_route
    assert "to_ts" in audit_export_route
    assert "content-disposition" in audit_export_route
    assert "x-onco-export-max-events" in audit_export_route
    assert "x-onco-export-truncated-reason" in audit_export_route
    assert "protectSpreadsheetFormula" in audit_export_route
    assert "@]/" in audit_export_route
    assert "return `'${text}`" in audit_export_route


def test_refresh_session_rotation_is_used_across_bff_routes() -> None:
    root = _frontend_root()
    me_route = (root / "app" / "api" / "session" / "me" / "route.ts").read_text()
    logout_route = (root / "app" / "api" / "session" / "logout" / "route.ts").read_text()
    proxy_lib = (root / "lib" / "bff" / "proxy.ts").read_text()
    middleware = (root / "proxy.ts").read_text()

    assert "rotateSessionFromRefresh" in me_route
    assert "error_code" in me_route
    assert "reason" in me_route
    assert "auth_required" in me_route
    assert "correlation_id" in me_route
    assert "x-correlation-id" in me_route
    assert "requestCorrelationId" in me_route
    assert "ensureSameOriginRequest" in logout_route
    assert "rotateSessionFromRefresh" in proxy_lib
    assert "rotateSessionFromRefresh" in middleware


def test_admin_page_has_session_security_controls() -> None:
    page = (_frontend_root() / "app" / "admin" / "page.tsx").read_text()

    assert "/api/session/audit" in page
    assert "/api/session/revoke" in page
    assert 'scope: "user"' in page
    assert "correlation_id" in page
    assert "Load Older Audit" in page
    assert "next_cursor" in page
    assert "outcome" in page
    assert "reason_group" in page
    assert "reason_group" in page
    assert "from_ts" in page
    assert "to_ts" in page
    assert "/api/session/audit/export" in page
    assert "Export Audit JSON" in page
    assert "Export Audit CSV" in page
    assert "export_max_events" in page
    assert "x-onco-export-truncated-reason" in page
    assert "Drilldown Correlation" in page
    assert "applyCorrelationDrilldown" in page
    assert "summarizeSessionReason" in page
    assert "SESSION_AUDIT_REASON_CATALOG" in page
    assert "Quick Reason Chips" in page
    assert "applyReasonCodeChip" in page
    assert "idp_alg_not_allowed" in page
    assert "idp_token_replay_detected" in page
    assert "/api/session/audit/summary" in page
    assert "Auth Risk Snapshot" in page
    assert "top_reasons" in page
    assert "incident_level" in page
    assert "incident_score" in page
    assert "incident_signals" in page
    assert "incident_alerts" in page
    assert "incidentBadgeClass" in page


def test_home_page_includes_idp_mode_notice() -> None:
    page = (_frontend_root() / "app" / "page.tsx").read_text()

    assert "async function HomePage" in page
    assert "await searchParams" in page
    assert '"idp"' in page
    assert "корпоративный провайдер идентификации" in page
    assert "/api/session/me" in page


def test_home_page_supports_auth_ui_override_for_credentials_and_demo_tabs() -> None:
    page = (_frontend_root() / "app" / "page.tsx").read_text()
    auth_card = (_frontend_root() / "components" / "shell" / "AuthTabsCard.tsx").read_text()

    assert "SESSION_AUTH_UI_OVERRIDE" in page
    assert '"all"' in page
    assert '"off"' in page
    assert "CREDENTIALS" in auth_card
    assert "DEMO" in auth_card


def test_idp_token_module_exists_with_signature_and_claim_validation() -> None:
    token_module = (_frontend_root() / "lib" / "security" / "idp_token.ts").read_text()
    auth_module = (_frontend_root() / "lib" / "security" / "session_auth.ts").read_text()

    assert "resolveIdpIdentityFromToken" in token_module
    assert "jwksJson" in token_module
    assert "hs256Secret" in token_module
    assert "allowedAlgs" in token_module
    assert "allowedRoles" in token_module
    assert "idp_alg_not_allowed" in token_module
    assert "idp_signature_invalid_rs256" in token_module
    assert "idp_token_replay_detected" in token_module
    assert "idp_jti_missing" in token_module
    assert "idp_user_id_missing" in token_module
    assert "idp_user_id_invalid_format" in token_module
    assert "reserveIdpTokenJti" in token_module
    assert "idp_claims_missing_identity_or_role_not_allowed" in token_module
    assert "SESSION_IDP_JWKS_JSON" in auth_module
    assert "SESSION_IDP_HS256_SECRET" in auth_module
