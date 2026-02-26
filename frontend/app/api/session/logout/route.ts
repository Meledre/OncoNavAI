import { NextRequest, NextResponse } from "next/server";

import { ensureSameOriginRequest } from "@/lib/security/csrf";
import { recordSessionAudit } from "@/lib/security/session_audit";
import { clearRoleSessionCookies, resolveSessionFromRequest, revokeSessionsFromRequest } from "@/lib/security/role_cookie";

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

function withCorrelation(response: NextResponse, correlationId: string): NextResponse {
  response.headers.set("x-correlation-id", correlationId);
  return response;
}

function jsonLogoutError(
  status: number,
  error: string,
  code: "BFF_FORBIDDEN",
  correlationId: string,
  reason: string
): NextResponse {
  return withCorrelation(
    NextResponse.json(
      {
        error,
        error_code: code,
        code,
        reason,
        correlation_id: correlationId
      },
      { status }
    ),
    correlationId
  );
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

export async function GET(request: NextRequest): Promise<NextResponse> {
  const correlationId = requestCorrelationId(request);
  const csrf = ensureSameOriginRequest(request);
  if (!csrf.ok) {
    await recordSessionAudit({
      event: "logout_rejected",
      outcome: "deny",
      reason: csrf.reason,
      path: "/api/session/logout",
      correlation_id: correlationId
    });
    return jsonLogoutError(403, "Cross-site logout request blocked", "BFF_FORBIDDEN", correlationId, csrf.reason);
  }
  const session = await resolveSessionFromRequest(request);
  const revoked = await revokeSessionsFromRequest(request);
  const url = new URL(request.url);
  const nextPath = sanitizeNextPath(url.searchParams.get("next"));
  const redirectUrl = new URL(nextPath, request.url);
  const response = withCorrelation(NextResponse.redirect(redirectUrl), correlationId);
  clearRoleSessionCookies(response);
  await recordSessionAudit({
    event: "logout",
    outcome: "info",
    role: session?.role,
    user_id: session?.userId,
    session_id: session?.sessionId,
    reason: `revoked=${revoked.revoked_session_ids}`,
    path: "/api/session/logout",
    correlation_id: correlationId
  });
  return response;
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  const correlationId = requestCorrelationId(request);
  const csrf = ensureSameOriginRequest(request);
  if (!csrf.ok) {
    await recordSessionAudit({
      event: "logout_rejected",
      outcome: "deny",
      reason: csrf.reason,
      path: "/api/session/logout",
      correlation_id: correlationId
    });
    return jsonLogoutError(403, "Cross-site logout request blocked", "BFF_FORBIDDEN", correlationId, csrf.reason);
  }
  const session = await resolveSessionFromRequest(request);
  const revoked = await revokeSessionsFromRequest(request);
  if (isFormPost(request)) {
    const form = await request.formData();
    const nextPath = sanitizeNextPath(String(form.get("next") || ""));
    const redirectUrl = new URL(nextPath, request.url);
    const response = withCorrelation(NextResponse.redirect(redirectUrl), correlationId);
    clearRoleSessionCookies(response);
    await recordSessionAudit({
      event: "logout",
      outcome: "info",
      role: session?.role,
      user_id: session?.userId,
      session_id: session?.sessionId,
      reason: `revoked=${revoked.revoked_session_ids}`,
      path: "/api/session/logout",
      correlation_id: correlationId
    });
    return response;
  }

  let body: { next?: unknown } = {};
  try {
    body = (await request.json()) as { next?: unknown };
  } catch {
    body = {};
  }
  const nextPath = sanitizeNextPath(body.next == null ? null : String(body.next));
  const response = withCorrelation(NextResponse.json({
    ok: true,
    next: nextPath,
    revoked_session_ids: revoked.revoked_session_ids,
    correlation_id: correlationId
  }), correlationId);
  clearRoleSessionCookies(response);
  await recordSessionAudit({
    event: "logout",
    outcome: "info",
    role: session?.role,
    user_id: session?.userId,
    session_id: session?.sessionId,
    reason: `revoked=${revoked.revoked_session_ids}`,
    path: "/api/session/logout",
    correlation_id: correlationId
  });
  return response;
}
