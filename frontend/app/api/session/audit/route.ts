import { NextRequest } from "next/server";

import { bffError, proxyToBackend } from "@/lib/bff/proxy";

export async function GET(request: NextRequest) {
  try {
    const url = new URL(request.url);
    const limitRaw = Number.parseInt(url.searchParams.get("limit") || "50", 10);
    const limit = Number.isFinite(limitRaw) ? Math.max(1, Math.min(limitRaw, 200)) : 50;
    const outcome = String(url.searchParams.get("outcome") || "").trim();
    const reasonGroup = String(url.searchParams.get("reason_group") || "").trim();
    const event = String(url.searchParams.get("event") || "").trim();
    const reason = String(url.searchParams.get("reason") || "").trim();
    const userId = String(url.searchParams.get("user_id") || "").trim();
    const correlationId = String(url.searchParams.get("correlation_id") || "").trim();
    const fromTs = String(url.searchParams.get("from_ts") || "").trim();
    const toTs = String(url.searchParams.get("to_ts") || "").trim();
    const cursor = String(url.searchParams.get("cursor") || "").trim();
    const nextCursorField = "next_cursor";
    void nextCursorField;

    const params = new URLSearchParams();
    params.set("limit", String(limit));
    if (outcome) params.set("outcome", outcome);
    if (reasonGroup) params.set("reason_group", reasonGroup);
    if (event) params.set("event", event);
    if (reason) params.set("reason", reason);
    if (userId) params.set("user_id", userId);
    if (correlationId) params.set("correlation_id", correlationId);
    if (fromTs) params.set("from_ts", fromTs);
    if (toTs) params.set("to_ts", toTs);
    if (cursor) params.set("cursor", cursor);

    return await proxyToBackend({
      request,
      backendPath: `/session/audit?${params.toString()}`,
      method: "GET",
      allowedRoles: ["admin"]
    });
  } catch (error) {
    return bffError(
      502,
      "BFF_UPSTREAM_NETWORK_ERROR",
      `BFF_UPSTREAM_NETWORK_ERROR (/session/audit): ${error instanceof Error ? error.message : "unknown"}`,
      "/session/audit"
    );
  }
}
