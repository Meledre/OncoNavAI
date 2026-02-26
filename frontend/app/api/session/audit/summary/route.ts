import { NextRequest } from "next/server";

import { bffError, proxyToBackend } from "@/lib/bff/proxy";

export async function GET(request: NextRequest) {
  try {
    const url = new URL(request.url);
    const rawWindow = Number.parseInt(url.searchParams.get("window_hours") || "24", 10);
    const windowHours = Number.isFinite(rawWindow) ? Math.max(1, Math.min(rawWindow, 168)) : 24;
    const fromTs = String(url.searchParams.get("from_ts") || "").trim();
    const toTs = String(url.searchParams.get("to_ts") || "").trim();

    const params = new URLSearchParams();
    params.set("window_hours", String(windowHours));
    if (fromTs) params.set("from_ts", fromTs);
    if (toTs) params.set("to_ts", toTs);

    return await proxyToBackend({
      request,
      backendPath: `/session/audit/summary?${params.toString()}`,
      method: "GET",
      allowedRoles: ["admin"],
    });
  } catch (error) {
    return bffError(
      502,
      "BFF_UPSTREAM_NETWORK_ERROR",
      `BFF_UPSTREAM_NETWORK_ERROR (/session/audit/summary): ${error instanceof Error ? error.message : "unknown"}`,
      "/session/audit/summary"
    );
  }
}
