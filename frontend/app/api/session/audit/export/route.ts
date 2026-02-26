import { NextRequest, NextResponse } from "next/server";

import { bffError, proxyToBackend } from "@/lib/bff/proxy";

type SessionAuditEvent = Record<string, unknown>;
type SessionAuditPayload = {
  count?: number;
  limit?: number;
  cursor?: string;
  next_cursor?: string;
  filters?: Record<string, string>;
  events?: SessionAuditEvent[];
  truncated?: boolean;
  truncated_reason?: string;
};

const CSV_COLUMNS = [
  "timestamp",
  "event",
  "outcome",
  "role",
  "user_id",
  "session_id",
  "actor_user_id",
  "correlation_id",
  "reason_group",
  "reason",
  "path"
] as const;
const EXPORT_MAX_EVENTS_HARD_CAP = 5000;

function parseBool(value: string): boolean {
  const normalized = value.trim().toLowerCase();
  return normalized === "1" || normalized === "true" || normalized === "yes" || normalized === "on";
}

function parseBoundedIntParam(
  raw: string | null,
  options: {
    fallback: number;
    min: number;
    max: number;
    paramName: string;
  }
): { value: number; error?: NextResponse } {
  const { fallback, min, max, paramName } = options;
  const text = String(raw || "").trim();
  if (!text) return { value: fallback };
  if (!/^[0-9]+$/.test(text)) {
    return {
      value: fallback,
      error: bffError(
        400,
        "BFF_BAD_REQUEST",
        `Invalid ${paramName}, expected integer in range ${min}..${max}`,
        "/session/audit/export"
      )
    };
  }
  const value = Number.parseInt(text, 10);
  if (!Number.isFinite(value) || value < min || value > max) {
    return {
      value: fallback,
      error: bffError(
        400,
        "BFF_BAD_REQUEST",
        `Invalid ${paramName}, expected integer in range ${min}..${max}`,
        "/session/audit/export"
      )
    };
  }
  return { value };
}

function protectSpreadsheetFormula(text: string): string {
  // Prevent spreadsheet formula execution when opening exported CSV in Excel/Sheets.
  if (/^[\s]*[=+\-@]/.test(text)) {
    return `'${text}`;
  }
  return text;
}

function csvCell(value: unknown): string {
  const text = protectSpreadsheetFormula(String(value ?? ""));
  if (!text.includes(",") && !text.includes('"') && !text.includes("\n") && !text.includes("\r")) {
    return text;
  }
  return `"${text.replace(/"/g, '""')}"`;
}

function toCsv(events: SessionAuditEvent[]): string {
  const rows: string[] = [];
  rows.push(CSV_COLUMNS.join(","));
  for (const event of events) {
    const values = CSV_COLUMNS.map((key) => csvCell(event[key]));
    rows.push(values.join(","));
  }
  return rows.join("\n");
}

function parseAuditPayload(raw: string): SessionAuditPayload {
  try {
    const parsed = JSON.parse(raw) as SessionAuditPayload;
    if (!parsed || typeof parsed !== "object") return {};
    return parsed;
  } catch {
    return {};
  }
}

function safeFilenameStamp(): string {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

async function fetchAuditPage(
  request: NextRequest,
  params: URLSearchParams
): Promise<{ payload: SessionAuditPayload; headers: Headers } | NextResponse> {
  const response = await proxyToBackend({
    request,
    backendPath: `/session/audit?${params.toString()}`,
    method: "GET",
    allowedRoles: ["admin"]
  });
  if (!response.ok) return response;
  const raw = await response.text();
  return {
    payload: parseAuditPayload(raw),
    headers: new Headers(response.headers)
  };
}

function buildExportResponse(
  payload: SessionAuditPayload,
  sourceHeaders: Headers,
  format: "json" | "csv",
  allPages: boolean,
  maxEvents: number
): NextResponse {
  const headers = new Headers(sourceHeaders);
  headers.set("cache-control", "no-store");
  headers.set("x-onco-export-max-events", String(maxEvents));
  if (payload.truncated) {
    headers.set("x-onco-export-truncated", "1");
    headers.set("x-onco-export-truncated-reason", String(payload.truncated_reason || "unknown"));
  }
  const stamp = safeFilenameStamp();
  if (format === "csv") {
    const events = Array.isArray(payload.events) ? payload.events : [];
    headers.set("content-type", "text/csv; charset=utf-8");
    headers.set(
      "content-disposition",
      `attachment; filename="session_audit_${allPages ? "all_" : ""}${stamp}.csv"`
    );
    return new NextResponse(toCsv(events), { status: 200, headers });
  }

  headers.set("content-type", "application/json; charset=utf-8");
  headers.set(
    "content-disposition",
    `attachment; filename="session_audit_${allPages ? "all_" : ""}${stamp}.json"`
  );
  return new NextResponse(JSON.stringify(payload, null, 2), { status: 200, headers });
}

export async function GET(request: NextRequest) {
  try {
    const url = new URL(request.url);
    const parsedLimit = parseBoundedIntParam(url.searchParams.get("limit"), {
      fallback: 200,
      min: 1,
      max: 500,
      paramName: "limit"
    });
    if (parsedLimit.error) return parsedLimit.error;
    const limit = parsedLimit.value;
    const outcome = String(url.searchParams.get("outcome") || "").trim();
    const reasonGroup = String(url.searchParams.get("reason_group") || "").trim();
    const event = String(url.searchParams.get("event") || "").trim();
    const reason = String(url.searchParams.get("reason") || "").trim();
    const userId = String(url.searchParams.get("user_id") || "").trim();
    const correlationId = String(url.searchParams.get("correlation_id") || "").trim();
    const fromTs = String(url.searchParams.get("from_ts") || "").trim();
    const toTs = String(url.searchParams.get("to_ts") || "").trim();
    const cursor = String(url.searchParams.get("cursor") || "").trim();
    const allPages = parseBool(String(url.searchParams.get("all") || "1"));
    const parsedMaxPages = parseBoundedIntParam(url.searchParams.get("max_pages"), {
      fallback: 50,
      min: 1,
      max: 200,
      paramName: "max_pages"
    });
    if (parsedMaxPages.error) return parsedMaxPages.error;
    const maxPages = parsedMaxPages.value;
    const parsedMaxEvents = parseBoundedIntParam(url.searchParams.get("max_events"), {
      fallback: EXPORT_MAX_EVENTS_HARD_CAP,
      min: 1,
      max: EXPORT_MAX_EVENTS_HARD_CAP,
      paramName: "max_events"
    });
    if (parsedMaxEvents.error) return parsedMaxEvents.error;
    const maxEvents = parsedMaxEvents.value;

    const formatRaw = String(url.searchParams.get("format") || "json").trim().toLowerCase();
    if (formatRaw !== "json" && formatRaw !== "csv") {
      return bffError(
        400,
        "BFF_BAD_REQUEST",
        "Invalid export format, expected one of: json|csv",
        "/session/audit/export"
      );
    }
    const format = formatRaw as "json" | "csv";

    const baseParams = new URLSearchParams();
    baseParams.set("limit", String(limit));
    if (outcome) baseParams.set("outcome", outcome);
    if (reasonGroup) baseParams.set("reason_group", reasonGroup);
    if (event) baseParams.set("event", event);
    if (reason) baseParams.set("reason", reason);
    if (userId) baseParams.set("user_id", userId);
    if (correlationId) baseParams.set("correlation_id", correlationId);
    if (fromTs) baseParams.set("from_ts", fromTs);
    if (toTs) baseParams.set("to_ts", toTs);

    if (!allPages) {
      if (cursor) baseParams.set("cursor", cursor);
      const single = await fetchAuditPage(request, baseParams);
      if (single instanceof NextResponse) return single;
      const singleEvents = Array.isArray(single.payload.events) ? single.payload.events.slice(0, maxEvents) : [];
      const singleTrimmed =
        Array.isArray(single.payload.events) && single.payload.events.length > singleEvents.length;
      const singleTruncatedReason = singleTrimmed
        ? "max_events"
        : single.payload.truncated
          ? "upstream"
          : undefined;
      const singlePayload: SessionAuditPayload = {
        ...single.payload,
        events: singleEvents,
        count: singleEvents.length,
        truncated: Boolean(singleTruncatedReason),
        truncated_reason: singleTruncatedReason,
      };
      return buildExportResponse(singlePayload, single.headers, format, false, maxEvents);
    }

    const collected: SessionAuditEvent[] = [];
    let truncatedByLimit = false;
    let sawUpstreamTruncated = false;
    let pageCursor = "";
    let nextCursor = "";
    let headers = new Headers();
    for (let idx = 0; idx < maxPages; idx += 1) {
      const params = new URLSearchParams(baseParams);
      if (pageCursor) params.set("cursor", pageCursor);
      const page = await fetchAuditPage(request, params);
      if (page instanceof NextResponse) return page;
      headers = page.headers;
      const events = Array.isArray(page.payload.events) ? page.payload.events : [];
      sawUpstreamTruncated = sawUpstreamTruncated || Boolean(page.payload.truncated);
      collected.push(...events);
      if (collected.length >= maxEvents) {
        collected.length = maxEvents;
        truncatedByLimit = true;
        nextCursor = String(page.payload.next_cursor || "").trim();
        break;
      }
      nextCursor = String(page.payload.next_cursor || "").trim();
      if (!nextCursor) break;
      pageCursor = nextCursor;
    }
    let truncatedReason: string | undefined;
    if (truncatedByLimit) {
      truncatedReason = "max_events";
    } else if (nextCursor) {
      truncatedReason = "max_pages";
    } else if (sawUpstreamTruncated) {
      truncatedReason = "upstream";
    }

    const payload: SessionAuditPayload = {
      count: collected.length,
      limit,
      filters: {
        outcome,
        reason_group: reasonGroup,
        event,
        reason,
        user_id: userId,
        correlation_id: correlationId,
        from_ts: fromTs,
        to_ts: toTs
      },
      cursor: "",
      next_cursor: nextCursor,
      events: collected,
      truncated: Boolean(truncatedReason),
      truncated_reason: truncatedReason
    };
    return buildExportResponse(payload, headers, format, true, maxEvents);
  } catch (error) {
    return bffError(
      502,
      "BFF_UPSTREAM_NETWORK_ERROR",
      `BFF_UPSTREAM_NETWORK_ERROR (/session/audit/export): ${error instanceof Error ? error.message : "unknown"}`,
      "/session/audit/export"
    );
  }
}
