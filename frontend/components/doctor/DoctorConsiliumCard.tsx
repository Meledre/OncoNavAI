"use client";

type Props = {
  consilium: string;
};

export default function DoctorConsiliumCard({ consilium }: Props) {
  if (!consilium.trim()) return null;
  return (
    <details className="doctor-collapsible" data-testid="doctor-consilium-collapsible">
      <summary>Загруженные данные</summary>
      <pre className="doctor-collapsible-content">{consilium}</pre>
    </details>
  );
}
