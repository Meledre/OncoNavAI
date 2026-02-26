"use client";

import EvidenceViewer from "@/components/doctor/EvidenceViewer";
import Card from "@/components/ui/Card";
import type { CitationV1_2, PlanSectionV1_2 } from "@/lib/contracts/types";

type Props = {
  plan: PlanSectionV1_2[];
  resolveCitations: (citationIds: string[]) => CitationV1_2[];
};

export default function DoctorPlanCard({ plan, resolveCitations }: Props) {
  if (plan.length === 0) return null;

  return (
    <>
      <h3>План</h3>
      <div className="grid">
        {plan.map((section) => (
          <Card key={`${section.section}:${section.title || ""}`} variant="flat">
            <div className="section-head">
              <strong>{section.title || section.section}</strong>
            </div>
            <ol>
              {section.steps.map((step) => (
                <li key={step.step_id}>
                  <p>
                    {step.text} <span className="muted">[{step.priority}]</span>
                  </p>
                  {step.rationale ? <p className="muted">{step.rationale}</p> : null}
                  <EvidenceViewer citations={resolveCitations(step.citation_ids)} emptyLabel="Для этого шага нет подтверждающих цитат." />
                </li>
              ))}
            </ol>
          </Card>
        ))}
      </div>
    </>
  );
}
