import { NextRequest } from "next/server";

import { bffError, proxyToBackend } from "@/lib/bff/proxy";

export async function GET(request: NextRequest) {
  const limitRaw = request.nextUrl.searchParams.get("limit");
  const limit = Number.parseInt(limitRaw || "", 10);
  const hasValidLimit = Number.isFinite(limit) && limit >= 1 && limit <= 100;
  const backendPath = hasValidLimit ? `/case/import/runs?limit=${limit}` : "/case/import/runs";
  try {
    return await proxyToBackend({
      request,
      backendPath,
      method: "GET",
      allowedRoles: ["clinician", "admin"]
    });
  } catch (error) {
    return bffError(
      502,
      "BFF_UPSTREAM_NETWORK_ERROR",
      `BFF_UPSTREAM_NETWORK_ERROR (${backendPath}): ${error instanceof Error ? error.message : "unknown"}`,
      "/case/import/runs"
    );
  }
}
