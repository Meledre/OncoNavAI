import { NextRequest } from "next/server";

import { bffError, proxyToBackend } from "@/lib/bff/proxy";

type Params = {
  params: Promise<{ case_id: string }>;
};

export async function GET(request: NextRequest, { params }: Params) {
  const { case_id } = await params;
  if (!case_id) {
    return bffError(400, "BFF_BAD_REQUEST", "Missing case_id path parameter", "/case/{case_id}");
  }
  try {
    return await proxyToBackend({
      request,
      backendPath: `/case/${encodeURIComponent(case_id)}`,
      method: "GET",
      allowedRoles: ["clinician", "admin"]
    });
  } catch (error) {
    return bffError(
      502,
      "BFF_UPSTREAM_NETWORK_ERROR",
      `BFF_UPSTREAM_NETWORK_ERROR (/case/${case_id}): ${error instanceof Error ? error.message : "unknown"}`,
      "/case/{case_id}"
    );
  }
}
