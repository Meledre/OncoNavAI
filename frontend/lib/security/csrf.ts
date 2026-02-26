import { NextRequest } from "next/server";

type CsrfDecision = {
  ok: boolean;
  reason: "ok" | "csrf_origin_mismatch" | "csrf_context_missing_or_cross_site";
};

function envBool(raw: string | null | undefined, fallback: boolean): boolean {
  const value = String(raw || "")
    .trim()
    .toLowerCase();
  if (!value) return fallback;
  if (["1", "true", "yes", "on"].includes(value)) return true;
  if (["0", "false", "no", "off"].includes(value)) return false;
  return fallback;
}

function parseCsvOrigins(raw: string | null | undefined): string[] {
  const value = String(raw || "").trim();
  if (!value) return [];
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function normalizeOrigin(raw: string | null | undefined): string {
  const value = String(raw || "").trim();
  if (!value) return "";
  try {
    return new URL(value).origin.toLowerCase();
  } catch {
    return "";
  }
}

function requestOriginCandidates(request: NextRequest): Set<string> {
  const origins = new Set<string>();
  origins.add(String(request.nextUrl.origin || "").toLowerCase());

  const forwardedProto = String(request.headers.get("x-forwarded-proto") || "").trim().toLowerCase();
  const host = String(request.headers.get("x-forwarded-host") || request.headers.get("host") || "")
    .trim()
    .toLowerCase();
  const proto = forwardedProto || request.nextUrl.protocol.replace(":", "").toLowerCase();
  if (host && proto) {
    origins.add(`${proto}://${host}`);
  }
  for (const trusted of parseCsvOrigins(process.env.SESSION_CSRF_TRUSTED_ORIGINS)) {
    const normalized = normalizeOrigin(trusted);
    if (normalized) origins.add(normalized);
  }
  origins.delete("");
  return origins;
}

function isSameSiteContext(request: NextRequest): boolean {
  const value = String(request.headers.get("sec-fetch-site") || "")
    .trim()
    .toLowerCase();
  if (!value) {
    return envBool(process.env.SESSION_CSRF_ALLOW_UNKNOWN_CONTEXT, true);
  }
  return value === "same-origin" || value === "same-site" || value === "none";
}

export function ensureSameOriginRequest(request: NextRequest): CsrfDecision {
  if (!envBool(process.env.SESSION_CSRF_ENFORCED, true)) {
    return { ok: true, reason: "ok" };
  }
  const allowedOrigins = requestOriginCandidates(request);
  const originHeader = normalizeOrigin(request.headers.get("origin"));
  if (originHeader) {
    if (allowedOrigins.has(originHeader)) return { ok: true, reason: "ok" };
    return { ok: false, reason: "csrf_origin_mismatch" };
  }

  const refererHeader = String(request.headers.get("referer") || "").trim();
  if (refererHeader) {
    const refererOrigin = normalizeOrigin(refererHeader);
    if (refererOrigin && allowedOrigins.has(refererOrigin)) return { ok: true, reason: "ok" };
    return { ok: false, reason: "csrf_origin_mismatch" };
  }

  if (isSameSiteContext(request)) return { ok: true, reason: "ok" };
  return { ok: false, reason: "csrf_context_missing_or_cross_site" };
}
