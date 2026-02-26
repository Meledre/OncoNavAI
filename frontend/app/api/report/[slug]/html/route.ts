import { NextRequest } from "next/server";

import { bffError, proxyToBackend } from "@/lib/bff/proxy";

export async function GET(request: NextRequest, context: { params: Promise<{ slug: string }> }) {
  try {
    const { slug } = await context.params;
    if (!slug) {
      return bffError(400, "BFF_BAD_REQUEST", "report_id is required", "/report/[slug]/html");
    }
    return await proxyToBackend({
      request,
      backendPath: `/report/${slug}.html`,
      method: "GET",
      allowedRoles: ["clinician", "admin"]
    });
  } catch (error) {
    return bffError(
      502,
      "BFF_UPSTREAM_NETWORK_ERROR",
      `BFF_UPSTREAM_NETWORK_ERROR (/report/[slug]/html): ${error instanceof Error ? error.message : "unknown"}`,
      "/report/[slug]/html"
    );
  }
}
