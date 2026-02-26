import type { AnalyzeResponse } from "@/lib/contracts/types";

export type DoctorBiomarkerView = {
  name: string;
  value: string;
};

export type DoctorDiagnosisView = {
  name: string;
  icd10?: string;
  stage?: string;
  biomarkers: DoctorBiomarkerView[];
};

export type DoctorComorbidityView = {
  name: string;
  code?: string;
  status?: string;
};

export type DoctorTimelineView = {
  date?: string;
  event: string;
  kind: "therapy" | "diagnostics" | "other";
};

export type DoctorTherapyView = {
  name: string;
  dose?: string;
  schedule?: string;
  status?: string;
};

export type DoctorActionView = {
  text: string;
  priority: string;
  section?: string;
  rationale?: string;
};

export type DoctorContextView = {
  diagnosis: DoctorDiagnosisView | null;
  comorbidities: DoctorComorbidityView[];
  therapy_timeline: DoctorTimelineView[];
  diagnostics_timeline: DoctorTimelineView[];
  current_therapy: DoctorTherapyView[];
  upcoming_actions: DoctorActionView[];
  counters: {
    confidence: number | null;
    cases: number;
    alerts: number;
  };
};

export type DoctorContextMeta = {
  has_diagnosis: boolean;
  has_comorbidities: boolean;
  has_therapy_timeline: boolean;
  has_diagnostics_timeline: boolean;
  has_current_therapy: boolean;
  has_upcoming_actions: boolean;
  missing: string[];
};

export type DoctorAnalyzeBffResponse = {
  analyze_response: AnalyzeResponse;
  doctor_context_view: DoctorContextView;
  context_meta: DoctorContextMeta;
};

