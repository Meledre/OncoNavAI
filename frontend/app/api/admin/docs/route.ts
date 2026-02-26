import { NextRequest } from "next/server";

import { bffError, proxyToBackend } from "@/lib/bff/proxy";

export async function GET(request: NextRequest) {
  try {
    const validOnlyRaw = request.nextUrl.searchParams.get("valid_only");
    const validOnly = validOnlyRaw === null ? "true" : String(validOnlyRaw).toLowerCase() === "false" ? "false" : "true";
    const kindRaw = String(request.nextUrl.searchParams.get("kind") || "guideline").toLowerCase().trim();
    const kind = kindRaw === "all" || kindRaw === "reference" ? kindRaw : "guideline";
    return await proxyToBackend({
      request,
      backendPath: `/admin/docs?valid_only=${validOnly}&kind=${kind}`,
      method: "GET",
      allowedRoles: ["admin"]
    });
  } catch (error) {
    return bffError(
      502,
      "BFF_UPSTREAM_NETWORK_ERROR",
      `BFF_UPSTREAM_NETWORK_ERROR (/admin/docs): ${error instanceof Error ? error.message : "unknown"}`,
      "/admin/docs"
    );
  }
}
