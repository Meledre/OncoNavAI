import { NextRequest } from "next/server";

import { bffError, proxyToBackend } from "@/lib/bff/proxy";

export async function GET(request: NextRequest) {
  try {
    const limitRaw = request.nextUrl.searchParams.get("limit");
    const parsed = Number.parseInt(String(limitRaw || "200"), 10);
    const limit = Number.isFinite(parsed) ? Math.max(1, Math.min(parsed, 5000)) : 200;
    return await proxyToBackend({
      request,
      backendPath: `/admin/drug-safety/cache?limit=${limit}`,
      method: "GET",
      allowedRoles: ["admin"]
    });
  } catch (error) {
    return bffError(
      502,
      "BFF_UPSTREAM_NETWORK_ERROR",
      `BFF_UPSTREAM_NETWORK_ERROR (/admin/drug-safety/cache): ${error instanceof Error ? error.message : "unknown"}`,
      "/admin/drug-safety/cache"
    );
  }
}
