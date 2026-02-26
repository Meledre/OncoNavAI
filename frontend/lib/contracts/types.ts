export type Language = "ru" | "en";
export type AnalyzeSchemaVersion = "0.2";
export type DoctorReportSchemaVersion = "1.2";
export type DoctorIssueSeverityV1_2 = "critical" | "warning" | "info";
export type DoctorIssueKindV1_2 = "missing_data" | "deviation" | "contraindication" | "inconsistency" | "other";
export type SanityStatusV1_2 = "pass" | "warn" | "fail";
export type QueryType = "NEXT_STEPS" | "CHECK_LAST_TREATMENT";
export type QueryMode = "FULL_ANALYSIS" | "SOURCES_ONLY";
export type DrugSafetyStatus = "ok" | "partial" | "unavailable";

export type DrugEvidenceSpanV1_2 = {
  text: string;
  char_start: number;
  char_end: number;
  page?: number;
};

export type DrugExtractedInnV1_2 = {
  inn: string;
  mentions: string[];
  source: "regimen" | "drug" | "fallback";
  confidence: number;
  evidence_spans: DrugEvidenceSpanV1_2[];
};

export type DrugUnresolvedCandidateV1_2 = {
  mention: string;
  context: string;
  reason: string;
};

export type DrugSafetyProfileV1_2 = {
  inn: string;
  source?: string;
  contraindications_ru: string[];
  warnings_ru: string[];
  interactions_ru: string[];
  adverse_reactions_ru: string[];
  updated_at: string;
};

export type DrugSafetySignalV1_2 = {
  severity: DoctorIssueSeverityV1_2;
  kind: "contraindication" | "inconsistency" | "missing_data";
  summary: string;
  details?: string;
  linked_inn: string[];
  citation_ids: string[];
  source_origin?: "guideline_heuristic" | "rule_engine" | "api_derived" | "supplementary";
};

export type DoctorDrugSafetyV1_2 = {
  status: DrugSafetyStatus;
  extracted_inn: DrugExtractedInnV1_2[];
  unresolved_candidates: DrugUnresolvedCandidateV1_2[];
  profiles: DrugSafetyProfileV1_2[];
  signals: DrugSafetySignalV1_2[];
  warnings: Array<{ code: string; message: string }>;
};

export type PatientDrugSafetyV1_2 = {
  status: DrugSafetyStatus;
  important_risks: string[];
  questions_for_doctor: string[];
};

export type CitationV1_2 = {
  citation_id: string;
  source_id: string;
  document_id: string;
  version_id: string;
  chunk_id?: string;
  page_start: number;
  page_end: number;
  section_path?: string;
  quote?: string;
  file_uri: string;
  official_page_url?: string;
  official_pdf_url?: string;
  score?: number;
};

export type PlanStepV1_2 = {
  step_id: string;
  text: string;
  priority: "high" | "medium" | "low";
  rationale?: string;
  evidence_level?: string;
  recommendation_strength?: string;
  confidence?: number;
  citation_ids: string[];
  depends_on_missing_data?: string[];
};

export type ComparativeClaimV1_2 = {
  claim_id: string;
  text: string;
  comparative_superiority: boolean;
  topic?: string;
  citation_ids: string[];
  pubmed_id?: string;
  pubmed_url?: string;
};

export type PlanSectionV1_2 = {
  section: "diagnostics" | "staging" | "treatment" | "follow_up" | "supportive" | "other";
  title?: string;
  steps: PlanStepV1_2[];
};

export type IssueV1_2 = {
  issue_id: string;
  severity: DoctorIssueSeverityV1_2;
  kind: DoctorIssueKindV1_2;
  summary: string;
  details?: string;
  field_path?: string;
  suggested_questions?: string[];
  citation_ids: string[];
};

export type SanityCheckV1_2 = {
  check_id: string;
  status: SanityStatusV1_2;
  details: string;
};

export type VerificationSummaryV1_2 = {
  category: "OK" | "NOT_COMPLIANT" | "NEEDS_DATA" | "RISK";
  status_line?: string;
  counts: {
    ok: number;
    not_compliant: number;
    needs_data: number;
    risk: number;
  };
};

export type DoctorReportV1_2 = {
  schema_version: DoctorReportSchemaVersion;
  report_id: string;
  request_id: string;
  query_type: QueryType;
  disease_context: Record<string, unknown>;
  case_facts: Record<string, unknown>;
  timeline: Array<Record<string, unknown> | string>;
  consilium_md: string;
  plan: PlanSectionV1_2[];
  issues: IssueV1_2[];
  comparative_claims?: ComparativeClaimV1_2[];
  sanity_checks: SanityCheckV1_2[];
  drug_safety: DoctorDrugSafetyV1_2;
  citations: CitationV1_2[];
  generated_at: string;
  summary_md?: string;
  checklist?: Record<string, unknown>;
  verification_summary?: VerificationSummaryV1_2;
  auto_compare?: Record<string, unknown>;
  disclaimer_md?: string;
};

export type PatientExplainV1_2 = {
  schema_version: "1.2";
  request_id: string;
  summary_plain: string;
  key_points: string[];
  questions_for_doctor: string[];
  what_was_checked: string[];
  safety_notes: string[];
  drug_safety: PatientDrugSafetyV1_2;
  sources_used: string[];
  generated_at: string;
};

export type PatientContextDiagnosis = {
  name?: string;
  icd10?: string;
  stage?: string;
  biomarkers?: Array<{
    name: string;
    value: string;
  }>;
};

export type PatientContextComorbidity = {
  name: string;
  code?: string;
  status?: string;
};

export type PatientContextTimeline = {
  date?: string;
  event: string;
  kind?: "therapy" | "diagnostics" | "other";
};

export type PatientContextTherapy = {
  name: string;
  dose?: string;
  schedule?: string;
  status?: string;
};

export type PatientContextAction = {
  text: string;
  priority?: string;
  section?: string;
  rationale?: string;
};

export type PatientContext = {
  diagnosis?: PatientContextDiagnosis;
  comorbidities?: PatientContextComorbidity[];
  therapy_timeline?: PatientContextTimeline[];
  diagnostics_timeline?: PatientContextTimeline[];
  current_therapy?: PatientContextTherapy[];
  upcoming_actions?: PatientContextAction[];
};

export type RunMetaV0_2 = {
  schema_version?: "0.2";
  request_id?: string;
  timings_ms?: {
    total: number;
    retrieval: number;
    llm: number;
    postprocess: number;
  };
  docs_retrieved_count?: number;
  docs_after_filter_count?: number;
  citations_count?: number;
  evidence_valid_ratio?: number;
  retrieval_engine?: "basic" | "llamaindex" | "other";
  llm_path?: "primary" | "fallback" | "deterministic" | string;
  reasoning_mode?: "compat" | "llm_rag_only" | string;
  vector_backend?: "local" | "qdrant" | string;
  embedding_backend?: "hash" | "openai" | string;
  reranker_backend?: "lexical" | "llm" | string;
  report_generation_path?: "primary" | "fallback" | "deterministic_only" | string;
  fallback_reason?: string;
  retrieval_k?: number;
  rerank_n?: number;
  latency_ms_total?: number;
  kb_version?: string;
  routing_meta?: {
    resolved_disease_id?: string;
    resolved_cancer_type?: string;
    match_strategy?: string;
    source_ids?: string[];
    doc_ids?: string[];
    candidate_chunks?: number;
    baseline_candidate_chunks?: number;
    reduction_ratio?: number;
  };
};

export type InsufficientData = {
  status: boolean;
  reason: string;
};

export type CompatProjectionStatus = {
  valid: boolean;
  errors: string[];
  schema_path?: string;
};

export type AnalyzeCompatibility = {
  doctor_report_v1_1?: CompatProjectionStatus;
  patient_explain_alt?: CompatProjectionStatus;
};

export type AnalyzeResponse = {
  schema_version: AnalyzeSchemaVersion;
  request_id: string;
  doctor_report: DoctorReportV1_2;
  patient_explain?: PatientExplainV1_2;
  run_meta?: RunMetaV0_2;
  insufficient_data?: InsufficientData;
  sources_only_result?: {
    mode: "SOURCES_ONLY";
    items: Array<{
      item_id: string;
      title: string;
      summary: string;
      citation_ids: string[];
      source_ids?: string[];
    }>;
    policy?: string;
  };
  historical_assessment?: {
    requested_as_of_date: string;
    status: "ok" | "insufficient_data";
    reason_code: "ok" | "missing_as_of_date" | "future_as_of_date" | "historical_sources_unavailable";
    current_guideline: {
      as_of_date: string;
      source_ids: string[];
      note: string;
    };
    as_of_date_guideline: {
      as_of_date: string;
      source_ids: string[];
      note: string;
    };
    conflicts: Array<{ topic: string; description: string; citation_ids?: string[] }>;
  };
  meta?: {
    execution_profile: "compat" | "strict_full";
    strict_mode: boolean;
    retrieval_backend: "local" | "qdrant";
    embedding_backend: "hash" | "openai";
    reranker_backend: "lexical" | "llm";
    fail_closed: boolean;
  };
  compatibility?: AnalyzeCompatibility;
};
