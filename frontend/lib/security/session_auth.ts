import { createHash, timingSafeEqual } from "node:crypto";

import { normalizeServerRole, type ServerRole, type SessionIdentity } from "@/lib/security/role_cookie";

export type SessionAuthMode = "demo" | "credentials" | "idp";

export type SessionIdpConfig = {
  enabled: boolean;
  issuer: string;
  audience: string;
  jwksUrl: string;
  jwksJson: string;
  hs256Secret: string;
  roleClaim: string;
  userIdClaim: string;
  userIdRegex: string;
  allowedAlgs: string[];
  allowedRoles: string[];
  clockSkewSec: number;
  requireJti: boolean;
  requireNbf: boolean;
  replayCheckEnabled: boolean;
};

type SessionUserRecord = {
  userId: string;
  username: string;
  password: string;
  role: ServerRole;
  active: boolean;
};

function normalizeAuthMode(raw: string | null | undefined): SessionAuthMode {
  const value = String(raw || "")
    .trim()
    .toLowerCase();
  if (value === "idp") return "idp";
  return value === "credentials" ? "credentials" : "demo";
}

export function sessionAuthMode(): SessionAuthMode {
  return normalizeAuthMode(process.env.SESSION_AUTH_MODE);
}

function envText(raw: string | null | undefined, maxLen = 300): string {
  return String(raw || "")
    .trim()
    .slice(0, maxLen);
}

function envBool(raw: string | null | undefined, fallback: boolean): boolean {
  const value = String(raw || "")
    .trim()
    .toLowerCase();
  if (!value) return fallback;
  if (["1", "true", "yes", "on"].includes(value)) return true;
  if (["0", "false", "no", "off"].includes(value)) return false;
  return fallback;
}

function envNumber(raw: string | null | undefined, fallback: number, min: number, max: number): number {
  const parsed = Number.parseInt(String(raw || "").trim(), 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(min, Math.min(max, parsed));
}

function parseCsvList(raw: string, fallback: string[]): string[] {
  const values = raw
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => item.toUpperCase());
  if (values.length === 0) return fallback;
  return Array.from(new Set(values));
}

export function sessionIdpConfig(): SessionIdpConfig {
  const mode = sessionAuthMode();
  return {
    enabled: mode === "idp",
    issuer: envText(process.env.SESSION_IDP_ISSUER),
    audience: envText(process.env.SESSION_IDP_AUDIENCE),
    jwksUrl: envText(process.env.SESSION_IDP_JWKS_URL),
    jwksJson: envText(process.env.SESSION_IDP_JWKS_JSON, 200_000),
    hs256Secret: envText(process.env.SESSION_IDP_HS256_SECRET, 4_096),
    roleClaim: envText(process.env.SESSION_IDP_ROLE_CLAIM || "role", 120),
    userIdClaim: envText(process.env.SESSION_IDP_USER_ID_CLAIM || "sub", 120),
    userIdRegex: envText(process.env.SESSION_IDP_USER_ID_REGEX || "^[A-Za-z0-9._:@-]{1,120}$", 300),
    allowedAlgs: parseCsvList(envText(process.env.SESSION_IDP_ALLOWED_ALGS || "RS256,HS256", 200), ["RS256", "HS256"]),
    allowedRoles: parseCsvList(
      envText(process.env.SESSION_IDP_ALLOWED_ROLES || "admin,clinician,patient", 200),
      ["ADMIN", "CLINICIAN", "PATIENT"]
    ).map((item) => item.toLowerCase()),
    clockSkewSec: envNumber(process.env.SESSION_IDP_CLOCK_SKEW_SEC, 60, 0, 300),
    requireJti: envBool(process.env.SESSION_IDP_REQUIRE_JTI, true),
    requireNbf: envBool(process.env.SESSION_IDP_REQUIRE_NBF, false),
    replayCheckEnabled: envBool(process.env.SESSION_IDP_REPLAY_CHECK_ENABLED, true)
  };
}

export function hasIdpConfig(): boolean {
  const cfg = sessionIdpConfig();
  const hasKeySource = Boolean(cfg.jwksUrl || cfg.jwksJson || cfg.hs256Secret);
  return cfg.enabled && Boolean(cfg.issuer && cfg.audience && hasKeySource);
}

function stableHash(value: string): Buffer {
  return createHash("sha256").update(value, "utf8").digest();
}

function timingSafeStringCompare(left: string, right: string): boolean {
  const leftDigest = stableHash(left);
  const rightDigest = stableHash(right);
  return timingSafeEqual(leftDigest, rightDigest);
}

function normalizeUserId(raw: string, fallbackUsername: string): string {
  const value = raw.trim();
  if (value) return value;
  return `user:${fallbackUsername.toLowerCase()}`;
}

function parseUsersConfig(raw: string): SessionUserRecord[] {
  if (!raw.trim()) return [];
  let parsed: unknown = null;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!Array.isArray(parsed)) return [];

  const users: SessionUserRecord[] = [];
  for (const item of parsed) {
    if (!item || typeof item !== "object") continue;
    const record = item as Record<string, unknown>;
    const username = String(record.username || "").trim();
    const password = String(record.password || "").trim();
    const role = normalizeServerRole(String(record.role || ""));
    const active = record.active === false ? false : true;
    if (!username || !password || !role || !active) continue;
    users.push({
      userId: normalizeUserId(String(record.user_id || ""), username),
      username,
      password,
      role,
      active
    });
  }
  return users;
}

function configuredUsers(): SessionUserRecord[] {
  return parseUsersConfig(String(process.env.SESSION_USERS_JSON || ""));
}

function passwordMatches(expected: string, provided: string): boolean {
  const value = expected.trim();
  const prefix = "sha256:";
  if (value.toLowerCase().startsWith(prefix)) {
    const expectedDigest = value.slice(prefix.length).trim().toLowerCase();
    if (!/^[0-9a-f]{64}$/.test(expectedDigest)) return false;
    return timingSafeStringCompare(expectedDigest, stableHash(provided).toString("hex"));
  }
  return timingSafeStringCompare(value, provided);
}

export function resolveDemoIdentity(rawRole: string | null | undefined): SessionIdentity | null {
  const role = normalizeServerRole(rawRole);
  if (!role) return null;
  return {
    role,
    userId: `demo:${role}`
  };
}

export function resolveCredentialIdentity(
  rawUsername: string | null | undefined,
  rawPassword: string | null | undefined
): SessionIdentity | null {
  const username = String(rawUsername || "").trim();
  const password = String(rawPassword || "");
  if (!username || !password) return null;

  for (const user of configuredUsers()) {
    if (!timingSafeStringCompare(user.username, username)) continue;
    if (!passwordMatches(user.password, password)) continue;
    return {
      role: user.role,
      userId: user.userId
    };
  }
  return null;
}

export function hasCredentialUsersConfigured(): boolean {
  return configuredUsers().length > 0;
}
