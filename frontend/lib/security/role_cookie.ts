import { NextRequest, NextResponse } from "next/server";
import { recordSessionAudit } from "@/lib/security/session_audit";
import {
  checkSessionAccess,
  persistSessionRevocations,
  revokeSession,
  type SessionRevocationEntry
} from "@/lib/security/session_registry";

export type ServerRole = "admin" | "clinician" | "patient";
export type SessionSource = "access" | "refresh";
export type SessionIdentity = {
  role: ServerRole;
  userId: string;
};
export type ServerSession = {
  role: ServerRole;
  source: SessionSource;
  userId: string;
  sessionId: string;
  issuedAt: number;
  exp: number;
};

export const SESSION_ACCESS_COOKIE_NAME = "session_access";
export const SESSION_ACCESS_SIG_COOKIE_NAME = "session_access_sig";
export const SESSION_REFRESH_COOKIE_NAME = "session_refresh";
export const SESSION_REFRESH_SIG_COOKIE_NAME = "session_refresh_sig";

const SUPPORTED_ROLES: ReadonlySet<ServerRole> = new Set(["admin", "clinician", "patient"]);
const SUPPORTED_KINDS: ReadonlySet<SessionSource> = new Set(["access", "refresh"]);

function roleCookieSecret(): string {
  return process.env.ROLE_COOKIE_SECRET || process.env.DEMO_TOKEN || "oncoai-dev-role-secret";
}

function accessTtlSec(): number {
  const parsed = Number.parseInt(process.env.SESSION_ACCESS_TTL_SEC || "900", 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 900;
}

function refreshTtlSec(): number {
  const parsed = Number.parseInt(process.env.SESSION_REFRESH_TTL_SEC || "604800", 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 604800;
}

function nowEpochSec(): number {
  return Math.floor(Date.now() / 1000);
}

function toHex(bytes: ArrayBuffer): string {
  return Array.from(new Uint8Array(bytes))
    .map((item) => item.toString(16).padStart(2, "0"))
    .join("");
}

function fromHex(value: string): Uint8Array | null {
  if (!value || value.length % 2 !== 0) return null;
  const normalized = value.trim().toLowerCase();
  if (!/^[0-9a-f]+$/.test(normalized)) return null;

  const bytes = new Uint8Array(normalized.length / 2);
  for (let index = 0; index < normalized.length; index += 2) {
    bytes[index / 2] = Number.parseInt(normalized.slice(index, index + 2), 16);
  }
  return bytes;
}

async function importHmacKey(secret: string): Promise<CryptoKey> {
  const data = new TextEncoder().encode(secret);
  return crypto.subtle.importKey("raw", data, { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"]);
}

export function normalizeServerRole(raw: string | null | undefined): ServerRole | null {
  const normalized = String(raw || "")
    .trim()
    .toLowerCase();
  if (SUPPORTED_ROLES.has(normalized as ServerRole)) {
    return normalized as ServerRole;
  }
  return null;
}

async function signValue(value: string): Promise<string> {
  const key = await importHmacKey(roleCookieSecret());
  const payload = new TextEncoder().encode(value);
  const signature = await crypto.subtle.sign("HMAC", key, payload);
  return toHex(signature);
}

async function verifyValue(value: string, signature: string | null | undefined): Promise<boolean> {
  const bytes = fromHex(String(signature || ""));
  if (!bytes) return false;
  const key = await importHmacKey(roleCookieSecret());
  const payload = new TextEncoder().encode(value);
  const signatureBuffer = new ArrayBuffer(bytes.byteLength);
  new Uint8Array(signatureBuffer).set(bytes);
  return crypto.subtle.verify("HMAC", key, signatureBuffer, payload);
}

function parseSessionToken(
  raw: string | null | undefined
): { kind: SessionSource; role: ServerRole; userId: string; sessionId: string; iat: number; exp: number } | null {
  const value = String(raw || "");
  if (!value) return null;
  const parts = value.split(".");
  if (parts.length !== 6 && parts.length !== 5 && parts.length !== 3) return null;

  const kind = (parts[0] || "").trim().toLowerCase();
  const role = normalizeServerRole(parts[1] || "");
  const isLegacy = parts.length === 3;
  const hasIssuedAt = parts.length === 6;
  const encodedUserId = isLegacy ? `legacy:${role || "unknown"}` : parts[2] || "";
  const encodedSessionId = isLegacy ? "legacy" : parts[3] || "";
  const iatRaw = hasIssuedAt ? parts[4] : "0";
  const expRaw = isLegacy ? parts[2] : hasIssuedAt ? parts[5] : parts[4];
  const iat = Number.parseInt(iatRaw || "", 10);
  const exp = Number.parseInt(expRaw || "", 10);
  if (!SUPPORTED_KINDS.has(kind as SessionSource)) return null;
  if (!role) return null;
  let userId = "";
  let sessionId = "";
  try {
    userId = decodeURIComponent(encodedUserId);
    sessionId = decodeURIComponent(encodedSessionId);
  } catch {
    return null;
  }
  if (!userId.trim()) return null;
  if (!sessionId.trim()) return null;
  if (!Number.isFinite(iat) || iat < 0) return null;
  if (!Number.isFinite(exp) || exp <= 0) return null;
  return {
    kind: kind as SessionSource,
    role,
    userId,
    sessionId,
    iat,
    exp
  };
}

function createSessionToken(identity: SessionIdentity, kind: SessionSource, ttlSec: number): string {
  const issuedAt = nowEpochSec();
  const exp = issuedAt + ttlSec;
  const sessionId = crypto.randomUUID();
  return [
    kind,
    identity.role,
    encodeURIComponent(identity.userId),
    encodeURIComponent(sessionId),
    String(issuedAt),
    String(exp)
  ].join(".");
}

async function resolveTokenSession(
  request: NextRequest,
  kind: SessionSource,
  tokenCookieName: string,
  sigCookieName: string,
  options: { ignoreRevocation?: boolean } = {}
): Promise<{ role: ServerRole; userId: string; sessionId: string; issuedAt: number; exp: number } | null> {
  const token = request.cookies.get(tokenCookieName)?.value || "";
  const signature = request.cookies.get(sigCookieName)?.value || "";
  const parsed = parseSessionToken(token);
  if (!parsed) return null;
  if (parsed.kind !== kind) return null;
  if (parsed.exp < nowEpochSec()) return null;

  const isValid = await verifyValue(token, signature);
  if (!isValid) return null;
  if (!options.ignoreRevocation) {
    const decision = await checkSessionAccess({
      sessionId: parsed.sessionId,
      userId: parsed.userId,
      issuedAtEpochSec: parsed.iat
    });
    if (!decision.allowed) {
      await recordSessionAudit({
        event: "session_rejected",
        outcome: "deny",
        role: parsed.role,
        user_id: parsed.userId,
        session_id: parsed.sessionId,
        reason: decision.reason || "session_rejected",
        path: request.nextUrl.pathname
      });
      return null;
    }
  }
  return {
    role: parsed.role,
    userId: parsed.userId,
    sessionId: parsed.sessionId,
    issuedAt: parsed.iat,
    exp: parsed.exp
  };
}

export async function issueRoleSessionCookies(
  response: NextResponse,
  identityOrRole: SessionIdentity | ServerRole
): Promise<void> {
  const identity: SessionIdentity =
    typeof identityOrRole === "string"
      ? {
          role: identityOrRole,
          userId: `demo:${identityOrRole}`
        }
      : identityOrRole;
  const accessToken = createSessionToken(identity, "access", accessTtlSec());
  const refreshToken = createSessionToken(identity, "refresh", refreshTtlSec());
  const accessSig = await signValue(accessToken);
  const refreshSig = await signValue(refreshToken);

  const baseOptions = {
    path: "/",
    sameSite: "lax" as const,
    httpOnly: true,
    secure: process.env.NODE_ENV === "production"
  };
  response.cookies.set(SESSION_ACCESS_COOKIE_NAME, accessToken, {
    ...baseOptions,
    maxAge: accessTtlSec()
  });
  response.cookies.set(SESSION_ACCESS_SIG_COOKIE_NAME, accessSig, {
    ...baseOptions,
    maxAge: accessTtlSec()
  });
  response.cookies.set(SESSION_REFRESH_COOKIE_NAME, refreshToken, {
    ...baseOptions,
    maxAge: refreshTtlSec()
  });
  response.cookies.set(SESSION_REFRESH_SIG_COOKIE_NAME, refreshSig, {
    ...baseOptions,
    maxAge: refreshTtlSec()
  });
}

export function clearRoleSessionCookies(response: NextResponse): void {
  const baseOptions = {
    path: "/",
    sameSite: "lax" as const,
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    maxAge: 0
  };
  for (const name of [
    SESSION_ACCESS_COOKIE_NAME,
    SESSION_ACCESS_SIG_COOKIE_NAME,
    SESSION_REFRESH_COOKIE_NAME,
    SESSION_REFRESH_SIG_COOKIE_NAME
  ]) {
    response.cookies.set(name, "", baseOptions);
  }
}

export async function revokeSessionsFromRequest(
  request: NextRequest
): Promise<{ revoked_session_ids: number; user_ids: string[] }> {
  const sessions = await Promise.all([
    resolveTokenSession(request, "access", SESSION_ACCESS_COOKIE_NAME, SESSION_ACCESS_SIG_COOKIE_NAME, {
      ignoreRevocation: true
    }),
    resolveTokenSession(request, "refresh", SESSION_REFRESH_COOKIE_NAME, SESSION_REFRESH_SIG_COOKIE_NAME, {
      ignoreRevocation: true
    })
  ]);

  const revoked = new Set<string>();
  const users = new Set<string>();
  const entries: SessionRevocationEntry[] = [];
  let actorRole: ServerRole | "clinician" = "clinician";
  for (const session of sessions) {
    if (!session) continue;
    actorRole = session.role;
    revokeSession(session.sessionId, session.exp);
    revoked.add(session.sessionId);
    users.add(session.userId);
    entries.push({
      session_id: session.sessionId,
      user_id: session.userId,
      role: session.role,
      exp: session.exp
    });
    await recordSessionAudit({
      event: "session_revoked",
      outcome: "info",
      role: session.role,
      user_id: session.userId,
      session_id: session.sessionId,
      reason: "logout",
      path: request.nextUrl.pathname
    });
  }
  if (entries.length > 0) {
    await persistSessionRevocations(entries, {
      actorRole,
      reason: "logout"
    });
  }
  return {
    revoked_session_ids: revoked.size,
    user_ids: Array.from(users)
  };
}

export async function resolveSessionFromRequest(request: NextRequest): Promise<ServerSession | null> {
  const accessSession = await resolveTokenSession(
    request,
    "access",
    SESSION_ACCESS_COOKIE_NAME,
    SESSION_ACCESS_SIG_COOKIE_NAME
  );
  if (accessSession) {
    return {
      role: accessSession.role,
      source: "access",
      userId: accessSession.userId,
      sessionId: accessSession.sessionId,
      issuedAt: accessSession.issuedAt,
      exp: accessSession.exp
    };
  }

  const refreshSession = await resolveTokenSession(
    request,
    "refresh",
    SESSION_REFRESH_COOKIE_NAME,
    SESSION_REFRESH_SIG_COOKIE_NAME
  );
  if (refreshSession) {
    return {
      role: refreshSession.role,
      source: "refresh",
      userId: refreshSession.userId,
      sessionId: refreshSession.sessionId,
      issuedAt: refreshSession.issuedAt,
      exp: refreshSession.exp
    };
  }
  return null;
}

export async function rotateSessionFromRefresh(
  response: NextResponse,
  session: ServerSession,
  options: { path?: string; correlationId?: string } = {}
): Promise<void> {
  await issueRoleSessionCookies(response, {
    role: session.role,
    userId: session.userId
  });
  if (session.source !== "refresh") return;

  await persistSessionRevocations(
    [
      {
        session_id: session.sessionId,
        user_id: session.userId,
        role: session.role,
        exp: session.exp
      }
    ],
    {
      actorRole: session.role,
      reason: "refresh_rotation"
    }
  );
  await recordSessionAudit({
    event: "session_refresh_rotated",
    outcome: "info",
    correlation_id: options.correlationId,
    role: session.role,
    user_id: session.userId,
    session_id: session.sessionId,
    reason: "refresh_rotation",
    path: options.path || ""
  });
}
