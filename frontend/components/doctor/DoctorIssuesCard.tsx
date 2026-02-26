"use client";

import EvidenceViewer from "@/components/doctor/EvidenceViewer";
import Card from "@/components/ui/Card";
import Badge from "@/components/ui/Badge";
import type { CitationV1_2, IssueV1_2 } from "@/lib/contracts/types";

type Props = {
  issues: IssueV1_2[];
  resolveCitations: (citationIds: string[]) => CitationV1_2[];
};

function badgeTone(severity: IssueV1_2["severity"]): "critical" | "important" | "note" {
  if (severity === "critical") return "critical";
  if (severity === "warning") return "important";
  return "note";
}

function severityLabel(severity: IssueV1_2["severity"]): string {
  if (severity === "critical") return "критично";
  if (severity === "warning") return "предупреждение";
  return "инфо";
}

export default function DoctorIssuesCard({ issues, resolveCitations }: Props) {
  const visibleIssues = issues.filter((issue) => issue.severity === "critical" || issue.severity === "warning");
  return (
    <>
      <h3>Клинические замечания</h3>
      {visibleIssues.length === 0 ? (
        <p className="muted">Критических и предупреждающих замечаний не выявлено.</p>
      ) : (
        <div className="grid">
          {visibleIssues.map((issue, index) => (
            <Card key={issue.issue_id} variant="flat">
              <div className="section-head">
                <strong>
                  #{index + 1} {issue.summary}
                </strong>
                <Badge tone={badgeTone(issue.severity)}>{severityLabel(issue.severity)}</Badge>
              </div>
              {issue.details ? <p>{issue.details}</p> : null}
              <EvidenceViewer citations={resolveCitations(issue.citation_ids)} />
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
