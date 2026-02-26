import { NextRequest, NextResponse } from "next/server";

import { backendUrl, demoToken } from "@/lib/backend";
import {
  resolveSessionFromRequest,
  rotateSessionFromRefresh,
  type ServerRole,
  type ServerSession
} from "@/lib/security/role_cookie";

export type BffErrorCode =
  | "BFF_BAD_REQUEST"
  | "BFF_AUTH_REQUIRED"
  | "BFF_FORBIDDEN"
  | "BFF_UPSTREAM_VALIDATION_ERROR"
  | "BFF_UPSTREAM_AUTH_ERROR"
  | "BFF_UPSTREAM_NOT_FOUND"
  | "BFF_UPSTREAM_RATE_LIMITED"
  | "BFF_UPSTREAM_HTTP_ERROR"
  | "BFF_UPSTREAM_NETWORK_ERROR";

type ProxyArgs = {
  request: NextRequest;
  backendPath: string;
  method: "GET" | "POST";
  allowedRoles: readonly ServerRole[];
  clientId?: string;
  body?: string;
  contentType?: string;
  timeoutMs?: number;
};

const UPSTREAM_NETWORK_RETRY_ATTEMPTS = 3;
const UPSTREAM_NETWORK_RETRY_BACKOFF_MS = 250;
const UPSTREAM_FETCH_TIMEOUT_MS = intFromEnv("ONCO_BFF_UPSTREAM_TIMEOUT_MS", 180_000, 1_000, 900_000);

function intFromEnv(name: string, fallback: number, minValue: number, maxValue: number): number {
  const raw = String(process.env[name] || "").trim();
  if (!raw) return fallback;
  const parsed = Number.parseInt(raw, 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(minValue, Math.min(parsed, maxValue));
}

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

async function resolveServerRole(request: NextRequest): Promise<ServerRole | null> {
  const session = await resolveSessionFromRequest(request);
  return session?.role || null;
}

async function resolveServerSession(request: NextRequest): Promise<ServerSession | null> {
  return resolveSessionFromRequest(request);
}

function mapStatusToCode(status: number): BffErrorCode {
  if (status === 400) return "BFF_UPSTREAM_VALIDATION_ERROR";
  if (status === 403) return "BFF_UPSTREAM_AUTH_ERROR";
  if (status === 404) return "BFF_UPSTREAM_NOT_FOUND";
  if (status === 429) return "BFF_UPSTREAM_RATE_LIMITED";
  return "BFF_UPSTREAM_HTTP_ERROR";
}

function parseErrorText(raw: string): string {
  if (!raw) return "";
  try {
    const parsed = JSON.parse(raw) as { error?: unknown };
    if (typeof parsed.error === "string" && parsed.error.trim()) {
      return parsed.error;
    }
    return raw;
  } catch {
    return raw;
  }
}

function shouldRetryNetworkError(error: unknown): boolean {
  if (!(error instanceof Error)) return false;
  const message = error.message.toLowerCase();
  return (
    message.includes("fetch failed") ||
    message.includes("econnrefused") ||
    message.includes("econnreset") ||
    message.includes("socket hang up") ||
    message.includes("network error")
  );
}

function delayMs(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, Math.max(0, ms)));
}

export function bffError(
  status: number,
  code: BffErrorCode,
  message: string,
  endpoint: string,
  upstreamStatus?: number,
  correlationId?: string
) {
  const response = NextResponse.json(
    {
      error: message,
      code,
      error_code: code,
      endpoint,
      upstream_status: upstreamStatus ?? null,
      correlation_id: correlationId || null
    },
    { status }
  );
  if (correlationId) {
    response.headers.set("x-correlation-id", correlationId);
  }
  return response;
}

export async function proxyToBackend(args: ProxyArgs): Promise<NextResponse> {
  const correlationId = requestCorrelationId(args.request);
  const requestTimeoutMs = Math.max(1_000, Math.min(Math.trunc(args.timeoutMs ?? UPSTREAM_FETCH_TIMEOUT_MS), 900_000));
  const session = await resolveServerSession(args.request);
  if (!session) {
    return bffError(
      401,
      "BFF_AUTH_REQUIRED",
      "Authentication required: session cookie is missing or invalid",
      args.backendPath,
      undefined,
      correlationId
    );
  }
  const role = session.role;
  if (!args.allowedRoles.includes(role)) {
    return bffError(403, "BFF_FORBIDDEN", `Access denied for role=${role}`, args.backendPath, undefined, correlationId);
  }

  for (let attempt = 1; attempt <= UPSTREAM_NETWORK_RETRY_ATTEMPTS; attempt += 1) {
    const abortController = new AbortController();
    const timeoutHandle = setTimeout(() => {
      abortController.abort();
    }, requestTimeoutMs);
    try {
      const upstream = await fetch(backendUrl(args.backendPath), {
        method: args.method,
        headers: {
          ...(args.contentType ? { "content-type": args.contentType } : {}),
          "x-role": role,
          "x-correlation-id": correlationId,
          ...(args.clientId ? { "x-client-id": args.clientId } : {}),
          "x-demo-token": demoToken()
        },
        body: args.body,
        cache: "no-store",
        signal: abortController.signal
      });

      if (upstream.ok) {
        const contentType = upstream.headers.get("content-type") || "application/json";
        const contentDisposition = upstream.headers.get("content-disposition");
        const body = await upstream.arrayBuffer();
        const response = new NextResponse(body, {
          status: upstream.status,
          headers: {
            "content-type": contentType,
            "x-correlation-id": correlationId,
            ...(contentDisposition ? { "content-disposition": contentDisposition } : {})
          }
        });
        if (session.source === "refresh") {
          await rotateSessionFromRefresh(response, session, {
            path: args.request.nextUrl.pathname,
            correlationId
          });
        }
        return response;
      }

      const text = await upstream.text();
      const upstreamError = parseErrorText(text);
      const fallbackMessage = `Upstream request failed for ${args.backendPath} (HTTP ${upstream.status})`;
      return bffError(
        upstream.status,
        mapStatusToCode(upstream.status),
        upstreamError || fallbackMessage,
        args.backendPath,
        upstream.status,
        correlationId
      );
    } catch (error) {
      const isAbortError = error instanceof Error && error.name === "AbortError";
      if (isAbortError) {
        return bffError(
          504,
          "BFF_UPSTREAM_NETWORK_ERROR",
          `BFF_UPSTREAM_NETWORK_ERROR (${args.backendPath}): timeout after ${requestTimeoutMs}ms`,
          args.backendPath,
          undefined,
          correlationId
        );
      }
      if (attempt < UPSTREAM_NETWORK_RETRY_ATTEMPTS && shouldRetryNetworkError(error)) {
        await delayMs(UPSTREAM_NETWORK_RETRY_BACKOFF_MS * attempt);
        continue;
      }
      const reason = error instanceof Error ? error.message : "unknown";
      return bffError(
        502,
        "BFF_UPSTREAM_NETWORK_ERROR",
        `BFF_UPSTREAM_NETWORK_ERROR (${args.backendPath}): ${reason}`,
        args.backendPath,
        undefined,
        correlationId
      );
    } finally {
      clearTimeout(timeoutHandle);
    }
  }

  return bffError(
    502,
    "BFF_UPSTREAM_NETWORK_ERROR",
    `BFF_UPSTREAM_NETWORK_ERROR (${args.backendPath}): retries exhausted`,
    args.backendPath,
    undefined,
    correlationId
  );
}

export async function getRoleFromRequest(request: NextRequest): Promise<ServerRole | null> {
  return resolveServerRole(request);
}
