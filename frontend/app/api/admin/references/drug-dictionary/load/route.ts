import { NextRequest } from "next/server";

import { bffError, proxyToBackend } from "@/lib/bff/proxy";

export async function POST(request: NextRequest) {
  try {
    const contentType = String(request.headers.get("content-type") || "").toLowerCase();
    if (contentType.includes("multipart/form-data")) {
      const formData = await request.formData();
      const file = formData.get("file");
      if (!(file instanceof File)) {
        return bffError(
          400,
          "BFF_BAD_REQUEST",
          "file is required for drug dictionary upload",
          "/admin/references/drug-dictionary/load"
        );
      }
      const bytes = await file.arrayBuffer();
      const payload = {
        filename: file.name || "drug_dictionary.json",
        content_base64: Buffer.from(bytes).toString("base64")
      };
      return await proxyToBackend({
        request,
        backendPath: "/admin/references/drug-dictionary/load",
        method: "POST",
        allowedRoles: ["admin"],
        body: JSON.stringify(payload),
        contentType: "application/json"
      });
    }

    const rawBody = await request.text();
    return await proxyToBackend({
      request,
      backendPath: "/admin/references/drug-dictionary/load",
      method: "POST",
      allowedRoles: ["admin"],
      body: rawBody,
      contentType: "application/json"
    });
  } catch (error) {
    return bffError(
      502,
      "BFF_UPSTREAM_NETWORK_ERROR",
      `BFF_UPSTREAM_NETWORK_ERROR (/admin/references/drug-dictionary/load): ${
        error instanceof Error ? error.message : "unknown"
      }`,
      "/admin/references/drug-dictionary/load"
    );
  }
}
