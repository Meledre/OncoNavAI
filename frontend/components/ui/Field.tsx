"use client";

import type { ReactNode } from "react";

type Props = {
  label: string;
  children: ReactNode;
  testId?: string;
};

export default function Field({ label, children, testId }: Props) {
  return (
    <label className="ui-field" data-testid={testId}>
      <span>{label}</span>
      {children}
    </label>
  );
}
