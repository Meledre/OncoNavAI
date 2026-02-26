"use client";

type CaseFactsEntry = {
  key: string;
  value: string;
};

type Props = {
  entries: CaseFactsEntry[];
};

export default function DoctorCaseFactsCard({ entries }: Props) {
  if (entries.length === 0) return null;
  return (
    <>
      <h3>Ключевые факты</h3>
      <ul>
        {entries.map((item) => (
          <li key={item.key}>
            <strong>{item.key}:</strong> <code>{item.value}</code>
          </li>
        ))}
      </ul>
    </>
  );
}
