import { createHash } from "node:crypto";

import { backendUrl, demoToken } from "@/lib/backend";
import { normalizeServerRole, type SessionIdentity } from "@/lib/security/role_cookie";
import { sessionIdpConfig } from "@/lib/security/session_auth";

type JwtHeader = {
  alg?: string;
  typ?: string;
  kid?: string;
};

type JwtClaims = {
  iss?: unknown;
  aud?: unknown;
  exp?: unknown;
  nbf?: unknown;
  iat?: unknown;
  jti?: unknown;
  sub?: unknown;
  [key: string]: unknown;
};

type JwkRecord = {
  kty?: string;
  kid?: string;
  alg?: string;
  n?: string;
  e?: string;
  [key: string]: unknown;
};

type JwksPayload = {
  keys?: unknown;
};

type IdpValidationResult =
  | {
      ok: true;
      identity: SessionIdentity;
      claims: JwtClaims;
      source: "hs256" | "rs256";
    }
  | {
      ok: false;
      reason: string;
    };

type JwksCacheState = {
  fetchedAtMs: number;
  jwks: JwksPayload | null;
};

type GlobalWithJwksCache = typeof globalThis & {
  __oncoai_idp_jwks_cache_v1__?: Map<string, JwksCacheState>;
};

const JWKS_CACHE_TTL_MS = 5 * 60 * 1000;

function nowEpochSec(): number {
  return Math.floor(Date.now() / 1000);
}

function base64UrlDecode(input: string): string | null {
  const normalized = String(input || "")
    .trim()
    .replace(/-/g, "+")
    .replace(/_/g, "/");
  if (!normalized) return null;
  const padLength = (4 - (normalized.length % 4)) % 4;
  const padded = normalized + "=".repeat(padLength);
  try {
    return Buffer.from(padded, "base64").toString("utf8");
  } catch {
    return null;
  }
}

function base64UrlToBytes(input: string): Uint8Array | null {
  const normalized = String(input || "")
    .trim()
    .replace(/-/g, "+")
    .replace(/_/g, "/");
  if (!normalized) return null;
  const padLength = (4 - (normalized.length % 4)) % 4;
  const padded = normalized + "=".repeat(padLength);
  try {
    return new Uint8Array(Buffer.from(padded, "base64"));
  } catch {
    return null;
  }
}

function toArrayBuffer(bytes: Uint8Array): ArrayBuffer {
  const buffer = new ArrayBuffer(bytes.byteLength);
  new Uint8Array(buffer).set(bytes);
  return buffer;
}

function parseJsonObject<T extends Record<string, unknown>>(raw: string | null): T | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null;
    return parsed as T;
  } catch {
    return null;
  }
}

function parseJwt(token: string): { header: JwtHeader; claims: JwtClaims; signingInput: string; signature: Uint8Array } | null {
  const raw = String(token || "").trim();
  const parts = raw.split(".");
  if (parts.length !== 3) return null;
  const [headerB64, payloadB64, sigB64] = parts;
  if (!headerB64 || !payloadB64 || !sigB64) return null;
  const header = parseJsonObject<JwtHeader>(base64UrlDecode(headerB64));
  const claims = parseJsonObject<JwtClaims>(base64UrlDecode(payloadB64));
  const signature = base64UrlToBytes(sigB64);
  if (!header || !claims || !signature) return null;
  return {
    header,
    claims,
    signingInput: `${headerB64}.${payloadB64}`,
    signature
  };
}

function readString(value: unknown, maxLen = 300): string {
  return String(value || "")
    .trim()
    .slice(0, maxLen);
}

function readNumericEpoch(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return Math.floor(value);
  if (typeof value === "string") {
    const parsed = Number.parseInt(value, 10);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function audienceMatches(tokenAud: unknown, expectedAudience: string): boolean {
  const expected = readString(expectedAudience, 300);
  if (!expected) return true;
  if (typeof tokenAud === "string") {
    return tokenAud.trim() === expected;
  }
  if (Array.isArray(tokenAud)) {
    return tokenAud.some((item) => typeof item === "string" && item.trim() === expected);
  }
  return false;
}

function validateClaims(claims: JwtClaims): { ok: true; exp: number; jti: string } | { ok: false; reason: string } {
  const cfg = sessionIdpConfig();
  const issuer = readString(claims.iss);
  if (!issuer || issuer !== cfg.issuer) {
    return { ok: false, reason: "idp_issuer_mismatch" };
  }
  if (!audienceMatches(claims.aud, cfg.audience)) {
    return { ok: false, reason: "idp_audience_mismatch" };
  }

  const now = nowEpochSec();
  const leeway = Math.max(0, Math.min(cfg.clockSkewSec || 0, 300));
  const exp = readNumericEpoch(claims.exp);
  if (!exp || exp <= now - leeway) {
    return { ok: false, reason: "idp_token_expired" };
  }
  const nbf = readNumericEpoch(claims.nbf);
  if (cfg.requireNbf && !nbf) {
    return { ok: false, reason: "idp_nbf_missing" };
  }
  if (nbf && nbf > now + leeway) {
    return { ok: false, reason: "idp_token_not_yet_valid" };
  }
  const iat = readNumericEpoch(claims.iat);
  if (iat && iat > now + leeway) {
    return { ok: false, reason: "idp_iat_in_future" };
  }

  const jti = readString(claims.jti, 200);
  if (cfg.requireJti && !jti) {
    return { ok: false, reason: "idp_jti_missing" };
  }
  return { ok: true, exp, jti };
}

function getJwksCache(): Map<string, JwksCacheState> {
  const root = globalThis as GlobalWithJwksCache;
  if (!root.__oncoai_idp_jwks_cache_v1__) {
    root.__oncoai_idp_jwks_cache_v1__ = new Map<string, JwksCacheState>();
  }
  return root.__oncoai_idp_jwks_cache_v1__;
}

async function loadJwksPayload(forceRefresh = false): Promise<JwksPayload | null> {
  const cfg = sessionIdpConfig();
  const inline = readString(cfg.jwksJson, 200_000);
  if (inline) {
    const parsed = parseJsonObject<JwksPayload>(inline);
    return parsed;
  }
  if (!cfg.jwksUrl) return null;

  const cacheKey = cfg.jwksUrl;
  const cache = getJwksCache();
  const cached = cache.get(cacheKey);
  if (!forceRefresh && cached && Date.now() - cached.fetchedAtMs <= JWKS_CACHE_TTL_MS) {
    return cached.jwks;
  }
  try {
    const response = await fetch(cfg.jwksUrl, { cache: "no-store" });
    if (!response.ok) {
      cache.set(cacheKey, { fetchedAtMs: Date.now(), jwks: null });
      return null;
    }
    const payload = (await response.json()) as JwksPayload;
    cache.set(cacheKey, { fetchedAtMs: Date.now(), jwks: payload });
    return payload;
  } catch {
    cache.set(cacheKey, { fetchedAtMs: Date.now(), jwks: null });
    return null;
  }
}

async function verifyHs256(tokenInput: string, signature: Uint8Array): Promise<boolean> {
  const cfg = sessionIdpConfig();
  const secret = readString(cfg.hs256Secret, 4096);
  if (!secret) return false;
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["verify"]
  );
  return crypto.subtle.verify("HMAC", key, toArrayBuffer(signature), new TextEncoder().encode(tokenInput));
}

function pickRsaJwk(payload: JwksPayload, kid: string): JwkRecord | null {
  const keys = Array.isArray(payload.keys) ? payload.keys : [];
  for (const item of keys) {
    if (!item || typeof item !== "object") continue;
    const record = item as JwkRecord;
    if (String(record.kty || "").toUpperCase() !== "RSA") continue;
    if (String(record.kid || "") !== kid) continue;
    if (!record.n || !record.e) continue;
    return record;
  }
  return null;
}

async function verifyRs256(tokenInput: string, signature: Uint8Array, kid: string | undefined): Promise<boolean> {
  const keyId = readString(kid, 200);
  if (!keyId) return false;
  const verifyWithJwks = async (jwks: JwksPayload | null): Promise<boolean> => {
    if (!jwks) return false;
    const jwk = pickRsaJwk(jwks, keyId);
    if (!jwk) return false;
    const key = await crypto.subtle.importKey(
      "jwk",
      jwk as JsonWebKey,
      { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
      false,
      ["verify"]
    );
    return crypto.subtle.verify(
      { name: "RSASSA-PKCS1-v1_5" },
      key,
      toArrayBuffer(signature),
      new TextEncoder().encode(tokenInput)
    );
  };

  const cached = await loadJwksPayload(false);
  if (await verifyWithJwks(cached)) return true;
  const refreshed = await loadJwksPayload(true);
  if (!refreshed) return false;
  return verifyWithJwks(refreshed);
}

function hashJti(value: string): string {
  return `sha256:${createHash("sha256").update(value, "utf8").digest("hex")}`;
}

async function reserveIdpTokenJti(payload: { jti: string; userId: string; exp: number }): Promise<{ ok: true } | { ok: false; reason: string }> {
  try {
    const response = await fetch(backendUrl("/session/idp/replay/reserve"), {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-demo-token": demoToken()
      },
      body: JSON.stringify({
        jti_hash: hashJti(payload.jti),
        user_id: payload.userId,
        exp: payload.exp
      }),
      cache: "no-store"
    });
    if (!response.ok) {
      return { ok: false, reason: "idp_replay_check_failed" };
    }
    const data = (await response.json()) as { allowed?: unknown; reason?: unknown };
    if (data.allowed === true) {
      return { ok: true };
    }
    const reason = readString(data.reason, 120);
    return { ok: false, reason: reason || "idp_token_replay_detected" };
  } catch {
    return { ok: false, reason: "idp_replay_check_failed" };
  }
}

function compileUserIdPattern(rawPattern: string): RegExp {
  try {
    return new RegExp(rawPattern);
  } catch {
    return /^[A-Za-z0-9._:@-]{1,120}$/;
  }
}

function resolveIdentityFromClaimsStrict(
  claims: JwtClaims
): { ok: true; identity: SessionIdentity } | { ok: false; reason: string } {
  const cfg = sessionIdpConfig();
  const roleRaw = readString(claims[cfg.roleClaim], 80);
  const role = normalizeServerRole(roleRaw);
  if (!role) return { ok: false, reason: "idp_claims_missing_identity_or_role_not_allowed" };
  if (!cfg.allowedRoles.includes(role)) return { ok: false, reason: "idp_claims_missing_identity_or_role_not_allowed" };

  const userRaw = readString(claims[cfg.userIdClaim], 160);
  if (!userRaw) return { ok: false, reason: "idp_user_id_missing" };
  const userIdPattern = compileUserIdPattern(readString(cfg.userIdRegex, 300));
  if (!userIdPattern.test(userRaw)) {
    return { ok: false, reason: "idp_user_id_invalid_format" };
  }
  return {
    ok: true,
    identity: {
      role,
      userId: `idp:${userRaw}`
    }
  };
}

export async function resolveIdpIdentityFromToken(token: string): Promise<IdpValidationResult> {
  const parsed = parseJwt(token);
  if (!parsed) return { ok: false, reason: "idp_invalid_jwt_format" };

  const cfg = sessionIdpConfig();
  if (!cfg.enabled) return { ok: false, reason: "idp_mode_not_enabled" };
  if (!cfg.issuer || !cfg.audience) {
    return { ok: false, reason: "idp_config_incomplete" };
  }
  if (!cfg.jwksUrl && !cfg.jwksJson && !cfg.hs256Secret) {
    return { ok: false, reason: "idp_config_incomplete" };
  }

  const claimsCheck = validateClaims(parsed.claims);
  if (!claimsCheck.ok) return claimsCheck;

  const alg = readString(parsed.header.alg, 20).toUpperCase();
  if (!cfg.allowedAlgs.includes(alg)) {
    return { ok: false, reason: "idp_alg_not_allowed" };
  }
  let verified = false;
  if (alg === "HS256") {
    verified = await verifyHs256(parsed.signingInput, parsed.signature);
    if (!verified) return { ok: false, reason: "idp_signature_invalid_hs256" };
  } else if (alg === "RS256") {
    verified = await verifyRs256(parsed.signingInput, parsed.signature, parsed.header.kid);
    if (!verified) return { ok: false, reason: "idp_signature_invalid_rs256" };
  } else {
    return { ok: false, reason: "idp_alg_not_supported" };
  }

  const identityResolution = resolveIdentityFromClaimsStrict(parsed.claims);
  if (!identityResolution.ok) return identityResolution;
  const identity = identityResolution.identity;

  if (cfg.replayCheckEnabled && claimsCheck.jti) {
    const replay = await reserveIdpTokenJti({
      jti: claimsCheck.jti,
      userId: identity.userId,
      exp: claimsCheck.exp
    });
    if (!replay.ok) {
      return { ok: false, reason: replay.reason || "idp_token_replay_detected" };
    }
  }
  return {
    ok: true,
    identity,
    claims: parsed.claims,
    source: alg === "HS256" ? "hs256" : "rs256"
  };
}
