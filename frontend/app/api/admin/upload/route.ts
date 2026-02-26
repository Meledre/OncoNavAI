import { NextRequest } from "next/server";

import { bffError, proxyToBackend } from "@/lib/bff/proxy";

function parseListField(raw: FormDataEntryValue | null): string[] {
  const text = String(raw || "").trim();
  if (!text) return [];
  if (text.startsWith("[") && text.endsWith("]")) {
    try {
      const parsed = JSON.parse(text);
      if (Array.isArray(parsed)) {
        return parsed.map((item) => String(item).trim()).filter((item) => item.length > 0);
      }
    } catch {
      return [];
    }
  }
  return text
    .split(",")
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

export async function POST(request: NextRequest) {
  try {
    const formData = await request.formData();
    const file = formData.get("file");

    if (!(file instanceof File)) {
      return bffError(400, "BFF_BAD_REQUEST", "file is required", "/admin/upload");
    }

    const arrayBuffer = await file.arrayBuffer();
    const bodyPayload = {
      filename: file.name || "upload.pdf",
      content_base64: Buffer.from(arrayBuffer).toString("base64"),
      doc_id: String(formData.get("doc_id") || ""),
      doc_version: String(formData.get("doc_version") || ""),
      source_set: String(formData.get("source_set") || ""),
      cancer_type: String(formData.get("cancer_type") || ""),
      language: String(formData.get("language") || ""),
      source_url: String(formData.get("source_url") || "").trim(),
      doc_kind: String(formData.get("doc_kind") || "guideline").trim().toLowerCase() || "guideline",
      disease_id: String(formData.get("disease_id") || "").trim() || undefined,
      icd10_prefixes: parseListField(formData.get("icd10_prefixes")),
      nosology_keywords: parseListField(formData.get("nosology_keywords"))
    };

    return await proxyToBackend({
      request,
      backendPath: "/admin/upload",
      method: "POST",
      allowedRoles: ["admin"],
      body: JSON.stringify(bodyPayload),
      contentType: "application/json"
    });
  } catch (error) {
    return bffError(
      502,
      "BFF_UPSTREAM_NETWORK_ERROR",
      `BFF_UPSTREAM_NETWORK_ERROR (/admin/upload): ${error instanceof Error ? error.message : "unknown"}`,
      "/admin/upload"
    );
  }
}
