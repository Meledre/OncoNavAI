"use client";

"use client";

import type { ReactNode } from "react";

type BadgeTone = "critical" | "important" | "note";

type Props = {
  tone: BadgeTone;
  children: ReactNode;
  className?: string;
};

export default function Badge({ tone, children, className }: Props) {
  const base = `badge ${tone}`;
  const merged = className ? `${base} ${className}` : base;
  return <span className={merged}>{children}</span>;
}
