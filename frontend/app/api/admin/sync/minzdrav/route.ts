import { NextRequest } from "next/server";

import { bffError, proxyToBackend } from "@/lib/bff/proxy";

export async function POST(request: NextRequest) {
  try {
    return await proxyToBackend({
      request,
      backendPath: "/admin/sync/minzdrav",
      method: "POST",
      allowedRoles: ["admin"]
    });
  } catch (error) {
    return bffError(
      502,
      "BFF_UPSTREAM_NETWORK_ERROR",
      `BFF_UPSTREAM_NETWORK_ERROR (/admin/sync/minzdrav): ${error instanceof Error ? error.message : "unknown"}`,
      "/admin/sync/minzdrav"
    );
  }
}
