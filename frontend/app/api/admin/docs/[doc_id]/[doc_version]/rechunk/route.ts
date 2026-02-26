import { NextRequest } from "next/server";

import { bffError, proxyToBackend } from "@/lib/bff/proxy";

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ doc_id: string; doc_version: string }> }
) {
  try {
    const { doc_id, doc_version } = await context.params;
    if (!doc_id || !doc_version) {
      return bffError(
        400,
        "BFF_BAD_REQUEST",
        "doc_id and doc_version are required",
        "/admin/docs/[doc_id]/[doc_version]/rechunk"
      );
    }
    return await proxyToBackend({
      request,
      backendPath: `/admin/docs/${doc_id}/${doc_version}/rechunk`,
      method: "POST",
      allowedRoles: ["admin"]
    });
  } catch (error) {
    return bffError(
      502,
      "BFF_UPSTREAM_NETWORK_ERROR",
      `BFF_UPSTREAM_NETWORK_ERROR (/admin/docs/[doc_id]/[doc_version]/rechunk): ${
        error instanceof Error ? error.message : "unknown"
      }`,
      "/admin/docs/[doc_id]/[doc_version]/rechunk"
    );
  }
}
