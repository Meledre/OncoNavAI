import { NextRequest } from "next/server";

import { bffError, proxyToBackend } from "@/lib/bff/proxy";

export const maxDuration = 900;

export async function POST(request: NextRequest) {
  try {
    const body = await request.text();
    return await proxyToBackend({
      request,
      backendPath: "/patient/analyze-file-base64",
      method: "POST",
      allowedRoles: ["patient", "admin", "clinician"],
      body,
      contentType: "application/json",
      timeoutMs: 420000
    });
  } catch (error) {
    return bffError(
      502,
      "BFF_UPSTREAM_NETWORK_ERROR",
      `BFF_UPSTREAM_NETWORK_ERROR (/patient/analyze-file-base64): ${error instanceof Error ? error.message : "unknown"}`,
      "/patient/analyze-file-base64"
    );
  }
}
