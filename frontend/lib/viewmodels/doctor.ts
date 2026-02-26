import type { AnalyzeResponse } from "@/lib/contracts/types";
import type {
  DoctorActionView,
  DoctorComorbidityView,
  DoctorContextMeta,
  DoctorContextView,
  DoctorDiagnosisView,
  DoctorTherapyView,
  DoctorTimelineView
} from "@/lib/viewmodels/types";

function asObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function asText(value: unknown): string {
  return String(value || "").trim();
}

function asNonEmpty(value: unknown): string | null {
  const text = asText(value);
  return text.length > 0 ? text : null;
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function firstText(...values: unknown[]): string | null {
  for (const value of values) {
    const text = asNonEmpty(value);
    if (text) return text;
  }
  return null;
}

function normalizeBiomarkers(...candidates: unknown[]): DoctorDiagnosisView["biomarkers"] {
  const items: DoctorDiagnosisView["biomarkers"] = [];
  for (const candidate of candidates) {
    if (candidate && typeof candidate === "object" && !Array.isArray(candidate)) {
      for (const [nameRaw, valueRaw] of Object.entries(candidate as Record<string, unknown>)) {
        const name = asNonEmpty(nameRaw);
        const value = asNonEmpty(valueRaw);
        if (!name || !value) continue;
        items.push({ name, value });
      }
      continue;
    }
    for (const entry of asArray(candidate)) {
      const row = asObject(entry);
      const name = firstText(row.name, row.marker, row.biomarker, row.code);
      const value = firstText(row.value, row.result, row.status) || "";
      if (!name) continue;
      items.push({ name, value });
    }
  }
  const dedup = new Map<string, DoctorDiagnosisView["biomarkers"][number]>();
  for (const item of items) {
    const key = `${item.name.toLowerCase()}::${item.value.toLowerCase()}`;
    if (!dedup.has(key)) dedup.set(key, item);
  }
  return Array.from(dedup.values());
}

function normalizeComorbidities(...candidates: unknown[]): DoctorComorbidityView[] {
  const items: DoctorComorbidityView[] = [];
  for (const candidate of candidates) {
    const entries =
      candidate && typeof candidate === "object" && !Array.isArray(candidate) ? [candidate] : asArray(candidate);
    for (const entry of entries) {
      if (typeof entry === "string") {
        const name = asNonEmpty(entry);
        if (name) items.push({ name });
        continue;
      }
      const row = asObject(entry);
      const name = firstText(row.name, row.diagnosis, row.condition, row.title);
      if (!name) continue;
      items.push({
        name,
        code: firstText(row.code, row.icd10) || undefined,
        status: firstText(row.status, row.state) || undefined
      });
    }
  }
  const dedup = new Map<string, DoctorComorbidityView>();
  for (const item of items) {
    const key = item.name.toLowerCase();
    if (!dedup.has(key)) dedup.set(key, item);
  }
  return Array.from(dedup.values());
}

function classifyTimeline(kindHint: string, event: string): DoctorTimelineView["kind"] {
  const value = `${kindHint} ${event}`.toLowerCase();
  const diagnosticsTokens = ["diagn", "кт", "мрт", "анализ", "лаборат", "биопс", "scan", "imaging", "узи"];
  const therapyTokens = ["therapy", "treat", "леч", "химио", "гормон", "иммуно", "препарат", "regimen", "drug"];
  if (diagnosticsTokens.some((token) => value.includes(token))) return "diagnostics";
  if (therapyTokens.some((token) => value.includes(token))) return "therapy";
  return "other";
}

function normalizeTimeline(rawTimeline: unknown): { therapy: DoctorTimelineView[]; diagnostics: DoctorTimelineView[] } {
  const therapy: DoctorTimelineView[] = [];
  const diagnostics: DoctorTimelineView[] = [];
  for (const entry of asArray(rawTimeline)) {
    const row = asObject(entry);
    const event =
      typeof entry === "string"
        ? asNonEmpty(entry)
        : firstText(row.event, row.text, row.summary, row.description, row.title);
    if (!event) continue;
    const kind = classifyTimeline(firstText(row.kind, row.type, row.section, row.category) || "", event);
    const normalized: DoctorTimelineView = {
      date: firstText(row.date, row.at, row.timestamp) || undefined,
      event,
      kind
    };
    if (kind === "therapy") therapy.push(normalized);
    if (kind === "diagnostics") diagnostics.push(normalized);
  }
  return { therapy, diagnostics };
}

function normalizeCurrentTherapy(...candidates: unknown[]): DoctorTherapyView[] {
  const items: DoctorTherapyView[] = [];
  for (const candidate of candidates) {
    const entries =
      candidate && typeof candidate === "object" && !Array.isArray(candidate) ? [candidate] : asArray(candidate);
    for (const entry of entries) {
      if (typeof entry === "string") {
        const name = asNonEmpty(entry);
        if (name) items.push({ name });
        continue;
      }
      const row = asObject(entry);
      const current = row.current;
      if (current && current !== entry) {
        items.push(...normalizeCurrentTherapy(current));
      }
      const name = firstText(row.name, row.drug, row.regimen, row.therapy, row.text);
      if (!name) continue;
      items.push({
        name,
        dose: firstText(row.dose, row.dosage) || undefined,
        schedule: firstText(row.schedule, row.frequency) || undefined,
        status: firstText(row.status, row.state) || undefined
      });
    }
  }
  const dedup = new Map<string, DoctorTherapyView>();
  for (const item of items) {
    const key = item.name.toLowerCase();
    if (!dedup.has(key)) dedup.set(key, item);
  }
  return Array.from(dedup.values());
}

function buildUpcomingActions(plan: AnalyzeResponse["doctor_report"]["plan"]): DoctorActionView[] {
  const actions: DoctorActionView[] = [];
  for (const section of plan || []) {
    for (const step of section.steps || []) {
      const text = asNonEmpty(step.text);
      if (!text) continue;
      actions.push({
        text,
        priority: asText(step.priority || "medium"),
        section: asNonEmpty(section.section) || undefined,
        rationale: asNonEmpty(step.rationale) || undefined
      });
    }
  }
  const rank = new Map<string, number>([
    ["high", 0],
    ["medium", 1],
    ["low", 2]
  ]);
  actions.sort((left, right) => (rank.get(left.priority.toLowerCase()) ?? 9) - (rank.get(right.priority.toLowerCase()) ?? 9));
  return actions.slice(0, 8);
}

function inferCasesCount(casePayload: unknown, fallback = 1): number {
  const record = asObject(casePayload);
  for (const key of ["documents", "files", "attachments", "sources"]) {
    const value = record[key];
    if (Array.isArray(value) && value.length > 0) return value.length;
  }
  return fallback;
}

function resolveConfidence(runMeta: AnalyzeResponse["run_meta"]): number | null {
  if (!runMeta) return null;
  const ratio = runMeta.evidence_valid_ratio;
  if (typeof ratio === "number" && Number.isFinite(ratio)) return Math.max(0, Math.min(1, ratio));
  return null;
}

export function projectDoctorContextView(args: {
  analyzeResponse: AnalyzeResponse;
  casePayload?: unknown;
  requestedCaseCount?: number;
}): { doctorContextView: DoctorContextView; contextMeta: DoctorContextMeta } {
  const report = args.analyzeResponse.doctor_report;
  const diseaseContext = asObject(report.disease_context);
  const caseFacts = asObject(report.case_facts);

  const diagnosisName = firstText(
    diseaseContext.diagnosis_name,
    diseaseContext.diagnosis,
    diseaseContext.disease_name,
    caseFacts.diagnosis_name,
    caseFacts.diagnosis,
    caseFacts.disease_name,
    caseFacts.nosology
  );
  const diagnosisIcd10 = firstText(diseaseContext.icd10, diseaseContext.icd10_code, caseFacts.icd10, caseFacts.icd10_code);
  const diagnosisStage = firstText(
    diseaseContext.stage,
    diseaseContext.stage_group,
    caseFacts.stage,
    caseFacts.stage_group,
    caseFacts.tnm_stage
  );
  const diagnosisBiomarkers = normalizeBiomarkers(
    diseaseContext.biomarkers,
    caseFacts.biomarkers,
    caseFacts.molecular_markers
  );
  const diagnosis: DoctorDiagnosisView | null =
    diagnosisName || diagnosisIcd10 || diagnosisStage || diagnosisBiomarkers.length > 0
      ? {
          name: diagnosisName || "Не указано",
          icd10: diagnosisIcd10 || undefined,
          stage: diagnosisStage || undefined,
          biomarkers: diagnosisBiomarkers
        }
      : null;

  const comorbidities = normalizeComorbidities(caseFacts.comorbidities, diseaseContext.comorbidities);
  const timelines = normalizeTimeline(report.timeline);
  let currentTherapy = normalizeCurrentTherapy(caseFacts.current_therapy, caseFacts.therapy, caseFacts.treatment);
  if (currentTherapy.length === 0 && timelines.therapy.length > 0) {
    currentTherapy = timelines.therapy.slice(-2).map((item) => ({ name: item.event }));
  }
  const upcomingActions = buildUpcomingActions(report.plan);
  const issueAlerts = (report.issues || []).filter((item) => item.severity === "critical" || item.severity === "warning").length;
  const drugAlerts = (report.drug_safety.signals || []).filter(
    (item) => item.severity === "critical" || item.severity === "warning"
  ).length;

  const doctorContextView: DoctorContextView = {
    diagnosis,
    comorbidities,
    therapy_timeline: timelines.therapy,
    diagnostics_timeline: timelines.diagnostics,
    current_therapy: currentTherapy,
    upcoming_actions: upcomingActions,
    counters: {
      confidence: resolveConfidence(args.analyzeResponse.run_meta),
      cases: Math.max(1, args.requestedCaseCount || inferCasesCount(args.casePayload)),
      alerts: issueAlerts + drugAlerts
    }
  };

  const missing: string[] = [];
  if (!doctorContextView.diagnosis) missing.push("diagnosis");
  if (doctorContextView.comorbidities.length === 0) missing.push("comorbidities");
  if (doctorContextView.therapy_timeline.length === 0) missing.push("therapy_timeline");
  if (doctorContextView.diagnostics_timeline.length === 0) missing.push("diagnostics_timeline");
  if (doctorContextView.current_therapy.length === 0) missing.push("current_therapy");
  if (doctorContextView.upcoming_actions.length === 0) missing.push("upcoming_actions");

  const contextMeta: DoctorContextMeta = {
    has_diagnosis: !missing.includes("diagnosis"),
    has_comorbidities: !missing.includes("comorbidities"),
    has_therapy_timeline: !missing.includes("therapy_timeline"),
    has_diagnostics_timeline: !missing.includes("diagnostics_timeline"),
    has_current_therapy: !missing.includes("current_therapy"),
    has_upcoming_actions: !missing.includes("upcoming_actions"),
    missing
  };

  return { doctorContextView, contextMeta };
}

