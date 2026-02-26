"use client";

type SectionItem = {
  id: string;
  label: string;
};

type Props = {
  sections: SectionItem[];
  testId?: string;
};

export default function DoctorSectionNav({ sections, testId = "doctor-section-nav" }: Props) {
  return (
    <nav className="section-nav" id="doctor-sections" data-testid={testId} aria-label="Разделы отчёта врача">
      {sections.map((section) => (
        <a key={section.id} href={`#${section.id}`}>
          {section.label}
        </a>
      ))}
    </nav>
  );
}
