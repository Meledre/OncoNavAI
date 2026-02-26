import { NextRequest, NextResponse } from "next/server";

import { backendUrl, demoToken } from "@/lib/backend";
import { bffError } from "@/lib/bff/proxy";
import { normalizeAnalyzeResponse } from "@/lib/contracts/validate";
import { rotateSessionFromRefresh, resolveSessionFromRequest } from "@/lib/security/role_cookie";
import { projectDoctorContextView } from "@/lib/viewmodels/doctor";

export const maxDuration = 900;

type UpstreamResult = {
  ok: boolean;
  status: number;
  payload: unknown;
  text: string;
};

function asObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function requestCorrelationId(request: NextRequest): string {
  const raw = request.headers.get("x-correlation-id") || request.headers.get("x-request-id") || "";
  const value = String(raw).trim().slice(0, 120);
  return value || crypto.randomUUID();
}

function parseErrorText(payload: unknown, text: string): string {
  if (payload && typeof payload === "object" && !Array.isArray(payload)) {
    const data = payload as Record<string, unknown>;
    const message = String(data.error || data.detail || data.message || "").trim();
    if (message) return message;
  }
  return text || "Upstream request failed";
}

function mapStatusToCode(status: number):
  | "BFF_UPSTREAM_VALIDATION_ERROR"
  | "BFF_UPSTREAM_AUTH_ERROR"
  | "BFF_UPSTREAM_NOT_FOUND"
  | "BFF_UPSTREAM_RATE_LIMITED"
  | "BFF_UPSTREAM_HTTP_ERROR" {
  if (status === 400) return "BFF_UPSTREAM_VALIDATION_ERROR";
  if (status === 403) return "BFF_UPSTREAM_AUTH_ERROR";
  if (status === 404) return "BFF_UPSTREAM_NOT_FOUND";
  if (status === 429) return "BFF_UPSTREAM_RATE_LIMITED";
  return "BFF_UPSTREAM_HTTP_ERROR";
}

async function fetchUpstreamJson(args: {
  path: string;
  role: "admin" | "clinician";
  method: "GET" | "POST";
  body?: string;
  correlationId: string;
  timeoutMs: number;
}): Promise<UpstreamResult> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), Math.max(1_000, Math.min(args.timeoutMs, 900_000)));
  try {
    const response = await fetch(backendUrl(args.path), {
      method: args.method,
      headers: {
        "content-type": args.method === "POST" ? "application/json" : "text/plain",
        "x-role": args.role,
        "x-demo-token": demoToken(),
        "x-correlation-id": args.correlationId
      },
      body: args.body,
      cache: "no-store",
      signal: controller.signal
    });
    const text = await response.text();
    let payload: unknown = null;
    try {
      payload = text ? JSON.parse(text) : null;
    } catch {
      payload = null;
    }
    return {
      ok: response.ok,
      status: response.status,
      payload,
      text
    };
  } finally {
    clearTimeout(timeout);
  }
}

function requestedCaseCountFromPayload(payload: Record<string, unknown>): number | undefined {
  const options = payload.options;
  if (!options || typeof options !== "object" || Array.isArray(options)) return undefined;
  const raw =
    (options as Record<string, unknown>).ui_case_count ??
    (options as Record<string, unknown>).case_count ??
    payload.case_count;
  const parsed = Number.parseInt(String(raw || ""), 10);
  if (!Number.isFinite(parsed) || parsed <= 0) return undefined;
  return parsed;
}

export async function POST(request: NextRequest) {
  const correlationId = requestCorrelationId(request);
  try {
    const session = await resolveSessionFromRequest(request);
    if (!session) {
      return bffError(
        401,
        "BFF_AUTH_REQUIRED",
        "Authentication required: session cookie is missing or invalid",
        "/doctor/analyze",
        undefined,
        correlationId
      );
    }
    if (!(session.role === "admin" || session.role === "clinician")) {
      return bffError(403, "BFF_FORBIDDEN", `Access denied for role=${session.role}`, "/doctor/analyze", undefined, correlationId);
    }

    const body = await request.text();
    let payload: unknown = null;
    try {
      payload = body ? JSON.parse(body) : null;
    } catch {
      return bffError(400, "BFF_BAD_REQUEST", "Invalid JSON payload", "/doctor/analyze", undefined, correlationId);
    }
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      return bffError(400, "BFF_BAD_REQUEST", "Payload must be an object", "/doctor/analyze", undefined, correlationId);
    }
    const payloadRecord = asObject(payload);
    const caseId = String(asObject(payloadRecord.case).case_id || "").trim();
    if (!caseId) {
      return bffError(400, "BFF_BAD_REQUEST", "Payload must include case.case_id", "/doctor/analyze", undefined, correlationId);
    }

    const analyzeResult = await fetchUpstreamJson({
      path: "/analyze",
      role: session.role,
      method: "POST",
      body,
      correlationId,
      timeoutMs: 420_000
    });
    if (!analyzeResult.ok) {
      return bffError(
        analyzeResult.status,
        mapStatusToCode(analyzeResult.status),
        parseErrorText(analyzeResult.payload, analyzeResult.text),
        "/analyze",
        analyzeResult.status,
        correlationId
      );
    }
    const normalizedAnalyzeResponse = normalizeAnalyzeResponse(analyzeResult.payload);
    if (!normalizedAnalyzeResponse) {
      return bffError(
        502,
        "BFF_UPSTREAM_HTTP_ERROR",
        "Upstream /analyze returned payload that does not match AnalyzeResponse v0.2",
        "/analyze",
        200,
        correlationId
      );
    }

    const caseResult = await fetchUpstreamJson({
      path: `/case/${encodeURIComponent(caseId)}`,
      role: session.role,
      method: "GET",
      correlationId,
      timeoutMs: 120_000
    });
    const casePayload = caseResult.ok ? caseResult.payload : {};

    const projection = projectDoctorContextView({
      analyzeResponse: normalizedAnalyzeResponse,
      casePayload,
      requestedCaseCount: requestedCaseCountFromPayload(payloadRecord)
    });

    const response = NextResponse.json(
      {
        analyze_response: normalizedAnalyzeResponse,
        doctor_context_view: projection.doctorContextView,
        context_meta: {
          ...projection.contextMeta,
          case_lookup_ok: caseResult.ok
        }
      },
      {
        status: 200,
        headers: {
          "x-correlation-id": correlationId
        }
      }
    );

    if (session.source === "refresh") {
      await rotateSessionFromRefresh(response, session, {
        path: request.nextUrl.pathname,
        correlationId
      });
    }
    return response;
  } catch (error) {
    const message = error instanceof Error ? error.message : "unknown";
    return bffError(
      502,
      "BFF_UPSTREAM_NETWORK_ERROR",
      `BFF_UPSTREAM_NETWORK_ERROR (/doctor/analyze): ${message}`,
      "/doctor/analyze",
      undefined,
      correlationId
    );
  }
}
