"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import AdminDocsTab from "@/components/admin/AdminDocsTab";
import AdminImportRunsTab from "@/components/admin/AdminImportRunsTab";
import AdminReferencesTab from "@/components/admin/AdminReferencesTab";
import AdminSecurityTab from "@/components/admin/AdminSecurityTab";
import AdminSyncTab from "@/components/admin/AdminSyncTab";
import AdminTabs, { type AdminTabId } from "@/components/admin/AdminTabs";

type DocRecord = {
  doc_id: string;
  doc_version: string;
  source_set: string;
  cancer_type: string;
  language: string;
  uploaded_at: string;
  sha256?: string;
  status?: string;
  chunk_count?: number;
  source_url?: string;
  doc_kind?: "guideline" | "reference";
  updated_at?: string;
  last_error_code?: string;
  is_valid?: boolean;
  validity_reason?: string;
  official_source?: string;
};

type DrugSafetyCacheItem = {
  inn: string;
  source: string;
  status: string;
  fetched_at?: string;
  expires_at?: string;
  error_code?: string;
};

type DrugSafetyCacheSummary = {
  dictionary_entries_total: number;
  cache_entries_total: number;
  unique_cached_inn: number;
  fresh_entries: number;
  expired_entries: number;
  coverage_ratio: number;
  status_counts: Record<string, number>;
  cache_ttl_hours: number;
};

type ReindexProgress = {
  processed_docs: number;
  total_docs: number;
  last_error_code: string | null;
};

type ImportRunMessage = {
  code: string;
  message: string;
};

type CaseImportRun = {
  schema_version: string;
  import_run_id: string;
  case_id: string;
  import_profile: string;
  started_at: string;
  finished_at?: string;
  status: "SUCCESS" | "PARTIAL_SUCCESS" | "FAILED";
  confidence?: number;
  missing_required_fields: string[];
  warnings: ImportRunMessage[];
  errors: ImportRunMessage[];
};

type IngestionRun = {
  run_id: string;
  status: string;
  processed_docs: number;
  total_docs: number;
  kb_version?: string | null;
  last_error_code?: string | null;
};

type GovernanceSummary = {
  sources_total: number;
  documents_total: number;
  versions_total: number;
  disease_registry_total: number;
  latest_ingestion_runs: IngestionRun[];
};

type SessionAuditEvent = {
  timestamp: string;
  correlation_id?: string;
  event: string;
  outcome: "allow" | "deny" | "info" | "error";
  reason_group?: string;
  role?: string;
  user_id?: string;
  session_id?: string;
  actor_user_id?: string;
  reason?: string;
  path?: string;
};

type SessionAuditPayload = {
  count: number;
  limit: number;
  cursor?: string;
  next_cursor?: string;
  filters?: Record<string, string>;
  events: SessionAuditEvent[];
  revoked_session_ids_sample?: string[];
};

type SessionAuditSummary = {
  window_hours: number;
  from_ts: string;
  to_ts: string;
  total_events: number;
  unique_users: number;
  outcome_counts: Record<string, number>;
  reason_group_counts: Record<string, number>;
  top_reasons: Array<{ reason: string; count: number }>;
  top_events: Array<{ event: string; count: number }>;
  incident_level?: "none" | "low" | "medium" | "high";
  incident_score?: number;
  incident_signals?: {
    deny_rate?: number;
    error_count?: number;
    replay_detected_count?: number;
    config_error_count?: number;
    min_events_for_deny_rate_alert?: number;
  };
  alerts?: Array<{
    code: string;
    metric: string;
    level: "warn" | "critical";
    value: number;
    threshold: number;
    message: string;
  }>;
};

type SessionAuditReasonCode = {
  code: string;
  label: string;
  group: "auth" | "token" | "revocation" | "config" | "rate_limit" | "other";
  outcome?: "allow" | "deny" | "info" | "error";
  event?: string;
};

function parseJsonSafe(raw: string): Record<string, unknown> {
  try {
    return raw ? JSON.parse(raw) : {};
  } catch {
    return { error: raw || "Invalid JSON response" };
  }
}

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

type ValidationSummary = {
  total?: number;
  valid?: number;
  invalid?: number;
  needs_manual?: number;
};

function toValidationSummary(value: unknown): ValidationSummary {
  if (!value || typeof value !== "object") return {};
  const raw = value as Record<string, unknown>;
  return {
    total: Number(raw.total || 0),
    valid: Number(raw.valid || 0),
    invalid: Number(raw.invalid || 0),
    needs_manual: Number(raw.needs_manual || 0)
  };
}

function extractDocYear(docVersion: string, updatedAt: string, uploadedAt: string): string {
  const fromVersion = String(docVersion || "").match(/\b(19|20)\d{2}\b/);
  if (fromVersion) return fromVersion[0];
  const fromDate = String(updatedAt || uploadedAt || "").match(/\b(19|20)\d{2}\b/);
  return fromDate ? fromDate[0] : "";
}

function summarizeSessionReason(reason?: string): string {
  const value = String(reason || "").trim().toLowerCase();
  if (!value) return "other";
  if (value.includes("idp_") || value.includes("credentials") || value.includes("auth")) return "auth";
  if (value.includes("replay") || value.includes("refresh_rotation")) return "token";
  if (value.includes("revoked") || value.includes("forced_logout")) return "revocation";
  if (value.includes("config") || value.includes("missing")) return "config";
  if (value.includes("rate_limit")) return "rate_limit";
  return "other";
}

function incidentBadgeClass(level: string): string {
  const normalized = String(level || "")
    .trim()
    .toLowerCase();
  if (normalized === "high") return "badge critical";
  if (normalized === "medium" || normalized === "low") return "badge important";
  return "badge note";
}

const SESSION_AUDIT_REASON_CATALOG: SessionAuditReasonCode[] = [
  { code: "idp_token_missing", label: "IdP token missing", group: "auth", outcome: "deny", event: "login_rejected" },
  { code: "invalid_credentials", label: "Credentials mismatch", group: "auth", outcome: "deny", event: "login_rejected" },
  { code: "idp_alg_not_allowed", label: "IdP alg denied", group: "auth", outcome: "deny", event: "login_rejected" },
  { code: "idp_signature_invalid_rs256", label: "RS256 signature fail", group: "auth", outcome: "deny", event: "login_rejected" },
  { code: "idp_token_replay_detected", label: "Replay detected", group: "token", outcome: "deny", event: "login_rejected" },
  { code: "refresh_rotation", label: "Refresh rotated", group: "token", outcome: "info", event: "session_refresh_rotated" },
  { code: "session_revoked", label: "Session revoked", group: "revocation", outcome: "deny", event: "session_rejected" },
  { code: "forced_logout", label: "Forced logout", group: "revocation", outcome: "deny", event: "session_rejected" },
  { code: "idp_config_incomplete", label: "IdP config incomplete", group: "config", outcome: "error", event: "login_error" },
  { code: "credentials_mode_without_users", label: "Users config empty", group: "config", outcome: "error", event: "login_error" },
  { code: "rate_limit_exceeded", label: "Rate limit exceeded", group: "rate_limit", outcome: "deny" },
  { code: "unknown", label: "Unknown", group: "other", outcome: "info" }
];

const ADMIN_TAB_QUERY: Record<AdminTabId, string> = {
  docs: "tab=docs",
  references: "tab=references",
  sync: "tab=sync",
  import: "tab=import",
  security: "tab=security"
};

function resolveAdminTab(raw: string | null): AdminTabId {
  if (raw === "sync" || raw === "import" || raw === "security" || raw === "references") return raw;
  return "docs";
}

function AdminPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const activeTab = resolveAdminTab(searchParams.get("tab"));

  const [docs, setDocs] = useState<DocRecord[]>([]);
  const [kbVersion, setKbVersion] = useState<string>("kb_empty");
  const [status, setStatus] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [reindexJobId, setReindexJobId] = useState("");
  const [reindexPoll, setReindexPoll] = useState(0);
  const [reindexProgress, setReindexProgress] = useState<ReindexProgress | null>(null);
  const [governance, setGovernance] = useState<GovernanceSummary | null>(null);
  const [importRuns, setImportRuns] = useState<CaseImportRun[]>([]);
  const [importRunsLoading, setImportRunsLoading] = useState(false);
  const [importRunsError, setImportRunsError] = useState("");
  const [selectedImportRunId, setSelectedImportRunId] = useState("");
  const [selectedImportRun, setSelectedImportRun] = useState<CaseImportRun | null>(null);
  const [importRunLoading, setImportRunLoading] = useState(false);
  const [importRetrying, setImportRetrying] = useState(false);
  const [sessionAudit, setSessionAudit] = useState<SessionAuditPayload | null>(null);
  const [sessionAuditSummary, setSessionAuditSummary] = useState<SessionAuditSummary | null>(null);
  const [sessionAuditLoading, setSessionAuditLoading] = useState(false);
  const [sessionAuditSummaryLoading, setSessionAuditSummaryLoading] = useState(false);
  const [sessionAuditError, setSessionAuditError] = useState("");
  const [sessionAuditLimit, setSessionAuditLimit] = useState("50");
  const [sessionAuditOutcome, setSessionAuditOutcome] = useState("");
  const [sessionAuditReasonGroup, setSessionAuditReasonGroup] = useState("");
  const [sessionAuditEvent, setSessionAuditEvent] = useState("");
  const [sessionAuditReason, setSessionAuditReason] = useState("");
  const [sessionAuditUserId, setSessionAuditUserId] = useState("");
  const [sessionAuditCorrelationId, setSessionAuditCorrelationId] = useState("");
  const [sessionAuditFromTs, setSessionAuditFromTs] = useState("");
  const [sessionAuditToTs, setSessionAuditToTs] = useState("");
  const [sessionAuditCursor, setSessionAuditCursor] = useState("");
  const [sessionAuditNextCursor, setSessionAuditNextCursor] = useState("");
  const [sessionAuditExporting, setSessionAuditExporting] = useState(false);
  const [sessionAuditExportMaxEvents, setSessionAuditExportMaxEvents] = useState("1000");
  const [forceLogoutUserId, setForceLogoutUserId] = useState("");
  const [forceLogoutStatus, setForceLogoutStatus] = useState("");
  const [forceLogoutLoading, setForceLogoutLoading] = useState(false);
  const [docsSourceFilter, setDocsSourceFilter] = useState("");
  const [docsYearFilter, setDocsYearFilter] = useState("");
  const [docsStatusFilter, setDocsStatusFilter] = useState("");
  const [docsNosologyFilter, setDocsNosologyFilter] = useState("");
  const [showInvalidDocs, setShowInvalidDocs] = useState(false);
  const [cleanupBusy, setCleanupBusy] = useState(false);
  const [drugDictionaryFile, setDrugDictionaryFile] = useState<File | null>(null);
  const [drugWarmupInns, setDrugWarmupInns] = useState("");
  const [drugSafetyCacheItems, setDrugSafetyCacheItems] = useState<DrugSafetyCacheItem[]>([]);
  const [drugSafetyCacheSummary, setDrugSafetyCacheSummary] = useState<DrugSafetyCacheSummary | null>(null);

  const [meta, setMeta] = useState({
    doc_id: "guideline_nsclc_ru",
    doc_version: "2025-11",
    source_set: "mvp_guidelines_ru_2025",
    cancer_type: "nsclc_egfr",
    language: "ru",
    source_url: "",
    doc_kind: "guideline" as "guideline" | "reference"
  });

  const setTab = useCallback(
    (tab: AdminTabId) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("tab", tab);
      router.replace(`/admin?${params.toString()}`);
    },
    [router, searchParams]
  );

  const loadDocs = useCallback(async (validOnly = true, kind: "guideline" | "reference" | "all" = "all") => {
    const query = validOnly ? "true" : "false";
    const res = await fetch(`/api/admin/docs?valid_only=${query}&kind=${encodeURIComponent(kind)}`);
    const raw = await res.text();
    const data = parseJsonSafe(raw);
    if (res.ok) {
      setDocs((data.docs as DocRecord[]) || []);
      setKbVersion((data.kb_version as string) || "kb_empty");
      setGovernance((data.governance as GovernanceSummary) || null);
      setError("");
    } else {
      setError((data.error as string) || `HTTP ${res.status}`);
    }
  }, []);

  const loadDrugSafetyCache = useCallback(async (limit = 200) => {
    const safeLimit = Math.max(1, Math.min(limit, 5000));
    const res = await fetch(`/api/admin/drug-safety/cache?limit=${safeLimit}`, {
      cache: "no-store"
    });
    const raw = await res.text();
    const data = parseJsonSafe(raw);
    if (!res.ok) {
      setError((data.error as string) || `HTTP ${res.status}`);
      return;
    }
    const items = (Array.isArray(data.items) ? data.items : []) as DrugSafetyCacheItem[];
    const summaryRaw = (data.summary as Record<string, unknown>) || {};
    setDrugSafetyCacheItems(items);
    setDrugSafetyCacheSummary({
      dictionary_entries_total: Number(summaryRaw.dictionary_entries_total || 0),
      cache_entries_total: Number(summaryRaw.cache_entries_total || 0),
      unique_cached_inn: Number(summaryRaw.unique_cached_inn || 0),
      fresh_entries: Number(summaryRaw.fresh_entries || 0),
      expired_entries: Number(summaryRaw.expired_entries || 0),
      coverage_ratio: Number(summaryRaw.coverage_ratio || 0),
      status_counts:
        typeof summaryRaw.status_counts === "object" && summaryRaw.status_counts !== null
          ? (summaryRaw.status_counts as Record<string, number>)
          : {},
      cache_ttl_hours: Number(summaryRaw.cache_ttl_hours || 0)
    });
  }, []);

  const loadImportRuns = useCallback(async (limit = 20) => {
    setImportRunsLoading(true);
    setImportRunsError("");
    try {
      const res = await fetch(`/api/case/import/runs?limit=${limit}`, {
        cache: "no-store"
      });
      const raw = await res.text();
      const data = parseJsonSafe(raw);
      if (!res.ok) {
        setImportRunsError((data.error as string) || `HTTP ${res.status}`);
        setImportRuns([]);
        return;
      }
      const runs = (data.runs as CaseImportRun[]) || [];
      setImportRuns(runs);
      if (!selectedImportRunId && runs.length > 0) {
        setSelectedImportRunId(runs[0].import_run_id);
      }
    } catch (err) {
      setImportRuns([]);
      setImportRunsError(err instanceof Error ? err.message : "Failed to load case import runs");
    } finally {
      setImportRunsLoading(false);
    }
  }, [selectedImportRunId]);

  const loadImportRunDetails = useCallback(async (importRunId: string) => {
    if (!importRunId) {
      setSelectedImportRun(null);
      return;
    }
    setImportRunLoading(true);
    try {
      const res = await fetch(`/api/case/import/${encodeURIComponent(importRunId)}`, {
        cache: "no-store"
      });
      const raw = await res.text();
      const data = parseJsonSafe(raw);
      if (!res.ok) {
        setSelectedImportRun(null);
        setImportRunsError((data.error as string) || `HTTP ${res.status}`);
        return;
      }
      setSelectedImportRun(data as unknown as CaseImportRun);
    } catch (err) {
      setSelectedImportRun(null);
      setImportRunsError(err instanceof Error ? err.message : "Failed to load case import run details");
    } finally {
      setImportRunLoading(false);
    }
  }, []);

  const loadSessionAudit = useCallback(
    async (filters?: {
      limit?: string;
      outcome?: string;
      reason_group?: string;
      event?: string;
      reason?: string;
      user_id?: string;
      correlation_id?: string;
      from_ts?: string;
      to_ts?: string;
      cursor?: string;
    }) => {
      setSessionAuditLoading(true);
      setSessionAuditError("");
      try {
        const params = new URLSearchParams();
        const limitRaw = Number.parseInt(filters?.limit || "50", 10);
        const limit = Number.isFinite(limitRaw) ? Math.max(1, Math.min(limitRaw, 200)) : 50;
        params.set("limit", String(limit));
        if ((filters?.outcome || "").trim()) params.set("outcome", String(filters?.outcome || "").trim());
        if ((filters?.reason_group || "").trim()) {
          params.set("reason_group", String(filters?.reason_group || "").trim());
        }
        if ((filters?.event || "").trim()) params.set("event", String(filters?.event || "").trim());
        if ((filters?.reason || "").trim()) params.set("reason", String(filters?.reason || "").trim());
        if ((filters?.user_id || "").trim()) params.set("user_id", String(filters?.user_id || "").trim());
        if ((filters?.correlation_id || "").trim()) {
          params.set("correlation_id", String(filters?.correlation_id || "").trim());
        }
        if ((filters?.from_ts || "").trim()) params.set("from_ts", String(filters?.from_ts || "").trim());
        if ((filters?.to_ts || "").trim()) params.set("to_ts", String(filters?.to_ts || "").trim());
        if ((filters?.cursor || "").trim()) params.set("cursor", String(filters?.cursor || "").trim());
        const res = await fetch(`/api/session/audit?${params.toString()}`, {
          cache: "no-store"
        });
        const raw = await res.text();
        const data = parseJsonSafe(raw);
        if (!res.ok) {
          setSessionAudit(null);
          setSessionAuditError((data.error as string) || `HTTP ${res.status}`);
          return;
        }
        const payload = data as unknown as SessionAuditPayload;
        setSessionAudit(payload);
        setSessionAuditCursor(String(filters?.cursor || ""));
        setSessionAuditNextCursor(String(payload.next_cursor || ""));
      } catch (err) {
        setSessionAudit(null);
        setSessionAuditError(err instanceof Error ? err.message : "Failed to load session audit");
      } finally {
        setSessionAuditLoading(false);
      }
    },
    []
  );

  const loadSessionAuditSummary = useCallback(async (windowHours = 24) => {
    setSessionAuditSummaryLoading(true);
    setSessionAuditError("");
    try {
      const safeWindow = Math.max(1, Math.min(windowHours, 168));
      const res = await fetch(`/api/session/audit/summary?window_hours=${safeWindow}`, {
        cache: "no-store"
      });
      const raw = await res.text();
      const data = parseJsonSafe(raw);
      if (!res.ok) {
        setSessionAuditSummary(null);
        setSessionAuditError((data.error as string) || `HTTP ${res.status}`);
        return;
      }
      setSessionAuditSummary(data as unknown as SessionAuditSummary);
    } catch (err) {
      setSessionAuditSummary(null);
      setSessionAuditError(err instanceof Error ? err.message : "Failed to load session audit summary");
    } finally {
      setSessionAuditSummaryLoading(false);
    }
  }, []);

  const applyReasonCodeChip = useCallback(
    async (item: SessionAuditReasonCode) => {
      const nextOutcome = item.outcome || sessionAuditOutcome;
      const nextEvent = item.event || sessionAuditEvent;
      const nextReasonGroup = item.group || sessionAuditReasonGroup;
      setSessionAuditReason(item.code);
      setSessionAuditOutcome(nextOutcome);
      setSessionAuditEvent(nextEvent);
      setSessionAuditReasonGroup(nextReasonGroup);
      setSessionAuditCursor("");
      await loadSessionAudit({
        limit: sessionAuditLimit,
        outcome: nextOutcome,
        reason_group: nextReasonGroup,
        event: nextEvent,
        reason: item.code,
        user_id: sessionAuditUserId,
        correlation_id: sessionAuditCorrelationId,
        from_ts: sessionAuditFromTs,
        to_ts: sessionAuditToTs,
        cursor: ""
      });
    },
    [
      loadSessionAudit,
      sessionAuditCorrelationId,
      sessionAuditEvent,
      sessionAuditFromTs,
      sessionAuditLimit,
      sessionAuditOutcome,
      sessionAuditReasonGroup,
      sessionAuditToTs,
      sessionAuditUserId
    ]
  );

  const applyCorrelationDrilldown = useCallback(
    async (correlationId: string) => {
      const value = String(correlationId || "").trim();
      if (!value) return;
      setSessionAuditCorrelationId(value);
      setSessionAuditCursor("");
      await loadSessionAudit({
        limit: sessionAuditLimit,
        outcome: sessionAuditOutcome,
        reason_group: sessionAuditReasonGroup,
        event: sessionAuditEvent,
        reason: sessionAuditReason,
        user_id: sessionAuditUserId,
        correlation_id: value,
        from_ts: sessionAuditFromTs,
        to_ts: sessionAuditToTs,
        cursor: ""
      });
    },
    [
      loadSessionAudit,
      sessionAuditEvent,
      sessionAuditFromTs,
      sessionAuditLimit,
      sessionAuditOutcome,
      sessionAuditReason,
      sessionAuditReasonGroup,
      sessionAuditToTs,
      sessionAuditUserId
    ]
  );

  useEffect(() => {
    Promise.all([
      loadDocs(!showInvalidDocs),
      loadImportRuns(),
      loadSessionAudit({ limit: "50", cursor: "" }),
      loadSessionAuditSummary(24),
      loadDrugSafetyCache(200)
    ]).catch((err) => setStatus(err.message));
  }, [loadDocs, loadDrugSafetyCache, loadImportRuns, loadSessionAudit, loadSessionAuditSummary, showInvalidDocs]);

  useEffect(() => {
    loadImportRunDetails(selectedImportRunId).catch((err) => {
      setImportRunsError(err instanceof Error ? err.message : "Failed to load case import run details");
    });
  }, [loadImportRunDetails, selectedImportRunId]);

  async function forceLogoutUser() {
    const target = forceLogoutUserId.trim();
    if (!target) {
      setForceLogoutStatus("Enter user_id before force logout.");
      return;
    }
    setForceLogoutLoading(true);
    setForceLogoutStatus("");
    setSessionAuditError("");
    try {
      const res = await fetch("/api/session/revoke", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          scope: "user",
          user_id: target
        })
      });
      const raw = await res.text();
      const data = parseJsonSafe(raw);
      if (!res.ok) {
        setForceLogoutStatus((data.error as string) || `HTTP ${res.status}`);
        return;
      }
      const forcedAfter = Number(data.forced_logout_after || 0);
      setForceLogoutStatus(
        `Forced logout set for user_id=${target}${forcedAfter > 0 ? `, forced_after=${forcedAfter}` : ""}`
      );
      await loadSessionAudit({
        limit: sessionAuditLimit,
        outcome: sessionAuditOutcome,
        reason_group: sessionAuditReasonGroup,
        event: sessionAuditEvent,
        reason: sessionAuditReason,
        user_id: sessionAuditUserId,
        correlation_id: sessionAuditCorrelationId,
        from_ts: sessionAuditFromTs,
        to_ts: sessionAuditToTs,
        cursor: sessionAuditCursor
      });
      await loadSessionAuditSummary(24);
    } catch (err) {
      setForceLogoutStatus(err instanceof Error ? err.message : "Failed to force logout user");
    } finally {
      setForceLogoutLoading(false);
    }
  }

  async function exportSessionAudit(format: "json" | "csv") {
    setSessionAuditError("");
    setSessionAuditExporting(true);
    try {
      const params = new URLSearchParams();
      const limitRaw = Number.parseInt(sessionAuditLimit || "200", 10);
      const limit = Number.isFinite(limitRaw) ? Math.max(1, Math.min(limitRaw, 500)) : 200;
      const exportMaxEventsRaw = Number.parseInt(sessionAuditExportMaxEvents || "1000", 10);
      const exportMaxEvents = Number.isFinite(exportMaxEventsRaw)
        ? Math.max(1, Math.min(exportMaxEventsRaw, 5000))
        : 1000;
      params.set("format", format);
      params.set("all", "1");
      params.set("limit", String(limit));
      params.set("max_events", String(exportMaxEvents));
      if (sessionAuditOutcome.trim()) params.set("outcome", sessionAuditOutcome.trim());
      if (sessionAuditReasonGroup.trim()) params.set("reason_group", sessionAuditReasonGroup.trim());
      if (sessionAuditEvent.trim()) params.set("event", sessionAuditEvent.trim());
      if (sessionAuditReason.trim()) params.set("reason", sessionAuditReason.trim());
      if (sessionAuditUserId.trim()) params.set("user_id", sessionAuditUserId.trim());
      if (sessionAuditCorrelationId.trim()) params.set("correlation_id", sessionAuditCorrelationId.trim());
      if (sessionAuditFromTs.trim()) params.set("from_ts", sessionAuditFromTs.trim());
      if (sessionAuditToTs.trim()) params.set("to_ts", sessionAuditToTs.trim());

      const res = await fetch(`/api/session/audit/export?${params.toString()}`, {
        cache: "no-store"
      });
      if (!res.ok) {
        const raw = await res.text();
        const data = parseJsonSafe(raw);
        setSessionAuditError((data.error as string) || `HTTP ${res.status}`);
        return;
      }

      const blob = await res.blob();
      const fallback = `session_audit_export.${format}`;
      const disposition = String(res.headers.get("content-disposition") || "");
      const match = disposition.match(/filename="?([^"]+)"?/i);
      const filename = match?.[1] ? match[1] : fallback;
      const exportMaxEventsHeader = String(
        res.headers.get("x-onco-export-max-events") || String(exportMaxEvents)
      ).trim();
      const exportTruncated = String(res.headers.get("x-onco-export-truncated") || "").trim() === "1";
      const exportTruncatedReason = String(res.headers.get("x-onco-export-truncated-reason") || "").trim();

      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(objectUrl);
      setStatus(
        `Session audit export ready: ${filename}` +
          ` (max_events=${exportMaxEventsHeader}` +
          `${exportTruncated ? `, truncated=${exportTruncatedReason || "unknown"}` : ""})`
      );
    } catch (err) {
      setSessionAuditError(err instanceof Error ? err.message : "Failed to export session audit");
    } finally {
      setSessionAuditExporting(false);
    }
  }

  async function retryImportFromCase(run: CaseImportRun) {
    setImportRunsError("");
    setImportRetrying(true);
    try {
      const caseRes = await fetch(`/api/case/${encodeURIComponent(run.case_id)}`, {
        cache: "no-store"
      });
      const caseRaw = await caseRes.text();
      const casePayload = parseJsonSafe(caseRaw);
      if (!caseRes.ok) {
        setImportRunsError(
          `Retry failed: cannot load case ${run.case_id} (${(casePayload.error as string) || `HTTP ${caseRes.status}`})`
        );
        return;
      }

      const payload = {
        schema_version: "1.0",
        import_profile: run.import_profile,
        case_id: run.case_id,
        case_json: casePayload
      };
      const retryRes = await fetch("/api/case/import", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload)
      });
      const retryRaw = await retryRes.text();
      const retryData = parseJsonSafe(retryRaw);
      if (!retryRes.ok) {
        setImportRunsError((retryData.error as string) || `HTTP ${retryRes.status}`);
        return;
      }

      const newRunId = String(retryData.import_run_id || "");
      setStatus(`Case import retry done. run_id=${newRunId || "n/a"}, case_id=${run.case_id}`);
      await loadImportRuns();
      if (newRunId) {
        setSelectedImportRunId(newRunId);
      }
    } catch (err) {
      setImportRunsError(err instanceof Error ? err.message : "Retry failed");
    } finally {
      setImportRetrying(false);
    }
  }

  function summarizeRunMessage(run: CaseImportRun): string {
    if (run.errors.length > 0) return `error=${run.errors[0].code}`;
    if (run.warnings.length > 0) return `warn=${run.warnings[0].code}`;
    return "ok";
  }

  async function upload() {
    if (!file) {
      setStatus("Choose PDF first.");
      return;
    }
    setError("");
    const form = new FormData();
    form.append("file", file);
    form.append("doc_id", meta.doc_id);
    form.append("doc_version", meta.doc_version);
    form.append("source_set", meta.source_set);
    form.append("cancer_type", meta.cancer_type);
    form.append("language", meta.language);
    form.append("source_url", meta.source_url);
    form.append("doc_kind", meta.doc_kind);

    setLoading(true);
    setStatus("Uploading...");
    const res = await fetch("/api/admin/upload", {
      method: "POST",
      body: form
    });
    const raw = await res.text();
    const data = parseJsonSafe(raw);
    setLoading(false);
    if (!res.ok) {
      setError((data.error as string) || `HTTP ${res.status}`);
      return;
    }
    setStatus(`Uploaded ${String(data.doc_id)}:${String(data.doc_version)}`);
    await loadDocs(!showInvalidDocs);
  }

  async function uploadDrugDictionary() {
    if (!drugDictionaryFile) {
      setStatus("Выберите JSON словарь препаратов.");
      return;
    }
    setError("");
    setLoading(true);
    setStatus("Загрузка drug dictionary...");
    try {
      const form = new FormData();
      form.append("file", drugDictionaryFile);
      const res = await fetch("/api/admin/references/drug-dictionary/load", {
        method: "POST",
        body: form
      });
      const raw = await res.text();
      const data = parseJsonSafe(raw);
      if (!res.ok) {
        setError((data.error as string) || `HTTP ${res.status}`);
        return;
      }
      setStatus(
        `Drug dictionary загружен: version=${String(data.version || "")}, entries=${String(
          data.entries_loaded || 0
        )}, regimens=${String(data.regimens_loaded || 0)}`
      );
      setDrugDictionaryFile(null);
      await loadDrugSafetyCache(200);
    } finally {
      setLoading(false);
    }
  }

  async function warmupDrugSafetyCache() {
    setError("");
    const inns = drugWarmupInns
      .split(",")
      .map((item) => item.trim().toLowerCase())
      .filter((item) => item.length > 0);
    setLoading(true);
    setStatus("Warmup drug safety cache...");
    try {
      const res = await fetch("/api/admin/drug-safety/cache/warmup", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(inns.length > 0 ? { inns } : {})
      });
      const raw = await res.text();
      const data = parseJsonSafe(raw);
      if (!res.ok) {
        setError((data.error as string) || `HTTP ${res.status}`);
        return;
      }
      setStatus(
        `Warmup завершён: status=${String(data.status || "unknown")}, profiles=${String(
          data.profiles || 0
        )}, requested=${String(data.requested || 0)}`
      );
      await loadDrugSafetyCache(200);
    } finally {
      setLoading(false);
    }
  }

  async function reindex() {
    setError("");
    setLoading(true);
    setStatus("Reindex started...");
    setReindexPoll(0);
    setReindexProgress(null);
    const start = await fetch("/api/admin/reindex", {
      method: "POST"
    });
    const startRaw = await start.text();
    const startData = parseJsonSafe(startRaw);
    if (!start.ok) {
      setLoading(false);
      setError((startData.error as string) || `HTTP ${start.status}`);
      return;
    }
    const jobId = String(startData.job_id || "");
    if (!jobId) {
      setLoading(false);
      setError("No job_id returned from /admin/reindex");
      return;
    }
    setReindexJobId(jobId);

    for (let attempt = 1; attempt <= 25; attempt += 1) {
      setReindexPoll(attempt);
      const statusRes = await fetch(`/api/admin/reindex/${jobId}`, {
        cache: "no-store"
      });
      const statusRaw = await statusRes.text();
      const statusData = parseJsonSafe(statusRaw);
      if (!statusRes.ok) {
        setLoading(false);
        setError((statusData.error as string) || `HTTP ${statusRes.status}`);
        return;
      }

      const state = String(statusData.status || "unknown");
      const kb = String(statusData.kb_version || kbVersion);
      const processedDocs = Number(statusData.processed_docs || 0);
      const totalDocs = Number(statusData.total_docs || 0);
      const lastErrorCode = statusData.last_error_code ? String(statusData.last_error_code) : null;
      setReindexProgress({
        processed_docs: processedDocs,
        total_docs: totalDocs,
        last_error_code: lastErrorCode
      });
      setStatus(`Reindex ${state} ${processedDocs}/${totalDocs} (poll ${attempt}/25). kb_version=${kb}`);
      if (state === "done") {
        setLoading(false);
        await loadDocs(!showInvalidDocs);
        return;
      }
      if (state === "failed") {
        setLoading(false);
        setError(`Reindex failed for job ${jobId}${lastErrorCode ? ` (${lastErrorCode})` : ""}`);
        return;
      }
      await sleep(800);
    }

    setLoading(false);
    setError(`Reindex timeout for job ${jobId}. Use Retry.`);
  }

  async function postAdminAction(endpoint: string, body?: Record<string, unknown>) {
    setError("");
    setLoading(true);
    try {
      const res = await fetch(endpoint, {
        method: "POST",
        headers: body ? { "content-type": "application/json" } : undefined,
        body: body ? JSON.stringify(body) : undefined
      });
      const raw = await res.text();
      const data = parseJsonSafe(raw);
      if (!res.ok) {
        setError((data.error as string) || `HTTP ${res.status}`);
        return null;
      }
      return data;
    } finally {
      setLoading(false);
    }
  }

  async function syncRussco() {
    setStatus("Синхронизация RUSSCO запущена...");
    const payload = await postAdminAction("/api/admin/sync/russco");
    if (!payload) return;
    const summary = toValidationSummary(payload.validation_summary);
    setStatus(
      `RUSSCO sync: статус=${String(payload.status || "ok")}, загружено=${String(payload.count || 0)}, валидно=${String(summary.valid || 0)}, manual=${String(summary.needs_manual || 0)}, невалидно=${String(summary.invalid || 0)}`
    );
    await loadDocs(!showInvalidDocs);
  }

  async function syncMinzdrav() {
    setStatus("Синхронизация Минздрава запущена...");
    const payload = await postAdminAction("/api/admin/sync/minzdrav");
    if (!payload) return;
    const summary = toValidationSummary(payload.validation_summary);
    setStatus(
      `Минздрав sync: статус=${String(payload.status || "ok")}, загружено=${String(payload.count || 0)}, валидно=${String(summary.valid || 0)}, manual=${String(summary.needs_manual || 0)}, невалидно=${String(summary.invalid || 0)}`
    );
    await loadDocs(!showInvalidDocs);
  }

  async function cleanupInvalidDocs(applyMode: boolean) {
    if (applyMode) {
      const confirmed = window.confirm("Удалить/архивировать невалидные документы из каталога?");
      if (!confirmed) return;
    }
    setCleanupBusy(true);
    setStatus(applyMode ? "Очистка невалидных документов (apply)..." : "Проверка очистки (dry-run)...");
    try {
      const payload = await postAdminAction("/api/admin/docs/cleanup-invalid", {
        dry_run: !applyMode,
        apply: applyMode
      });
      if (!payload) return;
      const candidates = Array.isArray(payload.candidates) ? payload.candidates.length : 0;
      const deletedCount = Number(payload.deleted_count || 0);
      const errorCount = Number(payload.error_count || 0);
      setStatus(
        `${applyMode ? "Очистка" : "Dry-run"}: кандидатов=${candidates}, удалено=${deletedCount}, ошибок=${errorCount}`
      );
      await loadDocs(!showInvalidDocs);
    } finally {
      setCleanupBusy(false);
    }
  }

  async function docRechunk(doc: DocRecord) {
    setStatus(`Re-chunk ${doc.doc_id}:${doc.doc_version}...`);
    const endpoint = `/api/admin/docs/${encodeURIComponent(doc.doc_id)}/${encodeURIComponent(doc.doc_version)}/rechunk`;
    const payload = await postAdminAction(endpoint);
    if (!payload) return;
    setStatus(`${doc.doc_id}:${doc.doc_version} -> ${String(payload.status || "PENDING_APPROVAL")}`);
    await loadDocs(!showInvalidDocs);
  }

  async function docApprove(doc: DocRecord) {
    setStatus(`Approve ${doc.doc_id}:${doc.doc_version}...`);
    const endpoint = `/api/admin/docs/${encodeURIComponent(doc.doc_id)}/${encodeURIComponent(doc.doc_version)}/approve`;
    const payload = await postAdminAction(endpoint);
    if (!payload) return;
    setStatus(`${doc.doc_id}:${doc.doc_version} -> ${String(payload.status || "APPROVED")}`);
    await loadDocs(!showInvalidDocs);
  }

  async function docReject(doc: DocRecord) {
    const reason = window.prompt(`Причина отклонения для ${doc.doc_id}:${doc.doc_version}`, "") || "";
    setStatus(`Reject ${doc.doc_id}:${doc.doc_version}...`);
    const endpoint = `/api/admin/docs/${encodeURIComponent(doc.doc_id)}/${encodeURIComponent(doc.doc_version)}/reject`;
    const payload = await postAdminAction(endpoint, reason.trim() ? { reason: reason.trim() } : undefined);
    if (!payload) return;
    setStatus(`${doc.doc_id}:${doc.doc_version} -> ${String(payload.status || "REJECTED")}`);
    await loadDocs(!showInvalidDocs);
  }

  async function docIndex(doc: DocRecord) {
    if (String(doc.status || "").toUpperCase() !== "APPROVED") return;
    setStatus(`Index ${doc.doc_id}:${doc.doc_version}...`);
    const endpoint = `/api/admin/docs/${encodeURIComponent(doc.doc_id)}/${encodeURIComponent(doc.doc_version)}/index`;
    const payload = await postAdminAction(endpoint);
    if (!payload) return;
    setStatus(`${doc.doc_id}:${doc.doc_version} -> ${String(payload.status || "INDEXED")}`);
    await loadDocs(!showInvalidDocs);
  }

  async function docVerifyIndex(doc: DocRecord) {
    setStatus(`Verify index ${doc.doc_id}:${doc.doc_version}...`);
    const endpoint = `/api/admin/docs/${encodeURIComponent(doc.doc_id)}/${encodeURIComponent(doc.doc_version)}/verify-index`;
    const payload = await postAdminAction(endpoint);
    if (!payload) return;
    setStatus(
      `${doc.doc_id}:${doc.doc_version} verify=${String(payload.status || "unknown")} ` +
        `sqlite=${String(payload.sqlite_chunk_count || 0)} qdrant=${String(payload.qdrant_point_count || 0)} ` +
        `backend=${String(payload.vector_backend || "local")}`
    );
    await loadDocs(!showInvalidDocs);
  }

  function openDocPdf(doc: DocRecord) {
    const endpoint = `/api/admin/docs/${encodeURIComponent(doc.doc_id)}/${encodeURIComponent(doc.doc_version)}/pdf`;
    window.open(endpoint, "_blank", "noopener,noreferrer");
  }

  const sourceOptions = Array.from(new Set(docs.map((doc) => String(doc.source_set || "").trim()).filter(Boolean))).sort();
  const yearOptions = Array.from(
    new Set(docs.map((doc) => extractDocYear(doc.doc_version, String(doc.updated_at || ""), doc.uploaded_at)).filter(Boolean))
  ).sort();
  const statusOptions = Array.from(new Set(docs.map((doc) => String(doc.status || "").trim()).filter(Boolean))).sort();
  const nosologyOptions = Array.from(new Set(docs.map((doc) => String(doc.cancer_type || "").trim()).filter(Boolean))).sort();

  const filteredDocs = docs.filter((doc) => {
    if (String(doc.doc_kind || "guideline") !== "guideline") return false;
    if (docsSourceFilter && String(doc.source_set || "") !== docsSourceFilter) return false;
    if (docsStatusFilter && String(doc.status || "") !== docsStatusFilter) return false;
    if (docsNosologyFilter && String(doc.cancer_type || "") !== docsNosologyFilter) return false;
    if (docsYearFilter) {
      const docYear = extractDocYear(doc.doc_version, String(doc.updated_at || ""), doc.uploaded_at);
      if (docYear !== docsYearFilter) return false;
    }
    return true;
  });
  const references = docs.filter((doc) => String(doc.doc_kind || "guideline") === "reference");

  return (
    <>
      <div className="card hero-card">
        <div className="section-head">
          <div>
            <h1>Админ-панель</h1>
            <p className="muted">Загрузка источников, sync, статусный approve/index workflow.</p>
          </div>
        </div>
        <div className="grid two">
          <label>
            doc_id
            <input value={meta.doc_id} onChange={(event) => setMeta({ ...meta, doc_id: event.target.value })} />
          </label>
          <label>
            doc_version
            <input
              value={meta.doc_version}
              onChange={(event) => setMeta({ ...meta, doc_version: event.target.value })}
            />
          </label>
          <label>
            source_set
            <input
              value={meta.source_set}
              onChange={(event) => setMeta({ ...meta, source_set: event.target.value })}
            />
          </label>
          <label>
            cancer_type
            <input
              value={meta.cancer_type}
              onChange={(event) => setMeta({ ...meta, cancer_type: event.target.value })}
            />
          </label>
          <label>
            source_url
            <input
              value={meta.source_url}
              onChange={(event) => setMeta({ ...meta, source_url: event.target.value })}
              placeholder="https://..."
            />
          </label>
          <label>
            doc_kind
            <select
              value={meta.doc_kind}
              onChange={(event) => setMeta({ ...meta, doc_kind: event.target.value as "guideline" | "reference" })}
            >
              <option value="guideline">guideline</option>
              <option value="reference">reference</option>
            </select>
          </label>
        </div>
        <div style={{ marginTop: 8 }}>
          <input type="file" accept="application/pdf" onChange={(event) => setFile(event.target.files?.[0] || null)} />
        </div>
        <div className="action-row" style={{ marginTop: 8 }}>
          <button disabled={loading} onClick={upload}>
            Загрузить
          </button>
          <button className="secondary" disabled={loading} onClick={syncRussco}>
            Sync RUSSCO
          </button>
          <button className="secondary" disabled={loading} onClick={syncMinzdrav}>
            Sync Минздрав
          </button>
          <button className="secondary" disabled={loading} onClick={reindex}>
            Reindex
          </button>
          <button className="secondary" disabled={loading || !reindexJobId} onClick={reindex}>
            Retry
          </button>
        </div>
        {reindexJobId && (
          <p className="muted">
            reindex_job_id: {reindexJobId} (poll={reindexPoll})
          </p>
        )}
        {reindexProgress && (
          <p className="muted">
            progress: {reindexProgress.processed_docs}/{reindexProgress.total_docs}
            {reindexProgress.last_error_code ? `, last_error_code=${reindexProgress.last_error_code}` : ""}
          </p>
        )}
        {status && <p className="muted">{status}</p>}
        {error && <p className="error">{error}</p>}
      </div>

      <div className="card" data-testid="admin-layout">
        <AdminTabs activeTab={activeTab} onChange={setTab} />
        <p className="muted">
          Быстрые ссылки: {ADMIN_TAB_QUERY.docs}, {ADMIN_TAB_QUERY.references}, {ADMIN_TAB_QUERY.sync}, {ADMIN_TAB_QUERY.import}, {ADMIN_TAB_QUERY.security}
        </p>
      </div>

      <AdminDocsTab active={activeTab === "docs"}>
      <div className="card">
        <div className="section-head">
          <h3>Документы</h3>
          <div className="action-row">
            <button className="secondary" disabled={cleanupBusy || loading} onClick={() => cleanupInvalidDocs(false)}>
              Dry-run очистки
            </button>
            <button className="secondary" disabled={cleanupBusy || loading} onClick={() => cleanupInvalidDocs(true)}>
              Применить очистку
            </button>
          </div>
        </div>
        <p className="muted">kb_version: {kbVersion}</p>
        <label style={{ maxWidth: 360 }}>
          Режим отображения документов
          <select
            value={showInvalidDocs ? "all" : "valid"}
            onChange={async (event) => {
              const all = event.target.value === "all";
              setShowInvalidDocs(all);
              await loadDocs(!all);
            }}
          >
            <option value="valid">Только валидные (релиз)</option>
            <option value="all">Все (включая невалидные)</option>
          </select>
        </label>
        <div className="grid two" style={{ marginBottom: 10 }}>
          <label>
            Источник
            <select value={docsSourceFilter} onChange={(event) => setDocsSourceFilter(event.target.value)}>
              <option value="">Все</option>
              {sourceOptions.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
          <label>
            Год
            <select value={docsYearFilter} onChange={(event) => setDocsYearFilter(event.target.value)}>
              <option value="">Все</option>
              {yearOptions.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
          <label>
            Статус
            <select value={docsStatusFilter} onChange={(event) => setDocsStatusFilter(event.target.value)}>
              <option value="">Все</option>
              {statusOptions.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
          <label>
            Нозология
            <select value={docsNosologyFilter} onChange={(event) => setDocsNosologyFilter(event.target.value)}>
              <option value="">Все</option>
              {nosologyOptions.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
        </div>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th align="left">doc_id</th>
              <th align="left">version</th>
              <th align="left">sha256</th>
              <th align="left">status</th>
              <th align="left">validity</th>
              <th align="left">chunk_count</th>
              <th align="left">source_set</th>
              <th align="left">synced_at</th>
              <th align="left">actions</th>
            </tr>
          </thead>
          <tbody>
            {filteredDocs.map((doc) => (
              <tr key={`${doc.doc_id}:${doc.doc_version}`}>
                <td>{doc.doc_id}</td>
                <td>{doc.doc_version}</td>
                <td>{doc.sha256 ? `${doc.sha256.slice(0, 12)}...` : "-"}</td>
                <td>{doc.status || "NEW"}</td>
                <td>
                  {doc.is_valid ? "valid" : `invalid (${doc.validity_reason || "unknown"})`}
                  {doc.official_source ? ` / ${doc.official_source}` : ""}
                </td>
                <td>{String(doc.chunk_count ?? 0)}</td>
                <td>{doc.source_set}</td>
                <td>{doc.updated_at || doc.uploaded_at}</td>
                <td>
                  <div className="action-row">
                    <button className="secondary" disabled={loading} onClick={() => openDocPdf(doc)}>
                      PDF
                    </button>
                    <button className="secondary" disabled={loading} onClick={() => docRechunk(doc)}>
                      Re-chunk
                    </button>
                    <button className="secondary" disabled={loading} onClick={() => docApprove(doc)}>
                      Approve
                    </button>
                    <button className="secondary" disabled={loading} onClick={() => docReject(doc)}>
                      Reject
                    </button>
                    <button
                      className="secondary"
                      disabled={loading || String(doc.status || "").toUpperCase() !== "APPROVED"}
                      onClick={() => docIndex(doc)}
                    >
                      Index
                    </button>
                    <button className="secondary" disabled={loading} onClick={() => docVerifyIndex(doc)}>
                      Verify
                    </button>
                  </div>
                  {doc.last_error_code ? <p className="muted">last_error_code: {doc.last_error_code}</p> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      </AdminDocsTab>

      <AdminReferencesTab active={activeTab === "references"}>
      <div className="card" data-testid="admin-drug-safety-controls">
        <div className="section-head">
          <h3>Словарь препаратов и safety cache</h3>
          <div className="action-row">
            <button className="secondary" disabled={loading} onClick={() => loadDrugSafetyCache(200)}>
              Обновить cache
            </button>
          </div>
        </div>
        <div className="grid two">
          <label>
            JSON словарь препаратов
            <input
              type="file"
              accept=".json,application/json"
              onChange={(event) => setDrugDictionaryFile(event.target.files?.[0] || null)}
            />
          </label>
          <label>
            INN для warmup (через запятую, опционально)
            <input
              value={drugWarmupInns}
              onChange={(event) => setDrugWarmupInns(event.target.value)}
              placeholder="capecitabine, warfarin, ramucirumab"
            />
          </label>
        </div>
        <div className="action-row" style={{ marginTop: 8 }}>
          <button className="secondary" disabled={loading || !drugDictionaryFile} onClick={uploadDrugDictionary}>
            Загрузить словарь
          </button>
          <button className="secondary" disabled={loading} onClick={warmupDrugSafetyCache}>
            Warmup cache
          </button>
        </div>
        {drugSafetyCacheSummary ? (
          <p className="muted">
            dict={drugSafetyCacheSummary.dictionary_entries_total}, cache={drugSafetyCacheSummary.cache_entries_total},
            fresh={drugSafetyCacheSummary.fresh_entries}, expired={drugSafetyCacheSummary.expired_entries},
            coverage={drugSafetyCacheSummary.coverage_ratio}, ttl_h={drugSafetyCacheSummary.cache_ttl_hours}
          </p>
        ) : null}
      </div>
      <div className="card" data-testid="admin-references-table">
        <div className="section-head">
          <h3>Справочники</h3>
        </div>
        <p className="muted">Отдельный каталог reference-документов (например, МКБ-10).</p>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th align="left">doc_id</th>
              <th align="left">version</th>
              <th align="left">status</th>
              <th align="left">sha256</th>
              <th align="left">chunk_count</th>
              <th align="left">source_url</th>
              <th align="left">updated_at</th>
              <th align="left">actions</th>
            </tr>
          </thead>
          <tbody>
            {references.map((doc) => (
              <tr key={`${doc.doc_id}:${doc.doc_version}`}>
                <td>{doc.doc_id}</td>
                <td>{doc.doc_version}</td>
                <td>{doc.status || "NEW"}</td>
                <td>{doc.sha256 ? `${doc.sha256.slice(0, 12)}...` : "-"}</td>
                <td>{String(doc.chunk_count ?? 0)}</td>
                <td>{doc.source_url || "-"}</td>
                <td>{doc.updated_at || doc.uploaded_at}</td>
                <td>
                  <div className="action-row">
                    <button className="secondary" disabled={loading} onClick={() => openDocPdf(doc)}>
                      PDF
                    </button>
                    <button className="secondary" disabled={loading} onClick={() => docRechunk(doc)}>
                      Re-chunk
                    </button>
                    <button className="secondary" disabled={loading} onClick={() => docApprove(doc)}>
                      Approve
                    </button>
                    <button
                      className="secondary"
                      disabled={loading || String(doc.status || "").toUpperCase() !== "APPROVED"}
                      onClick={() => docIndex(doc)}
                    >
                      Index
                    </button>
                    <button className="secondary" disabled={loading} onClick={() => docVerifyIndex(doc)}>
                      Verify
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {drugSafetyCacheItems.length > 0 ? (
          <>
            <h4 style={{ marginTop: 16 }}>Drug safety cache (последние записи)</h4>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <th align="left">inn</th>
                  <th align="left">source</th>
                  <th align="left">status</th>
                  <th align="left">fetched_at</th>
                  <th align="left">expires_at</th>
                  <th align="left">error_code</th>
                </tr>
              </thead>
              <tbody>
                {drugSafetyCacheItems.slice(0, 20).map((item) => (
                  <tr key={`${item.inn}:${item.fetched_at || ""}`}>
                    <td>{item.inn}</td>
                    <td>{item.source || "-"}</td>
                    <td>{item.status || "-"}</td>
                    <td>{item.fetched_at || "-"}</td>
                    <td>{item.expires_at || "-"}</td>
                    <td>{item.error_code || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : null}
      </div>
      </AdminReferencesTab>

      <AdminSyncTab active={activeTab === "sync"}>
      {governance && (
        <div className="card">
          <div className="section-head">
            <h3>Governance</h3>
          </div>
          <p className="muted">
            sources={governance.sources_total}, documents={governance.documents_total}, versions={governance.versions_total},
            disease_registry={governance.disease_registry_total}
          </p>
          {governance.latest_ingestion_runs?.length ? (
            <ul>
              {governance.latest_ingestion_runs.map((run) => (
                <li key={run.run_id}>
                  {run.run_id}: {run.status} {run.processed_docs}/{run.total_docs}
                  {run.kb_version ? `, kb=${run.kb_version}` : ""}
                  {run.last_error_code ? `, error=${run.last_error_code}` : ""}
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">No ingestion runs yet.</p>
          )}
        </div>
      )}
      </AdminSyncTab>

      <AdminSecurityTab active={activeTab === "security"}>
      <div className="card">
        <div className="section-head">
          <h3>Session Security</h3>
        </div>
        <p className="muted">Force logout for user sessions and inspect latest session audit events.</p>
        <div style={{ display: "grid", gap: 8, marginBottom: 8 }}>
          <p className="muted">Auth Risk Snapshot</p>
          {sessionAuditSummaryLoading && <p className="muted">Loading session audit summary...</p>}
          {sessionAuditSummary && (
            <>
              <p className="muted">
                window={sessionAuditSummary.window_hours}h, total_events={sessionAuditSummary.total_events},
                unique_users={sessionAuditSummary.unique_users}
              </p>
              <p className="muted">
                outcomes: allow={Number(sessionAuditSummary.outcome_counts?.allow || 0)}, deny=
                {Number(sessionAuditSummary.outcome_counts?.deny || 0)}, info=
                {Number(sessionAuditSummary.outcome_counts?.info || 0)}, error=
                {Number(sessionAuditSummary.outcome_counts?.error || 0)}
              </p>
              <p className="muted">
                top_reasons:{" "}
                {(sessionAuditSummary.top_reasons || [])
                  .slice(0, 5)
                  .map((item) => `${item.reason}:${item.count}`)
                  .join(", ") || "-"}
              </p>
              <p className="muted">
                incident_level:{" "}
                <span className={incidentBadgeClass(String(sessionAuditSummary.incident_level || "none"))}>
                  {String(sessionAuditSummary.incident_level || "none")}
                </span>
                , incident_score={Number(sessionAuditSummary.incident_score || 0)}
              </p>
              <p className="muted">
                incident_signals: deny_rate=
                {Number(sessionAuditSummary.incident_signals?.deny_rate || 0).toFixed(4)}, error_count=
                {Number(sessionAuditSummary.incident_signals?.error_count || 0)}, replay_detected_count=
                {Number(sessionAuditSummary.incident_signals?.replay_detected_count || 0)}, config_error_count=
                {Number(sessionAuditSummary.incident_signals?.config_error_count || 0)}
              </p>
              <p className="muted">
                incident_alerts:{" "}
                {(sessionAuditSummary.alerts || [])
                  .map((item) => `${item.code}:${item.level}:${item.value}/${item.threshold}`)
                  .join(", ") || "-"}
              </p>
            </>
          )}
        </div>
        <div style={{ display: "grid", gap: 8, maxWidth: 520 }}>
          <label>
            user_id
            <input
              value={forceLogoutUserId}
              onChange={(event) => setForceLogoutUserId(event.target.value)}
              placeholder="user:alice or demo:clinician"
            />
          </label>
          <div className="action-row">
            <button className="secondary" disabled={forceLogoutLoading} onClick={forceLogoutUser}>
              Force Logout User
            </button>
            <button
              className="secondary"
              disabled={sessionAuditSummaryLoading || sessionAuditExporting}
              onClick={() => loadSessionAuditSummary(24)}
            >
              Refresh Auth Risk Snapshot
            </button>
            <button
              className="secondary"
              disabled={sessionAuditLoading || sessionAuditExporting}
              onClick={() =>
                loadSessionAudit({
                  limit: sessionAuditLimit,
                  outcome: sessionAuditOutcome,
                  reason_group: sessionAuditReasonGroup,
                  event: sessionAuditEvent,
                  reason: sessionAuditReason,
                  user_id: sessionAuditUserId,
                  correlation_id: sessionAuditCorrelationId,
                  from_ts: sessionAuditFromTs,
                  to_ts: sessionAuditToTs,
                  cursor: sessionAuditCursor
                })
              }
            >
              Refresh Session Audit
            </button>
            <button
              className="secondary"
              disabled={sessionAuditLoading || sessionAuditExporting}
              onClick={() =>
                exportSessionAudit("json").catch((err) =>
                  setSessionAuditError(err instanceof Error ? err.message : "Failed to export session audit")
                )
              }
            >
              Export Audit JSON
            </button>
            <button
              className="secondary"
              disabled={sessionAuditLoading || sessionAuditExporting}
              onClick={() =>
                exportSessionAudit("csv").catch((err) =>
                  setSessionAuditError(err instanceof Error ? err.message : "Failed to export session audit")
                )
              }
            >
              Export Audit CSV
            </button>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 8 }}>
            <label>
              limit
              <input value={sessionAuditLimit} onChange={(event) => setSessionAuditLimit(event.target.value)} />
            </label>
            <label>
              export_max_events
              <input
                value={sessionAuditExportMaxEvents}
                onChange={(event) => setSessionAuditExportMaxEvents(event.target.value)}
                placeholder="1..5000"
              />
            </label>
            <label>
              outcome
              <select value={sessionAuditOutcome} onChange={(event) => setSessionAuditOutcome(event.target.value)}>
                <option value="">any</option>
                <option value="allow">allow</option>
                <option value="deny">deny</option>
                <option value="info">info</option>
                <option value="error">error</option>
              </select>
            </label>
            <label>
              reason_group
              <select value={sessionAuditReasonGroup} onChange={(event) => setSessionAuditReasonGroup(event.target.value)}>
                <option value="">any</option>
                <option value="auth">auth</option>
                <option value="token">token</option>
                <option value="revocation">revocation</option>
                <option value="config">config</option>
                <option value="rate_limit">rate_limit</option>
                <option value="other">other</option>
              </select>
            </label>
            <label>
              event
              <input value={sessionAuditEvent} onChange={(event) => setSessionAuditEvent(event.target.value)} />
            </label>
            <label>
              reason
              <input value={sessionAuditReason} onChange={(event) => setSessionAuditReason(event.target.value)} />
            </label>
            <label>
              user_id
              <input value={sessionAuditUserId} onChange={(event) => setSessionAuditUserId(event.target.value)} />
            </label>
            <label>
              correlation_id
              <input value={sessionAuditCorrelationId} onChange={(event) => setSessionAuditCorrelationId(event.target.value)} />
            </label>
            <label>
              from_ts
              <input
                value={sessionAuditFromTs}
                onChange={(event) => setSessionAuditFromTs(event.target.value)}
                placeholder="2026-02-19T00:00:00+00:00"
              />
            </label>
            <label>
              to_ts
              <input
                value={sessionAuditToTs}
                onChange={(event) => setSessionAuditToTs(event.target.value)}
                placeholder="2026-02-19T23:59:59+00:00"
              />
            </label>
          </div>
          <div style={{ display: "grid", gap: 8 }}>
            <p className="muted">Quick Reason Chips</p>
            {(["auth", "token", "revocation", "config", "rate_limit", "other"] as const).map((group) => {
              const items = SESSION_AUDIT_REASON_CATALOG.filter((item) => item.group === group);
              if (items.length === 0) return null;
              return (
                <div key={group} style={{ display: "grid", gap: 4 }}>
                  <small className="muted">{group}</small>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                    {items.map((item) => (
                      <button
                        key={item.code}
                        className="secondary"
                        disabled={sessionAuditLoading}
                        onClick={() =>
                          applyReasonCodeChip(item).catch((err) =>
                            setSessionAuditError(err instanceof Error ? err.message : "Failed to apply reason chip")
                          )
                        }
                      >
                        {item.code}
                      </button>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              className="secondary"
              disabled={sessionAuditLoading}
              onClick={() =>
                loadSessionAudit({
                  limit: sessionAuditLimit,
                  outcome: sessionAuditOutcome,
                  reason_group: sessionAuditReasonGroup,
                  event: sessionAuditEvent,
                  reason: sessionAuditReason,
                  user_id: sessionAuditUserId,
                  correlation_id: sessionAuditCorrelationId,
                  from_ts: sessionAuditFromTs,
                  to_ts: sessionAuditToTs,
                  cursor: ""
                })
              }
            >
              Apply Audit Filters
            </button>
            <button
              className="secondary"
              disabled={sessionAuditLoading || !sessionAuditNextCursor}
              onClick={() =>
                loadSessionAudit({
                  limit: sessionAuditLimit,
                  outcome: sessionAuditOutcome,
                  reason_group: sessionAuditReasonGroup,
                  event: sessionAuditEvent,
                  reason: sessionAuditReason,
                  user_id: sessionAuditUserId,
                  correlation_id: sessionAuditCorrelationId,
                  from_ts: sessionAuditFromTs,
                  to_ts: sessionAuditToTs,
                  cursor: sessionAuditNextCursor
                })
              }
            >
              Load Older Audit
            </button>
            <button
              className="secondary"
              disabled={sessionAuditLoading}
              onClick={() => {
                setSessionAuditLimit("50");
                setSessionAuditOutcome("");
                setSessionAuditReasonGroup("");
                setSessionAuditEvent("");
                setSessionAuditReason("");
                setSessionAuditUserId("");
                setSessionAuditCorrelationId("");
                setSessionAuditFromTs("");
                setSessionAuditToTs("");
                setSessionAuditCursor("");
                setSessionAuditNextCursor("");
                loadSessionAudit({ limit: "50", cursor: "" }).catch((err) =>
                  setSessionAuditError(err instanceof Error ? err.message : "Failed to reset audit filters")
                );
              }}
            >
              Reset Filters
            </button>
          </div>
          <p className="muted">next_cursor: {sessionAuditNextCursor || "-"}</p>
          {forceLogoutStatus && <p className="muted">{forceLogoutStatus}</p>}
          {sessionAuditError && <p className="error">{sessionAuditError}</p>}
        </div>
        {sessionAuditLoading && <p className="muted">Loading session audit...</p>}
        {sessionAudit && sessionAudit.events.length > 0 && (
          <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 8 }}>
            <thead>
              <tr>
                <th align="left">timestamp</th>
                <th align="left">event</th>
                <th align="left">outcome</th>
                <th align="left">role</th>
                <th align="left">user_id</th>
                <th align="left">correlation_id</th>
                <th align="left">reason_group</th>
                <th align="left">reason</th>
              </tr>
            </thead>
            <tbody>
              {sessionAudit.events.slice(0, 20).map((event, index) => (
                <tr key={`${event.timestamp}-${event.event}-${index}`}>
                  <td>{event.timestamp}</td>
                  <td>{event.event}</td>
                  <td>{event.outcome}</td>
                  <td>{event.role || "-"}</td>
                  <td>{event.user_id || "-"}</td>
                  <td>
                    {event.correlation_id ? (
                      <div style={{ display: "grid", gap: 4 }}>
                        <code>{event.correlation_id}</code>
                        <button
                          className="secondary"
                          disabled={sessionAuditLoading}
                          onClick={() =>
                            applyCorrelationDrilldown(event.correlation_id || "").catch((err) =>
                              setSessionAuditError(
                                err instanceof Error ? err.message : "Failed to apply correlation drilldown"
                              )
                            )
                          }
                        >
                          Drilldown Correlation
                        </button>
                      </div>
                    ) : (
                      "-"
                    )}
                  </td>
                  <td>{event.reason_group || summarizeSessionReason(event.reason)}</td>
                  <td>{event.reason || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {sessionAudit && sessionAudit.events.length === 0 && <p className="muted">No session audit events yet.</p>}
      </div>
      </AdminSecurityTab>

      <AdminImportRunsTab active={activeTab === "import"}>
      <div className="card">
        <div className="section-head">
          <h3>Case Import Runs</h3>
        </div>
        <p className="muted">Latest import runs and retry controls.</p>
        <div className="action-row" style={{ marginBottom: 8 }}>
          <button className="secondary" disabled={importRunsLoading || importRetrying} onClick={() => loadImportRuns()}>
            Refresh Runs
          </button>
          {selectedImportRun && (
            <button
              className="secondary"
              disabled={importRetrying || importRunLoading}
              onClick={() => retryImportFromCase(selectedImportRun)}
            >
              Retry From Case Snapshot
            </button>
          )}
        </div>
        {importRunsLoading && <p className="muted">Loading case import runs...</p>}
        {importRunsError && <p className="error">{importRunsError}</p>}
        {!importRunsLoading && importRuns.length === 0 && <p className="muted">No case import runs yet.</p>}
        {importRuns.length > 0 && (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th align="left">run_id</th>
                <th align="left">status</th>
                <th align="left">profile</th>
                <th align="left">case_id</th>
                <th align="left">started_at</th>
                <th align="left">note</th>
              </tr>
            </thead>
            <tbody>
              {importRuns.map((run) => (
                <tr
                  key={run.import_run_id}
                  style={{ cursor: "pointer", background: selectedImportRunId === run.import_run_id ? "#f6f8fa" : "transparent" }}
                  onClick={() => setSelectedImportRunId(run.import_run_id)}
                >
                  <td>{run.import_run_id}</td>
                  <td>{run.status}</td>
                  <td>{run.import_profile}</td>
                  <td>{run.case_id}</td>
                  <td>{run.started_at}</td>
                  <td>{summarizeRunMessage(run)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {selectedImportRun && (
          <div style={{ marginTop: 12 }}>
            <h4 style={{ margin: 0 }}>Run Details</h4>
            {importRunLoading ? (
              <p className="muted">Loading run details...</p>
            ) : (
              <>
                <p className="muted">
                  run_id={selectedImportRun.import_run_id}, status={selectedImportRun.status}, confidence=
                  {typeof selectedImportRun.confidence === "number" ? selectedImportRun.confidence.toFixed(2) : "n/a"}
                </p>
                {selectedImportRun.missing_required_fields.length > 0 && (
                  <p className="muted">missing_required_fields: {selectedImportRun.missing_required_fields.join(", ")}</p>
                )}
                {selectedImportRun.warnings.length > 0 && (
                  <ul>
                    {selectedImportRun.warnings.map((item, index) => (
                      <li key={`warn-${index}`}>
                        {item.code}: {item.message}
                      </li>
                    ))}
                  </ul>
                )}
                {selectedImportRun.errors.length > 0 && (
                  <ul>
                    {selectedImportRun.errors.map((item, index) => (
                      <li key={`err-${index}`}>
                        {item.code}: {item.message}
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </div>
        )}
      </div>
      </AdminImportRunsTab>
    </>
  );
}

export default function AdminPage() {
  return (
    <Suspense
      fallback={
        <div className="card">
          <p className="muted">Загрузка админ-панели...</p>
        </div>
      }
    >
      <AdminPageContent />
    </Suspense>
  );
}
