"use client";

type Props = {
  message: string;
  testId?: string;
};

export default function ErrorState({ message, testId }: Props) {
  return (
    <p className="error state-box error-state" data-testid={testId}>
      {message}
    </p>
  );
}
