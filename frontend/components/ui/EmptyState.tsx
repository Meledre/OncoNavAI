"use client";

type Props = {
  title: string;
  subtitle?: string;
  testId?: string;
};

export default function EmptyState({ title, subtitle, testId }: Props) {
  return (
    <div className="state-box empty-state" data-testid={testId}>
      <strong>{title}</strong>
      {subtitle ? <p className="muted">{subtitle}</p> : null}
    </div>
  );
}
