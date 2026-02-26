import { NextRequest } from "next/server";

import { bffError, proxyToBackend } from "@/lib/bff/proxy";

export async function GET(request: NextRequest) {
  try {
    const language = request.nextUrl.searchParams.get("language");
    const search = language ? `?language=${encodeURIComponent(language)}` : "";
    return await proxyToBackend({
      request,
      backendPath: `/admin/routing/routes${search}`,
      method: "GET",
      allowedRoles: ["admin"]
    });
  } catch (error) {
    return bffError(
      502,
      "BFF_UPSTREAM_NETWORK_ERROR",
      `BFF_UPSTREAM_NETWORK_ERROR (/admin/routing/routes): ${error instanceof Error ? error.message : "unknown"}`,
      "/admin/routing/routes"
    );
  }
}
