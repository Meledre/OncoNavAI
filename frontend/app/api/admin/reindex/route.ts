import { NextRequest } from "next/server";

import { bffError, proxyToBackend } from "@/lib/bff/proxy";

export const maxDuration = 300;

export async function POST(request: NextRequest) {
  try {
    return await proxyToBackend({
      request,
      backendPath: "/admin/reindex",
      method: "POST",
      allowedRoles: ["admin"],
      timeoutMs: 900000
    });
  } catch (error) {
    return bffError(
      502,
      "BFF_UPSTREAM_NETWORK_ERROR",
      `BFF_UPSTREAM_NETWORK_ERROR (/admin/reindex): ${error instanceof Error ? error.message : "unknown"}`,
      "/admin/reindex"
    );
  }
}
