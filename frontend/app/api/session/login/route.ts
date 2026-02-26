import { NextRequest, NextResponse } from "next/server";

import { checkLoginRateLimit } from "@/lib/security/login_rate_limit";
import { ensureSameOriginRequest } from "@/lib/security/csrf";
import { resolveIdpIdentityFromToken } from "@/lib/security/idp_token";
import { recordSessionAudit } from "@/lib/security/session_audit";
import { issueRoleSessionCookies } from "@/lib/security/role_cookie";
import {
  hasCredentialUsersConfigured,
  hasIdpConfig,
  resolveCredentialIdentity,
  resolveDemoIdentity,
  sessionAuthMode
} from "@/lib/security/session_auth";

function normalizeCorrelationId(raw: string | null | undefined): string {
  const value = String(raw || "")
    .trim()
    .slice(0, 120);
  if (!value) return crypto.randomUUID();
  return value;
}

function requestCorrelationId(request: NextRequest): string {
  return normalizeCorrelationId(request.headers.get("x-correlation-id") || request.headers.get("x-request-id"));
}

function applyCorrelationHeader(response: NextResponse, correlationId: string): NextResponse {
  response.headers.set("x-correlation-id", correlationId);
  return response;
}

function sanitizeNextPath(raw: string | null | undefined): string {
  const value = String(raw || "").trim();
  if (!value.startsWith("/")) return "/";
  if (value.startsWith("//")) return "/";
  return value;
}

function isFormPost(request: NextRequest): boolean {
  const contentType = request.headers.get("content-type") || "";
  return contentType.includes("application/x-www-form-urlencoded") || contentType.includes("multipart/form-data");
}

function extractBearerToken(request: NextRequest): string {
  const header = String(request.headers.get("authorization") || "").trim();
  if (!header) return "";
  const match = header.match(/^Bearer\s+(.+)$/i);
  if (!match) return "";
  return String(match[1] || "").trim();
}

function normalizeCsrfReason(raw: string): "csrf_origin_mismatch" | "csrf_context_missing_or_cross_site" {
  return raw === "csrf_origin_mismatch" ? "csrf_origin_mismatch" : "csrf_context_missing_or_cross_site";
}

function jsonSessionError(
  status: number,
  error: string,
  code: "BFF_AUTH_REQUIRED" | "BFF_BAD_REQUEST" | "BFF_RATE_LIMITED" | "BFF_FORBIDDEN",
  correlationId: string,
  extra: Record<string, unknown> = {}
): NextResponse {
  const response = NextResponse.json(
    {
      error,
      error_code: code,
      code,
      correlation_id: correlationId,
      ...extra
    },
    { status }
  );
  response.headers.set("x-correlation-id", correlationId);
  return response;
}

export async function GET(request: NextRequest): Promise<NextResponse> {
  const correlationId = requestCorrelationId(request);
  const csrf = ensureSameOriginRequest(request);
  if (!csrf.ok) {
    const reason = normalizeCsrfReason(csrf.reason);
    await recordSessionAudit({
      event: "login_rejected",
      outcome: "deny",
      reason,
      path: "/api/session/login",
      correlation_id: correlationId
    });
    return jsonSessionError(403, "Cross-site login request blocked", "BFF_FORBIDDEN", correlationId, {
      reason
    });
  }
  const mode = sessionAuthMode();
  if (mode === "idp") {
    const reason = hasIdpConfig() ? "idp_mode_external_auth" : "idp_mode_missing_config";
    await recordSessionAudit({
      event: "login_rejected",
      outcome: "deny",
      reason,
      path: "/api/session/login",
      correlation_id: correlationId
    });
    return jsonSessionError(
      405,
      reason === "idp_mode_external_auth"
        ? "IdP mode is enabled: interactive login is handled by the upstream IdP gateway"
        : "IdP mode is enabled but SESSION_IDP_* config is incomplete",
      "BFF_AUTH_REQUIRED",
      correlationId,
      { reason }
    );
  }
  if (mode === "credentials") {
    await recordSessionAudit({
      event: "login_rejected",
      outcome: "deny",
      reason: "credentials_mode_requires_post",
      path: "/api/session/login",
      correlation_id: correlationId
    });
    return jsonSessionError(405, "Credentials mode requires POST with username/password", "BFF_AUTH_REQUIRED", correlationId);
  }
  const url = new URL(request.url);
  const identity = resolveDemoIdentity(url.searchParams.get("role"));
  if (!identity) {
    await recordSessionAudit({
      event: "login_rejected",
      outcome: "deny",
      reason: "missing_role",
      path: "/api/session/login",
      correlation_id: correlationId
    });
    return jsonSessionError(400, "role is required", "BFF_BAD_REQUEST", correlationId);
  }
  const nextPath = sanitizeNextPath(url.searchParams.get("next"));
  const redirectUrl = new URL(nextPath, request.url);
  const response = applyCorrelationHeader(NextResponse.redirect(redirectUrl), correlationId);
  await issueRoleSessionCookies(response, identity);
  await recordSessionAudit({
    event: "login_success",
    outcome: "allow",
    role: identity.role,
    user_id: identity.userId,
    reason: "demo_mode",
    path: "/api/session/login",
    correlation_id: correlationId
  });
  return response;
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  const correlationId = requestCorrelationId(request);
  const csrf = ensureSameOriginRequest(request);
  if (!csrf.ok) {
    const reason = normalizeCsrfReason(csrf.reason);
    await recordSessionAudit({
      event: "login_rejected",
      outcome: "deny",
      reason,
      path: "/api/session/login",
      correlation_id: correlationId
    });
    return jsonSessionError(403, "Cross-site login request blocked", "BFF_FORBIDDEN", correlationId, {
      reason
    });
  }
  const rateLimitDecision = checkLoginRateLimit(request);
  if (!rateLimitDecision.allowed) {
    await recordSessionAudit({
      event: "login_rejected",
      outcome: "deny",
      reason: "login_rate_limited",
      path: "/api/session/login",
      correlation_id: correlationId
    });
    const response = jsonSessionError(
      429,
      "Too many login attempts; retry later",
      "BFF_RATE_LIMITED",
      correlationId,
      {
        reason: "login_rate_limited",
        retry_after_sec: rateLimitDecision.retryAfterSec
      }
    );
    response.headers.set("retry-after", String(rateLimitDecision.retryAfterSec));
    return response;
  }

  const mode = sessionAuthMode();
  let rawRole: string | null = null;
  let rawUsername: string | null = null;
  let rawPassword: string | null = null;
  let rawNext: string | null = null;
  let rawIdToken: string | null = null;

  if (isFormPost(request)) {
    const form = await request.formData();
    rawRole = String(form.get("role") || "");
    rawUsername = String(form.get("username") || "");
    rawPassword = String(form.get("password") || "");
    rawNext = String(form.get("next") || "");
    rawIdToken = String(form.get("id_token") || "");
  } else {
    let body: { role?: unknown; username?: unknown; password?: unknown; next?: unknown; id_token?: unknown } = {};
    try {
      body = (await request.json()) as {
        role?: unknown;
        username?: unknown;
        password?: unknown;
        next?: unknown;
        id_token?: unknown;
      };
    } catch {
      body = {};
    }
    rawRole = body.role == null ? null : String(body.role);
    rawUsername = body.username == null ? null : String(body.username);
    rawPassword = body.password == null ? null : String(body.password);
    rawNext = body.next == null ? null : String(body.next);
    rawIdToken = body.id_token == null ? null : String(body.id_token);
  }

  if (mode === "idp") {
    if (!hasIdpConfig()) {
      await recordSessionAudit({
        event: "login_error",
        outcome: "error",
        reason: "idp_mode_missing_config",
        path: "/api/session/login",
        correlation_id: correlationId
      });
      return jsonSessionError(
        503,
        "IdP mode is enabled but SESSION_IDP_* config is incomplete",
        "BFF_AUTH_REQUIRED",
        correlationId,
        { reason: "idp_mode_missing_config" }
      );
    }

    const idToken = String(rawIdToken || extractBearerToken(request) || "").trim();
    if (!idToken) {
      await recordSessionAudit({
        event: "login_rejected",
        outcome: "deny",
        reason: "idp_token_missing",
        path: "/api/session/login",
        correlation_id: correlationId
      });
      return jsonSessionError(
        400,
        "id_token is required in idp mode (or Authorization: Bearer <token>)",
        "BFF_BAD_REQUEST",
        correlationId,
        { reason: "idp_token_missing" }
      );
    }

    const resolved = await resolveIdpIdentityFromToken(idToken);
    if (!resolved.ok) {
      await recordSessionAudit({
        event: "login_rejected",
        outcome: "deny",
        reason: resolved.reason,
        path: "/api/session/login",
        correlation_id: correlationId
      });
      return jsonSessionError(401, "IdP token validation failed", "BFF_AUTH_REQUIRED", correlationId, {
        reason: resolved.reason
      });
    }

    const nextPath = sanitizeNextPath(rawNext);
    if (isFormPost(request)) {
      const redirectUrl = new URL(nextPath, request.url);
      const response = applyCorrelationHeader(NextResponse.redirect(redirectUrl), correlationId);
      await issueRoleSessionCookies(response, resolved.identity);
      await recordSessionAudit({
        event: "login_success",
        outcome: "allow",
        role: resolved.identity.role,
        user_id: resolved.identity.userId,
        reason: `idp_mode_${resolved.source}`,
        path: "/api/session/login",
        correlation_id: correlationId
      });
      return response;
    }
    const response = applyCorrelationHeader(NextResponse.json({
      ok: true,
      role: resolved.identity.role,
      user_id: resolved.identity.userId,
      next: nextPath,
      auth_mode: mode,
      correlation_id: correlationId
    }), correlationId);
    await issueRoleSessionCookies(response, resolved.identity);
    await recordSessionAudit({
      event: "login_success",
      outcome: "allow",
      role: resolved.identity.role,
      user_id: resolved.identity.userId,
      reason: `idp_mode_${resolved.source}`,
      path: "/api/session/login",
      correlation_id: correlationId
    });
    return response;
  }

  if (mode === "credentials" && !hasCredentialUsersConfigured()) {
    await recordSessionAudit({
      event: "login_error",
      outcome: "error",
      reason: "credentials_mode_without_users",
      path: "/api/session/login",
      correlation_id: correlationId
    });
    return jsonSessionError(
      503,
      "Credentials mode is enabled but SESSION_USERS_JSON is empty or invalid",
      "BFF_AUTH_REQUIRED",
      correlationId
    );
  }

  const identity =
    mode === "credentials"
      ? resolveCredentialIdentity(rawUsername, rawPassword)
      : resolveDemoIdentity(rawRole);
  if (!identity) {
    const details =
      mode === "credentials"
        ? "username/password are required and must match SESSION_USERS_JSON"
        : "role is required";
    await recordSessionAudit({
      event: "login_rejected",
      outcome: "deny",
      role: mode === "demo" ? String(rawRole || "").toLowerCase() : undefined,
      reason: mode === "credentials" ? "invalid_credentials" : "missing_role",
      path: "/api/session/login",
      correlation_id: correlationId
    });
    return jsonSessionError(400, details, "BFF_BAD_REQUEST", correlationId);
  }

  const nextPath = sanitizeNextPath(rawNext);
  if (isFormPost(request)) {
    const redirectUrl = new URL(nextPath, request.url);
    const response = applyCorrelationHeader(NextResponse.redirect(redirectUrl), correlationId);
    await issueRoleSessionCookies(response, identity);
    await recordSessionAudit({
      event: "login_success",
      outcome: "allow",
      role: identity.role,
      user_id: identity.userId,
      reason: mode,
      path: "/api/session/login",
      correlation_id: correlationId
    });
    return response;
  }

  const response = applyCorrelationHeader(NextResponse.json({
    ok: true,
    role: identity.role,
    user_id: identity.userId,
    next: nextPath,
    auth_mode: mode,
    correlation_id: correlationId
  }), correlationId);
  await issueRoleSessionCookies(response, identity);
  await recordSessionAudit({
    event: "login_success",
    outcome: "allow",
    role: identity.role,
    user_id: identity.userId,
    reason: mode,
    path: "/api/session/login",
    correlation_id: correlationId
  });
  return response;
}
