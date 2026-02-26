const EMAIL_RE = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/;
const PHONE_RE = /(?:\+?\d[\d\s().-]{8,}\d)/;

export function detectPII(text: string): string[] {
  const issues: string[] = [];
  if (EMAIL_RE.test(text)) issues.push("email");
  if (PHONE_RE.test(text)) issues.push("phone");
  return issues;
}
