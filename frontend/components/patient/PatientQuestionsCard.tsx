"use client";

import Card from "@/components/ui/Card";

type Props = {
  questions: string[];
  testId?: string;
};

export default function PatientQuestionsCard({ questions, testId = "patient-card-questions" }: Props) {
  if (questions.length === 0) return null;
  return (
    <Card testId={testId}>
      <h3>Что обсудить с врачом</h3>
      <ul>
        {questions.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </Card>
  );
}
