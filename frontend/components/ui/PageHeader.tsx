"use client";

import type { ReactNode } from "react";

type Props = {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  testId?: string;
};

export default function PageHeader({ title, subtitle, actions, testId }: Props) {
  return (
    <div className="section-head page-header" data-testid={testId}>
      <div>
        <h1>{title}</h1>
        {subtitle ? <p className="muted">{subtitle}</p> : null}
      </div>
      {actions ? <div className="action-row">{actions}</div> : null}
    </div>
  );
}
