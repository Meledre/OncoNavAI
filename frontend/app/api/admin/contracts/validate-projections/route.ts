import { NextRequest } from "next/server";

import { bffError, proxyToBackend } from "@/lib/bff/proxy";

export async function POST(request: NextRequest) {
  try {
    const body = await request.text();
    return await proxyToBackend({
      request,
      backendPath: "/admin/contracts/validate-projections",
      method: "POST",
      allowedRoles: ["admin"],
      body,
      contentType: "application/json"
    });
  } catch (error) {
    return bffError(
      502,
      "BFF_UPSTREAM_NETWORK_ERROR",
      `BFF_UPSTREAM_NETWORK_ERROR (/admin/contracts/validate-projections): ${error instanceof Error ? error.message : "unknown"}`,
      "/admin/contracts/validate-projections"
    );
  }
}
