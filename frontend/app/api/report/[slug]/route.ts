import { NextRequest } from "next/server";

import { bffError, proxyToBackend } from "@/lib/bff/proxy";

function parseLegacySlug(slug: string): { reportId: string; format: "json" | "html" | "pdf" | "docx" } | null {
  if (slug.endsWith(".json")) {
    return { reportId: slug.slice(0, -5), format: "json" };
  }
  if (slug.endsWith(".html")) {
    return { reportId: slug.slice(0, -5), format: "html" };
  }
  if (slug.endsWith(".pdf")) {
    return { reportId: slug.slice(0, -4), format: "pdf" };
  }
  if (slug.endsWith(".docx")) {
    return { reportId: slug.slice(0, -5), format: "docx" };
  }
  return null;
}

export async function GET(request: NextRequest, context: { params: Promise<{ slug: string }> }) {
  try {
    const { slug } = await context.params;
    const parsed = parseLegacySlug(slug);
    if (!parsed || !parsed.reportId) {
      return bffError(404, "BFF_BAD_REQUEST", "Unsupported report path", "/report/[slug]");
    }
    return await proxyToBackend({
      request,
      backendPath: `/report/${parsed.reportId}.${parsed.format}`,
      method: "GET",
      allowedRoles: ["clinician", "admin"]
    });
  } catch (error) {
    return bffError(
      502,
      "BFF_UPSTREAM_NETWORK_ERROR",
      `BFF_UPSTREAM_NETWORK_ERROR (/report/[slug]): ${error instanceof Error ? error.message : "unknown"}`,
      "/report/[slug]"
    );
  }
}
