"use client";

import Card from "@/components/ui/Card";

type Props = {
  summary: string;
  keyPoints: string[];
  testId?: string;
};

export default function PatientSummaryCard({ summary, keyPoints, testId = "patient-card-summary" }: Props) {
  return (
    <Card variant="hero" testId={testId}>
      <h3>Краткое объяснение</h3>
      <p>{summary}</p>
      {keyPoints.length > 0 ? (
        <>
          <h3>Ключевые моменты</h3>
          <ul>
            {keyPoints.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </>
      ) : null}
    </Card>
  );
}
