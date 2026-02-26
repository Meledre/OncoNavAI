"use client";

type Props = {
  message: string;
  testId?: string;
};

export default function LoadingState({ message, testId }: Props) {
  return (
    <p className="muted state-box loading-state" data-testid={testId}>
      {message}
    </p>
  );
}
