import { backendUrl, demoToken } from "@/lib/backend";

type SessionRegistryState = {
  revokedSessionIds: Map<string, number>;
  forcedLogoutAfterByUserId: Map<string, number>;
};

type GlobalWithSessionRegistry = typeof globalThis & {
  __oncoai_session_registry_v1__?: SessionRegistryState;
};

export type SessionRole = "admin" | "clinician" | "patient";

export type SessionCheckInput = {
  sessionId: string;
  userId: string;
  issuedAtEpochSec: number;
};

export type SessionRevocationEntry = {
  session_id: string;
  user_id: string;
  role?: SessionRole;
  exp?: number;
};

export type SessionCheckDecision = {
  allowed: boolean;
  reason: string;
  forced_logout_after?: number | null;
};

const REGISTRY_KEY = "__oncoai_session_registry_v1__";
const DEFAULT_REVOKED_TTL_SEC = 30 * 24 * 60 * 60;

function nowEpochSec(): number {
  return Math.floor(Date.now() / 1000);
}

function normalizeRole(raw: string | null | undefined): SessionRole {
  const value = String(raw || "")
    .trim()
    .toLowerCase();
  if (value === "admin" || value === "patient") return value;
  return "clinician";
}

function getRegistryState(): SessionRegistryState {
  const root = globalThis as GlobalWithSessionRegistry;
  if (!root[REGISTRY_KEY]) {
    root[REGISTRY_KEY] = {
      revokedSessionIds: new Map<string, number>(),
      forcedLogoutAfterByUserId: new Map<string, number>()
    };
  }
  return root[REGISTRY_KEY] as SessionRegistryState;
}

function cleanupExpiredRevocations(state: SessionRegistryState): void {
  const now = nowEpochSec();
  for (const [sessionId, expiresAt] of state.revokedSessionIds.entries()) {
    if (expiresAt <= now) {
      state.revokedSessionIds.delete(sessionId);
    }
  }
}

function safeNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number.parseInt(value, 10);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function setForcedLogoutCutoff(userId: string, cutoffEpochSec: number): void {
  const normalized = String(userId || "").trim();
  if (!normalized) return;
  const cutoff = safeNumber(cutoffEpochSec);
  if (cutoff == null || cutoff <= 0) return;
  getRegistryState().forcedLogoutAfterByUserId.set(normalized, cutoff);
}

async function postSessionBackend(
  path: string,
  body: Record<string, unknown>,
  role: SessionRole = "clinician"
): Promise<Record<string, unknown> | null> {
  try {
    const response = await fetch(backendUrl(path), {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-role": role,
        "x-demo-token": demoToken()
      },
      body: JSON.stringify(body),
      cache: "no-store"
    });
    if (!response.ok) return null;
    const data = (await response.json()) as Record<string, unknown>;
    return data;
  } catch {
    return null;
  }
}

function localDecision(input: SessionCheckInput): SessionCheckDecision {
  if (isSessionRevoked(input.sessionId)) {
    return { allowed: false, reason: "session_revoked" };
  }
  if (isUserForcedLogout(input.userId, input.issuedAtEpochSec)) {
    return { allowed: false, reason: "forced_logout" };
  }
  return { allowed: true, reason: "ok" };
}

export function revokeSession(sessionId: string, expEpochSec: number | null = null): void {
  const normalized = String(sessionId || "").trim();
  if (!normalized) return;

  const state = getRegistryState();
  cleanupExpiredRevocations(state);
  const fallbackExpiry = nowEpochSec() + DEFAULT_REVOKED_TTL_SEC;
  const expiresAt = Number.isFinite(expEpochSec || NaN) && (expEpochSec || 0) > 0 ? Number(expEpochSec) : fallbackExpiry;
  state.revokedSessionIds.set(normalized, expiresAt);
}

export function isSessionRevoked(sessionId: string): boolean {
  const normalized = String(sessionId || "").trim();
  if (!normalized) return false;

  const state = getRegistryState();
  cleanupExpiredRevocations(state);
  return state.revokedSessionIds.has(normalized);
}

export function revokeUserSessions(userId: string): number {
  const normalized = String(userId || "").trim();
  if (!normalized) return 0;

  const cutoff = nowEpochSec();
  setForcedLogoutCutoff(normalized, cutoff);
  return cutoff;
}

export function isUserForcedLogout(userId: string, issuedAtEpochSec: number): boolean {
  const normalized = String(userId || "").trim();
  if (!normalized) return false;

  const state = getRegistryState();
  const forcedAfter = state.forcedLogoutAfterByUserId.get(normalized);
  if (!forcedAfter) return false;
  return issuedAtEpochSec <= 0 || issuedAtEpochSec < forcedAfter;
}

export function listRevokedSessionIds(limit = 100): string[] {
  const boundedLimit = Math.max(1, Math.min(limit, 1000));
  const state = getRegistryState();
  cleanupExpiredRevocations(state);
  return Array.from(state.revokedSessionIds.keys()).slice(0, boundedLimit);
}

export async function checkSessionAccess(input: SessionCheckInput): Promise<SessionCheckDecision> {
  const fallback = localDecision(input);
  if (!fallback.allowed) return fallback;

  const payload = await postSessionBackend(
    "/session/check",
    {
      session_id: input.sessionId,
      user_id: input.userId,
      issued_at: input.issuedAtEpochSec
    },
    "clinician"
  );
  if (!payload) return fallback;

  const allowed = payload.allowed === true;
  const reason = String(payload.reason || (allowed ? "ok" : "deny"));
  const forcedAfter = safeNumber(payload.forced_logout_after);
  if (reason === "session_revoked") {
    revokeSession(input.sessionId);
  }
  if (reason === "forced_logout" && forcedAfter && forcedAfter > 0) {
    setForcedLogoutCutoff(input.userId, forcedAfter);
  }
  return {
    allowed,
    reason,
    forced_logout_after: forcedAfter
  };
}

export async function persistSessionRevocations(
  sessions: SessionRevocationEntry[],
  options: { actorRole?: string; reason?: string } = {}
): Promise<number> {
  const normalizedSessions = sessions.filter((item) => String(item.session_id || "").trim() && String(item.user_id || "").trim());
  if (normalizedSessions.length === 0) return 0;

  for (const session of normalizedSessions) {
    revokeSession(session.session_id, typeof session.exp === "number" ? session.exp : null);
  }
  const role = normalizeRole(options.actorRole || normalizedSessions[0]?.role || "clinician");
  const payload = await postSessionBackend(
    "/session/revoke",
    {
      scope: "self",
      reason: String(options.reason || "logout"),
      sessions: normalizedSessions.map((item) => ({
        session_id: item.session_id,
        user_id: item.user_id,
        role: item.role || role,
        exp: typeof item.exp === "number" ? item.exp : null
      }))
    },
    role
  );
  const persistedCount = safeNumber(payload?.revoked_session_ids);
  return persistedCount && persistedCount >= 0 ? persistedCount : normalizedSessions.length;
}

export async function persistForcedLogoutUser(
  userId: string,
  options: { actorUserId?: string; reason?: string } = {}
): Promise<number> {
  const normalized = String(userId || "").trim();
  if (!normalized) return 0;

  const localCutoff = revokeUserSessions(normalized);
  const payload = await postSessionBackend(
    "/session/revoke",
    {
      scope: "user",
      user_id: normalized,
      actor_user_id: String(options.actorUserId || ""),
      reason: String(options.reason || "admin_forced_logout")
    },
    "admin"
  );
  const remoteCutoff = safeNumber(payload?.forced_logout_after);
  if (remoteCutoff && remoteCutoff > 0) {
    setForcedLogoutCutoff(normalized, remoteCutoff);
    return remoteCutoff;
  }
  return localCutoff;
}
