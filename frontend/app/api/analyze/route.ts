import { NextRequest } from "next/server";

import { bffError, proxyToBackend } from "@/lib/bff/proxy";

export const maxDuration = 900;

export async function POST(request: NextRequest) {
  try {
    const body = await request.text();
    const clientId = request.headers.get("x-client-id") || "frontend";
    return await proxyToBackend({
      request,
      backendPath: "/analyze",
      method: "POST",
      allowedRoles: ["clinician", "admin"],
      clientId,
      body,
      contentType: "application/json",
      timeoutMs: 420000
    });
  } catch (error) {
    return bffError(
      502,
      "BFF_UPSTREAM_NETWORK_ERROR",
      `BFF_UPSTREAM_NETWORK_ERROR (/analyze): ${error instanceof Error ? error.message : "unknown"}`,
      "/analyze"
    );
  }
}
