import { NextRequest } from "next/server";

import { bffError, proxyToBackend } from "@/lib/bff/proxy";

export async function GET(request: NextRequest, context: { params: Promise<{ job_id: string }> }) {
  try {
    const { job_id } = await context.params;
    return await proxyToBackend({
      request,
      backendPath: `/admin/reindex/${job_id}`,
      method: "GET",
      allowedRoles: ["admin"]
    });
  } catch (error) {
    return bffError(
      502,
      "BFF_UPSTREAM_NETWORK_ERROR",
      `BFF_UPSTREAM_NETWORK_ERROR (/admin/reindex/[job_id]): ${error instanceof Error ? error.message : "unknown"}`,
      "/admin/reindex/[job_id]"
    );
  }
}
