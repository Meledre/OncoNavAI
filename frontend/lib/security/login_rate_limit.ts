import { NextRequest } from "next/server";

type LoginRateLimitState = {
  eventsByKey: Map<string, number[]>;
};

type GlobalWithLoginRateLimit = typeof globalThis & {
  __oncoai_login_rate_limit_v1__?: LoginRateLimitState;
};

export type LoginRateLimitDecision = {
  allowed: boolean;
  retryAfterSec: number;
  key: string;
};

const RATE_LIMIT_STATE_KEY = "__oncoai_login_rate_limit_v1__";

function asInt(raw: string | undefined, fallback: number, min: number, max: number): number {
  const parsed = Number.parseInt(String(raw || "").trim(), 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(min, Math.min(max, parsed));
}

function nowSec(): number {
  return Math.floor(Date.now() / 1000);
}

function maxAttempts(): number {
  return asInt(process.env.SESSION_LOGIN_RATE_LIMIT_PER_MINUTE, 60, 0, 10_000);
}

function windowSec(): number {
  return asInt(process.env.SESSION_LOGIN_RATE_LIMIT_WINDOW_SEC, 60, 10, 600);
}

function asBool(raw: string | undefined, fallback: boolean): boolean {
  const value = String(raw || "")
    .trim()
    .toLowerCase();
  if (!value) return fallback;
  if (["1", "true", "yes", "on"].includes(value)) return true;
  if (["0", "false", "no", "off"].includes(value)) return false;
  return fallback;
}

function keyMode(): "global" | "ip" {
  const value = String(process.env.SESSION_LOGIN_RATE_LIMIT_KEY_MODE || "")
    .trim()
    .toLowerCase();
  if (value === "ip") return "ip";
  return "global";
}

function trustProxyHeaders(): boolean {
  return asBool(process.env.SESSION_TRUST_PROXY_HEADERS, false);
}

function normalizedKeyPart(raw: string, maxLen: number): string {
  return String(raw || "")
    .trim()
    .toLowerCase()
    .slice(0, maxLen);
}

function requestClientKey(request: NextRequest): string {
  if (keyMode() !== "ip") {
    return "global";
  }
  if (!trustProxyHeaders()) {
    return "global";
  }
  const forwardedFor = normalizedKeyPart(request.headers.get("x-forwarded-for") || "", 200);
  const forwardedIp = forwardedFor.split(",")[0]?.trim() || "";
  const realIp = normalizedKeyPart(request.headers.get("x-real-ip") || "", 120);
  const ip = forwardedIp || realIp || "global";
  return ip;
}

function state(): LoginRateLimitState {
  const root = globalThis as GlobalWithLoginRateLimit;
  if (!root[RATE_LIMIT_STATE_KEY]) {
    root[RATE_LIMIT_STATE_KEY] = {
      eventsByKey: new Map<string, number[]>()
    };
  }
  return root[RATE_LIMIT_STATE_KEY] as LoginRateLimitState;
}

function pruneAll(nowEpochSec: number, windowSeconds: number): void {
  const cutoff = nowEpochSec - windowSeconds;
  const bucketMap = state().eventsByKey;
  for (const [key, values] of bucketMap.entries()) {
    const filtered = values.filter((value) => value > cutoff);
    if (filtered.length > 0) {
      bucketMap.set(key, filtered);
    } else {
      bucketMap.delete(key);
    }
  }
}

export function checkLoginRateLimit(request: NextRequest): LoginRateLimitDecision {
  const max = maxAttempts();
  if (max <= 0) {
    return { allowed: true, retryAfterSec: 0, key: "login:disabled" };
  }

  const nowEpochSec = nowSec();
  const windowSeconds = windowSec();
  const mode = normalizedKeyPart(process.env.SESSION_AUTH_MODE || "demo", 32);
  const key = `login:${mode}:${requestClientKey(request)}`;
  const bucketMap = state().eventsByKey;

  pruneAll(nowEpochSec, windowSeconds);
  const events = bucketMap.get(key) || [];
  if (events.length >= max) {
    const oldest = events[0] || nowEpochSec;
    const retryAfterSec = Math.max(1, windowSeconds - Math.max(0, nowEpochSec - oldest));
    return { allowed: false, retryAfterSec, key };
  }

  events.push(nowEpochSec);
  bucketMap.set(key, events);
  return { allowed: true, retryAfterSec: 0, key };
}
