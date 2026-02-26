import { NextRequest, NextResponse } from "next/server";

import { ensureSameOriginRequest } from "@/lib/security/csrf";
import { recordSessionAudit } from "@/lib/security/session_audit";
import {
  clearRoleSessionCookies,
  resolveSessionFromRequest,
  revokeSessionsFromRequest
} from "@/lib/security/role_cookie";
import { persistForcedLogoutUser } from "@/lib/security/session_registry";

type RevokeScope = "self" | "user";

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

function normalizeScope(value: unknown): RevokeScope {
  const normalized = String(value || "")
    .trim()
    .toLowerCase();
  return normalized === "user" ? "user" : "self";
}

function jsonSessionRevokeError(
  status: number,
  error: string,
  code: "BFF_AUTH_REQUIRED" | "BFF_FORBIDDEN" | "BFF_BAD_REQUEST",
  correlationId: string,
  reason: string
): NextResponse {
  return withCorrelation(NextResponse.json(
    {
      error,
      error_code: code,
      code,
      reason,
      correlation_id: correlationId
    },
    { status }
  ), correlationId);
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  const correlationId = requestCorrelationId(request);
  const csrf = ensureSameOriginRequest(request);
  if (!csrf.ok) {
    await recordSessionAudit({
      event: "session_revoke_rejected",
      outcome: "deny",
      reason: csrf.reason,
      path: "/api/session/revoke",
      correlation_id: correlationId
    });
    return jsonSessionRevokeError(
      403,
      "Cross-site revoke request blocked",
      "BFF_FORBIDDEN",
      correlationId,
      csrf.reason
    );
  }
  const session = await resolveSessionFromRequest(request);
  if (!session) {
    await recordSessionAudit({
      event: "session_revoke_rejected",
      outcome: "deny",
      reason: "auth_required",
      path: "/api/session/revoke",
      correlation_id: correlationId
    });
    return jsonSessionRevokeError(401, "Authentication required", "BFF_AUTH_REQUIRED", correlationId, "auth_required");
  }

  let body: { scope?: unknown; user_id?: unknown } = {};
  try {
    body = (await request.json()) as { scope?: unknown; user_id?: unknown };
  } catch {
    body = {};
  }
  const scope = normalizeScope(body.scope);

  if (scope === "user") {
    if (session.role !== "admin") {
      await recordSessionAudit({
        event: "session_revoke_rejected",
        outcome: "deny",
        role: session.role,
        user_id: session.userId,
        session_id: session.sessionId,
        reason: "admin_role_required",
        path: "/api/session/revoke",
        correlation_id: correlationId
      });
      return jsonSessionRevokeError(
        403,
        "Admin role required for user revocation",
        "BFF_FORBIDDEN",
        correlationId,
        "admin_role_required"
      );
    }
    const targetUserId = String(body.user_id || "").trim();
    if (!targetUserId) {
      return jsonSessionRevokeError(
        400,
        "user_id is required for scope=user",
        "BFF_BAD_REQUEST",
        correlationId,
        "user_id_required_for_scope_user"
      );
    }
    const forcedAfter = await persistForcedLogoutUser(targetUserId, {
      actorUserId: session.userId,
      reason: "admin_forced_logout"
    });
    await recordSessionAudit({
      event: "session_force_logout_user",
      outcome: "info",
      role: session.role,
      user_id: targetUserId,
      actor_user_id: session.userId,
      reason: `forced_after=${forcedAfter}`,
      path: "/api/session/revoke",
      correlation_id: correlationId
    });
    return withCorrelation(NextResponse.json({
      ok: true,
      scope: "user",
      user_id: targetUserId,
      forced_logout_after: forcedAfter,
      correlation_id: correlationId
    }), correlationId);
  }

  const revoked = await revokeSessionsFromRequest(request);
  const response = withCorrelation(NextResponse.json({
    ok: true,
    scope: "self",
    revoked_session_ids: revoked.revoked_session_ids,
    correlation_id: correlationId
  }), correlationId);
  clearRoleSessionCookies(response);
  await recordSessionAudit({
    event: "session_revoke_self",
    outcome: "info",
    role: session.role,
    user_id: session.userId,
    session_id: session.sessionId,
    reason: `revoked=${revoked.revoked_session_ids}`,
    path: "/api/session/revoke",
    correlation_id: correlationId
  });
  return response;
}
