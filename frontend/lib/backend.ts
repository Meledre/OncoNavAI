function normalizeBaseUrl(raw: string | undefined): string {
  const fallback = "http://localhost:8000";
  if (!raw) return fallback;

  let value = raw.trim().replace(/^['"]|['"]$/g, "");
  if (!value) return fallback;

  if (!/^https?:\/\//i.test(value)) {
    value = `http://${value}`;
  }

  try {
    const parsed = new URL(value);
    return parsed.toString().replace(/\/$/, "");
  } catch {
    return fallback;
  }
}

export function backendBaseUrl(): string {
  return normalizeBaseUrl(process.env.LOCAL_CORE_BASE_URL || process.env.BACKEND_URL);
}

export function backendUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${backendBaseUrl()}${normalizedPath}`;
}

export function demoToken(): string {
  return (process.env.DEMO_TOKEN || "demo-token").trim();
}
