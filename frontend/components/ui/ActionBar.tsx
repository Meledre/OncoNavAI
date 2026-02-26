"use client";

import type { ReactNode } from "react";

type Props = {
  children: ReactNode;
  className?: string;
  testId?: string;
};

export default function ActionBar({ children, className, testId }: Props) {
  const merged = className ? `action-row ${className}` : "action-row";
  return (
    <div className={merged} data-testid={testId}>
      {children}
    </div>
  );
}
