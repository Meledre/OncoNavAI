"use client";

import Card from "@/components/ui/Card";

type Props = {
  safetyNotes: string[];
  whatWasChecked: string[];
  drugSafety?: {
    status: "ok" | "partial" | "unavailable";
    important_risks: string[];
    questions_for_doctor: string[];
  };
  testId?: string;
};

export default function PatientSafetyCard({ safetyNotes, whatWasChecked, drugSafety, testId = "patient-card-safety" }: Props) {
  return (
    <Card testId={testId}>
      {drugSafety ? (
        <>
          <h3>Безопасность лекарств</h3>
          <p className="muted">Статус: {drugSafety.status}</p>
          {drugSafety.important_risks.length > 0 ? (
            <ul>
              {drugSafety.important_risks.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          ) : null}
          {drugSafety.questions_for_doctor.length > 0 ? (
            <>
              <h3>Вопросы по безопасности</h3>
              <ul>
                {drugSafety.questions_for_doctor.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </>
          ) : null}
        </>
      ) : null}
      {whatWasChecked.length > 0 ? (
        <>
          <h3>Что было проверено</h3>
          <ul>
            {whatWasChecked.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </>
      ) : null}
      <h3>Важно</h3>
      <ul>
        {safetyNotes.map((item) => (
          <li key={item} className="safe-copy">
            {item}
          </li>
        ))}
      </ul>
    </Card>
  );
}
