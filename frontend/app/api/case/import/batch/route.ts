import { NextRequest } from "next/server";

import { bffError, proxyToBackend } from "@/lib/bff/proxy";

export async function POST(request: NextRequest) {
  try {
    const body = await request.text();
    return await proxyToBackend({
      request,
      backendPath: "/case/import/batch",
      method: "POST",
      allowedRoles: ["clinician", "admin"],
      body,
      contentType: "application/json"
    });
  } catch (error) {
    return bffError(
      502,
      "BFF_UPSTREAM_NETWORK_ERROR",
      `BFF_UPSTREAM_NETWORK_ERROR (/case/import/batch): ${error instanceof Error ? error.message : "unknown"}`,
      "/case/import/batch"
    );
  }
}
