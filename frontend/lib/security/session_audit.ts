import { backendUrl, demoToken } from "@/lib/backend";

export type SessionAuditRecord = {
  timestamp: string;
  correlation_id: string;
  event: string;
  outcome: "allow" | "deny" | "info" | "error";
  role?: string;
  user_id?: string;
  session_id?: string;
  actor_user_id?: string;
  reason?: string;
  path?: string;
};

export type SessionAuditInput = Omit<SessionAuditRecord, "timestamp" | "correlation_id"> & {
  correlation_id?: string;
};

type SessionAuditState = {
  records: SessionAuditRecord[];
};

type GlobalWithSessionAudit = typeof globalThis & {
  __oncoai_session_audit_v1__?: SessionAuditState;
};

const AUDIT_KEY = "__oncoai_session_audit_v1__";

function maxAuditRecords(): number {
  const parsed = Number.parseInt(process.env.SESSION_AUDIT_MAX_EVENTS || "500", 10);
  if (!Number.isFinite(parsed) || parsed < 10) return 500;
  return Math.min(parsed, 10_000);
}

function sanitize(value: string | undefined, maxLen = 200): string | undefined {
  if (!value) return undefined;
  const normalized = value.trim();
  if (!normalized) return undefined;
  return normalized.slice(0, maxLen);
}

function state(): SessionAuditState {
  const root = globalThis as GlobalWithSessionAudit;
  if (!root[AUDIT_KEY]) {
    root[AUDIT_KEY] = { records: [] };
  }
  return root[AUDIT_KEY] as SessionAuditState;
}

function normalizeRole(raw: string | undefined): "admin" | "clinician" | "patient" {
  const value = String(raw || "")
    .trim()
    .toLowerCase();
  if (value === "admin" || value === "patient") return value;
  return "clinician";
}

async function persistAuditRecord(record: SessionAuditRecord): Promise<void> {
  try {
    await fetch(backendUrl("/session/audit"), {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-role": normalizeRole(record.role),
        "x-demo-token": demoToken()
      },
      body: JSON.stringify({
        event: record.event,
        outcome: record.outcome,
        correlation_id: record.correlation_id,
        role: record.role,
        user_id: record.user_id,
        session_id: record.session_id,
        actor_user_id: record.actor_user_id,
        reason: record.reason,
        path: record.path
      }),
      cache: "no-store"
    });
  } catch {
    // no-op: audit persistence failures must not break request flow
  }
}

export async function recordSessionAudit(input: SessionAuditInput): Promise<void> {
  const providedCorrelationId = sanitize(input.correlation_id, 120);
  const record: SessionAuditRecord = {
    timestamp: new Date().toISOString(),
    correlation_id: providedCorrelationId || crypto.randomUUID(),
    event: sanitize(input.event, 100) || "unknown",
    outcome: input.outcome,
    role: sanitize(input.role, 40),
    user_id: sanitize(input.user_id, 120),
    session_id: sanitize(input.session_id, 120),
    actor_user_id: sanitize(input.actor_user_id, 120),
    reason: sanitize(input.reason, 400),
    path: sanitize(input.path, 240)
  };

  const audit = state();
  audit.records.push(record);
  const extra = audit.records.length - maxAuditRecords();
  if (extra > 0) {
    audit.records.splice(0, extra);
  }

  try {
    console.info("session.audit", JSON.stringify(record));
  } catch {
    // no-op: console serialization failures must not break auth flow
  }

  await persistAuditRecord(record);
}

export function listSessionAudit(limit = 50): SessionAuditRecord[] {
  const boundedLimit = Math.max(1, Math.min(limit, 500));
  const audit = state().records;
  return audit.slice(Math.max(0, audit.length - boundedLimit)).reverse();
}
