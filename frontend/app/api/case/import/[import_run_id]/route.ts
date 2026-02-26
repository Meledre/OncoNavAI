import { NextRequest } from "next/server";

import { bffError, proxyToBackend } from "@/lib/bff/proxy";

type Params = {
  params: Promise<{ import_run_id: string }>;
};

export async function GET(request: NextRequest, { params }: Params) {
  const { import_run_id } = await params;
  if (!import_run_id) {
    return bffError(400, "BFF_BAD_REQUEST", "Missing import_run_id path parameter", "/case/import/{import_run_id}");
  }
  try {
    return await proxyToBackend({
      request,
      backendPath: `/case/import/${encodeURIComponent(import_run_id)}`,
      method: "GET",
      allowedRoles: ["clinician", "admin"]
    });
  } catch (error) {
    return bffError(
      502,
      "BFF_UPSTREAM_NETWORK_ERROR",
      `BFF_UPSTREAM_NETWORK_ERROR (/case/import/${import_run_id}): ${error instanceof Error ? error.message : "unknown"}`,
      "/case/import/{import_run_id}"
    );
  }
}
