import { NextRequest, NextResponse } from "next/server";

import { resolveSessionFromRequest, rotateSessionFromRefresh } from "@/lib/security/role_cookie";
import { recordSessionAudit } from "@/lib/security/session_audit";
import { sessionAuthMode } from "@/lib/security/session_auth";

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

function jsonSessionMeAuthRequired(correlationId: string): NextResponse {
  return withCorrelation(NextResponse.json(
    {
      authenticated: false,
      error: "Authentication required",
      error_code: "BFF_AUTH_REQUIRED",
      code: "BFF_AUTH_REQUIRED",
      reason: "auth_required",
      correlation_id: correlationId
    },
    { status: 401 }
  ), correlationId);
}

export async function GET(request: NextRequest): Promise<NextResponse> {
  const correlationId = requestCorrelationId(request);
  const session = await resolveSessionFromRequest(request);
  if (!session) {
    await recordSessionAudit({
      event: "session_me_rejected",
      outcome: "deny",
      reason: "auth_required",
      path: "/api/session/me",
      correlation_id: correlationId
    });
    return jsonSessionMeAuthRequired(correlationId);
  }

  const response = withCorrelation(NextResponse.json({
    authenticated: true,
    role: session.role,
    source: session.source,
    user_id: session.userId,
    auth_mode: sessionAuthMode(),
    correlation_id: correlationId
  }), correlationId);
  if (session.source === "refresh") {
    await recordSessionAudit({
      event: "session_refresh",
      outcome: "allow",
      role: session.role,
      user_id: session.userId,
      session_id: session.sessionId,
      reason: "refresh_cookie",
      path: "/api/session/me",
      correlation_id: correlationId
    });
    await rotateSessionFromRefresh(response, session, { path: "/api/session/me", correlationId });
  }
  return response;
}
