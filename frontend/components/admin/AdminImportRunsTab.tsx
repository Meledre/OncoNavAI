"use client";

import type { ReactNode } from "react";

type Props = {
  active: boolean;
  children: ReactNode;
};

export default function AdminImportRunsTab({ active, children }: Props) {
  if (!active) return null;
  return <div data-testid="admin-tab-import">{children}</div>;
}
