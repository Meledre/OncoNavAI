import type {
  AnalyzeCompatibility,
  AnalyzeResponse,
  CitationV1_2,
  DoctorDrugSafetyV1_2,
  DoctorIssueKindV1_2,
  DoctorIssueSeverityV1_2,
  DoctorReportV1_2,
  PatientContext,
  PatientDrugSafetyV1_2,
  PatientExplainV1_2,
  PlanSectionV1_2,
  PlanStepV1_2,
  QueryType,
  RunMetaV0_2,
  SanityCheckV1_2,
  VerificationSummaryV1_2
} from "./types";

const NEXT_PUBLIC_ONCOAI_DOCTOR_REPORT_1_0_COMPAT_ENABLED =
  process.env.NEXT_PUBLIC_ONCOAI_DOCTOR_REPORT_1_0_COMPAT_ENABLED !== "false";

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function asNonEmptyString(value: unknown): string | null {
  const text = asString(value).trim();
  return text.length > 0 ? text : null;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item).trim()).filter((item) => item.length > 0);
}

function asNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function asQueryType(value: unknown): QueryType {
  return value === "NEXT_STEPS" || value === "CHECK_LAST_TREATMENT" ? value : "CHECK_LAST_TREATMENT";
}

function asIssueSeverity(value: unknown): DoctorIssueSeverityV1_2 {
  if (value === "critical") return "critical";
  if (value === "warning" || value === "important") return "warning";
  return "info";
}

function asIssueKind(value: unknown): DoctorIssueKindV1_2 {
  if (
    value === "missing_data" ||
    value === "deviation" ||
    value === "contraindication" ||
    value === "inconsistency" ||
    value === "other"
  ) {
    return value;
  }
  if (value === "data_quality") return "missing_data";
  return "other";
}

function normalizeFileUri(fileUri: string): string {
  if (fileUri.startsWith("/api/")) return fileUri;
  if (fileUri.startsWith("/admin/")) return `/api${fileUri}`;
  return fileUri;
}

function fallbackFileUriFromLegacy(entry: Record<string, unknown>): string {
  const docId = asNonEmptyString(entry.doc_id);
  const docVersion = asNonEmptyString(entry.doc_version);
  if (!docId || !docVersion) return "about:blank";
  return `/api/admin/docs/${encodeURIComponent(docId)}/${encodeURIComponent(docVersion)}/pdf`;
}

function parseCitationV1_2(entry: unknown, index: number): CitationV1_2 | null {
  if (!isObject(entry)) return null;
  const citationId = asNonEmptyString(entry.citation_id) || `citation-${index + 1}`;
  const sourceId = asNonEmptyString(entry.source_id) || asNonEmptyString(entry.source_set) || "legacy_source";
  const documentId = asNonEmptyString(entry.document_id) || asNonEmptyString(entry.doc_id) || `document-${index + 1}`;
  const versionId =
    asNonEmptyString(entry.version_id) ||
    asNonEmptyString(entry.doc_version) ||
    `${documentId}:version-${index + 1}`;
  const pageFromLegacyIndex = asNumber(entry.pdf_page_index, 0) + 1;
  const legacyPages = Array.isArray(entry.pages) ? entry.pages : [];
  const legacyFirstPage = legacyPages.length > 0 ? asNumber(legacyPages[0], pageFromLegacyIndex) : pageFromLegacyIndex;
  const pageStart = Math.max(1, asNumber(entry.page_start, legacyFirstPage));
  const pageEnd = Math.max(pageStart, asNumber(entry.page_end, pageStart));
  const fileUriRaw = asNonEmptyString(entry.file_uri) || fallbackFileUriFromLegacy(entry);
  const fileUri = normalizeFileUri(fileUriRaw);
  const sectionPath = asNonEmptyString(entry.section_path) || asNonEmptyString(entry.section_title) || undefined;
  const quote = asNonEmptyString(entry.quote) || undefined;
  const chunkId = asNonEmptyString(entry.chunk_id) || undefined;
  const officialPageUrl =
    asNonEmptyString(entry.official_page_url) || asNonEmptyString(entry.source_page_url) || undefined;
  const officialPdfUrl =
    asNonEmptyString(entry.official_pdf_url) || asNonEmptyString(entry.source_pdf_url) || undefined;
  const scoreValue = entry.score;
  const score = typeof scoreValue === "number" && Number.isFinite(scoreValue) ? scoreValue : undefined;

  return {
    citation_id: citationId,
    source_id: sourceId,
    document_id: documentId,
    version_id: versionId,
    chunk_id: chunkId,
    page_start: pageStart,
    page_end: pageEnd,
    section_path: sectionPath,
    quote,
    file_uri: fileUri,
    official_page_url: officialPageUrl,
    official_pdf_url: officialPdfUrl,
    score
  };
}

function legacyEvidenceCitationId(issueIndex: number, evidenceIndex: number, entry: Record<string, unknown>): string {
  const chunk = asNonEmptyString(entry.chunk_id) || "chunk";
  const doc = asNonEmptyString(entry.doc_id) || "doc";
  const version = asNonEmptyString(entry.doc_version) || "version";
  const page = Math.max(1, asNumber(entry.pdf_page_index, 0) + 1);
  return `legacy-${doc}-${version}-${chunk}-${page}-${issueIndex + 1}-${evidenceIndex + 1}`;
}

function mergeUniqueCitations(input: CitationV1_2[]): CitationV1_2[] {
  const byId = new Map<string, CitationV1_2>();
  for (const citation of input) {
    if (!byId.has(citation.citation_id)) {
      byId.set(citation.citation_id, citation);
    }
  }
  return Array.from(byId.values());
}

function parseLegacyIssueEvidenceCitations(rawIssues: unknown[]): {
  byIssueIndex: Map<number, string[]>;
  citations: CitationV1_2[];
} {
  const byIssueIndex = new Map<number, string[]>();
  const citations: CitationV1_2[] = [];
  rawIssues.forEach((rawIssue, issueIndex) => {
    if (!isObject(rawIssue)) return;
    const evidenceList = Array.isArray(rawIssue.evidence) ? rawIssue.evidence : [];
    const citationIds: string[] = [];
    evidenceList.forEach((rawEvidence, evidenceIndex) => {
      if (!isObject(rawEvidence)) return;
      const citation = parseCitationV1_2(
        {
          ...rawEvidence,
          citation_id: legacyEvidenceCitationId(issueIndex, evidenceIndex, rawEvidence),
          source_id: rawEvidence.source_id ?? rawEvidence.source_set,
          document_id: rawEvidence.document_id ?? rawEvidence.doc_id,
          version_id: rawEvidence.version_id ?? rawEvidence.doc_version,
          page_start: rawEvidence.page_start ?? asNumber(rawEvidence.pdf_page_index, 0) + 1,
          page_end: rawEvidence.page_end ?? asNumber(rawEvidence.pdf_page_index, 0) + 1,
          section_path: rawEvidence.section_path ?? rawEvidence.section_title,
          file_uri: rawEvidence.file_uri ?? fallbackFileUriFromLegacy(rawEvidence)
        },
        evidenceIndex
      );
      if (!citation) return;
      citations.push(citation);
      citationIds.push(citation.citation_id);
    });
    if (citationIds.length > 0) {
      byIssueIndex.set(issueIndex, citationIds);
    }
  });
  return { byIssueIndex, citations: mergeUniqueCitations(citations) };
}

function parseIssueV1_2(entry: unknown, index: number, fallbackCitationIds: string[] = []): DoctorReportV1_2["issues"][number] | null {
  if (!isObject(entry)) return null;
  const summary = asNonEmptyString(entry.summary) || asNonEmptyString(entry.title);
  if (!summary) return null;
  const citationIds = asStringArray(entry.citation_ids);
  return {
    issue_id: asNonEmptyString(entry.issue_id) || `issue-${index + 1}`,
    severity: asIssueSeverity(entry.severity),
    kind: asIssueKind(entry.kind ?? entry.category),
    summary,
    details: asNonEmptyString(entry.details) || asNonEmptyString(entry.description) || undefined,
    field_path: asNonEmptyString(entry.field_path) || undefined,
    suggested_questions: asStringArray(entry.suggested_questions),
    citation_ids: citationIds.length > 0 ? citationIds : fallbackCitationIds
  };
}

function parsePlanStepV1_2(entry: unknown, sectionIndex: number, stepIndex: number): PlanStepV1_2 | null {
  if (!isObject(entry)) return null;
  const text = asNonEmptyString(entry.text);
  if (!text) return null;
  const priority =
    entry.priority === "high" || entry.priority === "medium" || entry.priority === "low" ? entry.priority : "medium";
  return {
    step_id: asNonEmptyString(entry.step_id) || `step-${sectionIndex + 1}-${stepIndex + 1}`,
    text,
    priority,
    rationale: asNonEmptyString(entry.rationale) || undefined,
    evidence_level: asNonEmptyString(entry.evidence_level) || undefined,
    recommendation_strength: asNonEmptyString(entry.recommendation_strength) || undefined,
    confidence:
      typeof entry.confidence === "number" && Number.isFinite(entry.confidence)
        ? Math.max(0, Math.min(1, entry.confidence))
        : undefined,
    citation_ids: asStringArray(entry.citation_ids),
    depends_on_missing_data: asStringArray(entry.depends_on_missing_data)
  };
}

function parsePlanSectionV1_2(entry: unknown, index: number): PlanSectionV1_2 | null {
  if (!isObject(entry)) return null;
  const section =
    entry.section === "diagnostics" ||
    entry.section === "staging" ||
    entry.section === "treatment" ||
    entry.section === "follow_up" ||
    entry.section === "supportive" ||
    entry.section === "other"
      ? entry.section
      : "other";
  const rawSteps = Array.isArray(entry.steps) ? entry.steps : [];
  const steps = rawSteps
    .map((step, stepIndex) => parsePlanStepV1_2(step, index, stepIndex))
    .filter((step): step is PlanStepV1_2 => Boolean(step));
  return {
    section,
    title: asNonEmptyString(entry.title) || undefined,
    steps
  };
}

function parseSanityCheckV1_2(entry: unknown): SanityCheckV1_2 | null {
  if (!isObject(entry)) return null;
  const checkId = asNonEmptyString(entry.check_id);
  if (!checkId) return null;
  const status = entry.status === "pass" || entry.status === "warn" || entry.status === "fail" ? entry.status : "warn";
  return {
    check_id: checkId,
    status,
    details: asString(entry.details || "")
  };
}

function parseVerificationSummary(raw: unknown): VerificationSummaryV1_2 | undefined {
  if (!isObject(raw)) return undefined;
  const categoryRaw = asString(raw.category);
  const category: VerificationSummaryV1_2["category"] =
    categoryRaw === "OK" || categoryRaw === "NOT_COMPLIANT" || categoryRaw === "NEEDS_DATA" || categoryRaw === "RISK"
      ? categoryRaw
      : "NEEDS_DATA";
  const countsRaw = isObject(raw.counts) ? raw.counts : {};
  return {
    category,
    status_line: asNonEmptyString(raw.status_line) || undefined,
    counts: {
      ok: Math.max(0, Math.floor(asNumber(countsRaw.ok, 0))),
      not_compliant: Math.max(0, Math.floor(asNumber(countsRaw.not_compliant, 0))),
      needs_data: Math.max(0, Math.floor(asNumber(countsRaw.needs_data, 0))),
      risk: Math.max(0, Math.floor(asNumber(countsRaw.risk, 0)))
    }
  };
}

function parseComparativeClaims(raw: unknown): DoctorReportV1_2["comparative_claims"] {
  if (!Array.isArray(raw)) return undefined;
  const claims = raw
    .filter((item) => isObject(item))
    .map((item, index) => ({
      claim_id: asNonEmptyString(item.claim_id) || `comparative-claim-${index + 1}`,
      text: asNonEmptyString(item.text) || "",
      comparative_superiority: Boolean(item.comparative_superiority),
      topic: asNonEmptyString(item.topic) || undefined,
      citation_ids: asStringArray(item.citation_ids),
      pubmed_id: asNonEmptyString(item.pubmed_id) || undefined,
      pubmed_url: asNonEmptyString(item.pubmed_url) || undefined
    }))
    .filter((item) => item.text.length > 0 && item.citation_ids.length > 0);
  return claims;
}

function parseDrugSafetyStatus(value: unknown): "ok" | "partial" | "unavailable" {
  if (value === "ok" || value === "partial" || value === "unavailable") return value;
  return "unavailable";
}

function defaultDoctorDrugSafety(): DoctorDrugSafetyV1_2 {
  return {
    status: "unavailable",
    extracted_inn: [],
    unresolved_candidates: [],
    profiles: [],
    signals: [],
    warnings: []
  };
}

function parseDoctorDrugSafety(raw: unknown): DoctorDrugSafetyV1_2 {
  if (!isObject(raw)) return defaultDoctorDrugSafety();
  const extractedInnRaw = Array.isArray(raw.extracted_inn) ? raw.extracted_inn : [];
  const extractedInn = extractedInnRaw
    .filter((item) => isObject(item))
    .map((item) => {
      const sourceRaw = item.source;
      const source =
        sourceRaw === "regimen" || sourceRaw === "drug" || sourceRaw === "fallback" ? sourceRaw : "fallback";
      return {
        inn: asNonEmptyString(item.inn) || "",
        mentions: asStringArray(item.mentions),
        source: source as "regimen" | "drug" | "fallback",
        confidence: typeof item.confidence === "number" ? Math.max(0, Math.min(1, item.confidence)) : 0,
        evidence_spans: (Array.isArray(item.evidence_spans) ? item.evidence_spans : [])
          .filter((span) => isObject(span))
          .map((span) => ({
            text: asNonEmptyString(span.text) || "",
            char_start: asNumber(span.char_start, 0),
            char_end: asNumber(span.char_end, 0),
            page: typeof span.page === "number" ? span.page : undefined
          }))
          .filter((span) => span.text.length > 0)
      };
    })
    .filter((item) => item.inn.length > 0);
  const unresolvedCandidates = (Array.isArray(raw.unresolved_candidates) ? raw.unresolved_candidates : [])
    .filter((item) => isObject(item))
    .map((item) => ({
      mention: asNonEmptyString(item.mention) || "",
      context: asNonEmptyString(item.context) || "",
      reason: asNonEmptyString(item.reason) || ""
    }))
    .filter((item) => item.mention.length > 0);
  const profiles = (Array.isArray(raw.profiles) ? raw.profiles : [])
    .filter((item) => isObject(item))
    .map((item) => ({
      inn: asNonEmptyString(item.inn) || "",
      source: asNonEmptyString(item.source) || undefined,
      contraindications_ru: asStringArray(item.contraindications_ru),
      warnings_ru: asStringArray(item.warnings_ru),
      interactions_ru: asStringArray(item.interactions_ru),
      adverse_reactions_ru: asStringArray(item.adverse_reactions_ru),
      updated_at: asNonEmptyString(item.updated_at) || new Date(0).toISOString()
    }))
    .filter((item) => item.inn.length > 0);
  const signals = (Array.isArray(raw.signals) ? raw.signals : [])
    .filter((item) => isObject(item))
    .map((item) => {
      const kindRaw = item.kind;
      const kind: "contraindication" | "inconsistency" | "missing_data" =
        kindRaw === "contraindication" || kindRaw === "inconsistency" || kindRaw === "missing_data"
          ? kindRaw
          : "inconsistency";
      const sourceOrigin: "guideline_heuristic" | "rule_engine" | "api_derived" | "supplementary" | undefined =
        item.source_origin === "guideline_heuristic" ||
        item.source_origin === "rule_engine" ||
        item.source_origin === "api_derived" ||
        item.source_origin === "supplementary"
          ? item.source_origin
          : undefined;
      return {
        severity: asIssueSeverity(item.severity),
        kind,
        summary: asNonEmptyString(item.summary) || "",
        details: asNonEmptyString(item.details) || undefined,
        linked_inn: asStringArray(item.linked_inn),
        citation_ids: asStringArray(item.citation_ids),
        source_origin: sourceOrigin
      };
    })
    .filter((item) => item.summary.length > 0);
  const warnings = (Array.isArray(raw.warnings) ? raw.warnings : [])
    .filter((item) => isObject(item))
    .map((item) => ({
      code: asNonEmptyString(item.code) || "",
      message: asNonEmptyString(item.message) || ""
    }))
    .filter((item) => item.code.length > 0 && item.message.length > 0);

  return {
    status: parseDrugSafetyStatus(raw.status),
    extracted_inn: extractedInn,
    unresolved_candidates: unresolvedCandidates,
    profiles,
    signals,
    warnings
  };
}

function defaultPatientDrugSafety(): PatientDrugSafetyV1_2 {
  return {
    status: "unavailable",
    important_risks: [],
    questions_for_doctor: []
  };
}

function parsePatientDrugSafety(raw: unknown): PatientDrugSafetyV1_2 {
  if (!isObject(raw)) return defaultPatientDrugSafety();
  return {
    status: parseDrugSafetyStatus(raw.status),
    important_risks: asStringArray(raw.important_risks),
    questions_for_doctor: asStringArray(raw.questions_for_doctor)
  };
}

export function normalizePatientContext(raw: unknown): PatientContext | undefined {
  if (!isObject(raw)) return undefined;

  const diagnosisRaw = isObject(raw.diagnosis) ? raw.diagnosis : {};
  const diagnosisBiomarkers = (Array.isArray(diagnosisRaw.biomarkers) ? diagnosisRaw.biomarkers : [])
    .filter((item) => isObject(item))
    .map((item) => ({
      name: asNonEmptyString(item.name) || "",
      value: asNonEmptyString(item.value) || ""
    }))
    .filter((item) => item.name.length > 0);
  const diagnosis =
    asNonEmptyString(diagnosisRaw.name) ||
    asNonEmptyString(diagnosisRaw.icd10) ||
    asNonEmptyString(diagnosisRaw.stage) ||
    diagnosisBiomarkers.length > 0
      ? {
          name: asNonEmptyString(diagnosisRaw.name) || undefined,
          icd10: asNonEmptyString(diagnosisRaw.icd10) || undefined,
          stage: asNonEmptyString(diagnosisRaw.stage) || undefined,
          biomarkers: diagnosisBiomarkers
        }
      : undefined;

  const comorbidities = (Array.isArray(raw.comorbidities) ? raw.comorbidities : [])
    .filter((item) => isObject(item))
    .map((item) => ({
      name: asNonEmptyString(item.name) || "",
      code: asNonEmptyString(item.code) || undefined,
      status: asNonEmptyString(item.status) || undefined
    }))
    .filter((item) => item.name.length > 0);

  const parseTimeline = (timelineRaw: unknown): PatientContext["therapy_timeline"] =>
    (Array.isArray(timelineRaw) ? timelineRaw : [])
      .map((item) => {
        const row = isObject(item) ? item : {};
        const event = typeof item === "string" ? asNonEmptyString(item) : asNonEmptyString(row.event || row.text || row.summary);
        if (!event) return null;
        const kind: "therapy" | "diagnostics" | "other" | undefined =
          row.kind === "therapy" || row.kind === "diagnostics" || row.kind === "other"
            ? (row.kind as "therapy" | "diagnostics" | "other")
            : row.type === "therapy" || row.type === "diagnostics" || row.type === "other"
              ? (row.type as "therapy" | "diagnostics" | "other")
              : undefined;
        return {
          date: asNonEmptyString(row.date || row.at || row.timestamp) || undefined,
          event,
          kind
        };
      })
      .filter((item): item is NonNullable<typeof item> => Boolean(item));

  const currentTherapy = (Array.isArray(raw.current_therapy) ? raw.current_therapy : [])
    .filter((item) => isObject(item))
    .map((item) => ({
      name: asNonEmptyString(item.name) || "",
      dose: asNonEmptyString(item.dose || item.dosage) || undefined,
      schedule: asNonEmptyString(item.schedule || item.frequency) || undefined,
      status: asNonEmptyString(item.status || item.state) || undefined
    }))
    .filter((item) => item.name.length > 0);

  const upcomingActions = (Array.isArray(raw.upcoming_actions) ? raw.upcoming_actions : [])
    .filter((item) => isObject(item))
    .map((item) => ({
      text: asNonEmptyString(item.text || item.title) || "",
      priority: asNonEmptyString(item.priority) || undefined,
      section: asNonEmptyString(item.section) || undefined,
      rationale: asNonEmptyString(item.rationale) || undefined
    }))
    .filter((item) => item.text.length > 0);

  const context: PatientContext = {
    diagnosis,
    comorbidities,
    therapy_timeline: parseTimeline(raw.therapy_timeline),
    diagnostics_timeline: parseTimeline(raw.diagnostics_timeline),
    current_therapy: currentTherapy,
    upcoming_actions: upcomingActions
  };

  const hasMeaningfulData =
    Boolean(context.diagnosis) ||
    Boolean(context.comorbidities && context.comorbidities.length > 0) ||
    Boolean(context.therapy_timeline && context.therapy_timeline.length > 0) ||
    Boolean(context.diagnostics_timeline && context.diagnostics_timeline.length > 0) ||
    Boolean(context.current_therapy && context.current_therapy.length > 0) ||
    Boolean(context.upcoming_actions && context.upcoming_actions.length > 0);
  return hasMeaningfulData ? context : undefined;
}

function parseDoctorReportCore(raw: Record<string, unknown>, topRequestId: string): DoctorReportV1_2 | null {
  const reportId = asNonEmptyString(raw.report_id);
  if (!reportId) return null;
  const requestId = asNonEmptyString(raw.request_id) || topRequestId;
  const consilium =
    asNonEmptyString(raw.consilium_md) || asNonEmptyString(raw.summary_md) || asNonEmptyString(raw.summary) || "";
  const diseaseContext = isObject(raw.disease_context) ? raw.disease_context : {};
  const caseFacts = isObject(raw.case_facts) ? raw.case_facts : {};
  const timelineRaw = Array.isArray(raw.timeline) ? raw.timeline : [];
  const timeline = timelineRaw
    .filter((item) => isObject(item) || typeof item === "string")
    .map((item) => (typeof item === "string" ? item : (item as Record<string, unknown>)));

  const citationItemsRaw = Array.isArray(raw.citations) ? raw.citations : [];
  const parsedCitations = citationItemsRaw
    .map((item, index) => parseCitationV1_2(item, index))
    .filter((citation): citation is CitationV1_2 => Boolean(citation));

  const issueItemsRaw = Array.isArray(raw.issues) ? raw.issues : [];
  const legacyEvidenceBundle = parseLegacyIssueEvidenceCitations(issueItemsRaw);
  const citations = mergeUniqueCitations([...parsedCitations, ...legacyEvidenceBundle.citations]);
  const citationIdsAvailable = new Set(citations.map((item) => item.citation_id));

  const issues = issueItemsRaw
    .map((item, index) => parseIssueV1_2(item, index, legacyEvidenceBundle.byIssueIndex.get(index) || []))
    .filter((issue): issue is DoctorReportV1_2["issues"][number] => Boolean(issue))
    .map((issue) => ({
      ...issue,
      citation_ids: issue.citation_ids.filter((citationId) => citationIdsAvailable.has(citationId))
    }));

  const planRaw = Array.isArray(raw.plan) ? raw.plan : [];
  const plan = planRaw
    .map((item, index) => parsePlanSectionV1_2(item, index))
    .filter((item): item is PlanSectionV1_2 => Boolean(item))
    .map((section) => ({
      ...section,
      steps: section.steps.map((step) => ({
        ...step,
        citation_ids: step.citation_ids.filter((citationId) => citationIdsAvailable.has(citationId))
      }))
    }));

  const sanityRaw = Array.isArray(raw.sanity_checks) ? raw.sanity_checks : [];
  const sanityChecks = sanityRaw
    .map((item) => parseSanityCheckV1_2(item))
    .filter((item): item is SanityCheckV1_2 => Boolean(item));

  return {
    schema_version: "1.2",
    report_id: reportId,
    request_id: requestId,
    query_type: asQueryType(raw.query_type),
    disease_context: diseaseContext,
    case_facts: caseFacts,
    timeline,
    consilium_md: consilium,
    plan,
    issues,
    comparative_claims: parseComparativeClaims(raw.comparative_claims),
    sanity_checks: sanityChecks,
    drug_safety: parseDoctorDrugSafety(raw.drug_safety),
    citations,
    generated_at: asNonEmptyString(raw.generated_at) || new Date(0).toISOString(),
    summary_md: asNonEmptyString(raw.summary_md) || undefined,
    checklist: isObject(raw.checklist) ? raw.checklist : undefined,
    verification_summary: parseVerificationSummary(raw.verification_summary),
    auto_compare: isObject(raw.auto_compare) ? raw.auto_compare : undefined,
    disclaimer_md: asNonEmptyString(raw.disclaimer_md) || undefined
  };
}

function normalizeLegacyDoctorReportV1_0(raw: Record<string, unknown>, topRequestId: string): DoctorReportV1_2 | null {
  return parseDoctorReportCore(raw, topRequestId);
}

function parseDoctorReportV1_2(raw: unknown, topRequestId: string): DoctorReportV1_2 | null {
  if (!isObject(raw)) return null;
  const schemaVersion = asString(raw.schema_version);
  if (schemaVersion === "1.2") {
    return parseDoctorReportCore(raw, topRequestId);
  }
  if (schemaVersion === "1.0" && NEXT_PUBLIC_ONCOAI_DOCTOR_REPORT_1_0_COMPAT_ENABLED) {
    return normalizeLegacyDoctorReportV1_0(raw, topRequestId);
  }
  return null;
}

function parsePatientExplainV1_2(raw: unknown, topRequestId: string): PatientExplainV1_2 | null {
  if (!isObject(raw)) return null;
  const schemaVersion = asString(raw.schema_version);
  if (!(schemaVersion === "1.2" || (schemaVersion === "1.0" && NEXT_PUBLIC_ONCOAI_DOCTOR_REPORT_1_0_COMPAT_ENABLED))) {
    return null;
  }
  const summary = asNonEmptyString(raw.summary_plain) || asNonEmptyString(raw.summary);
  if (!summary) return null;
  const questions = asStringArray(raw.questions_for_doctor);
  const legacyQuestions = asStringArray(raw.questions_to_ask_doctor);
  const safetyNotes = asStringArray(raw.safety_notes);
  const safetyDisclaimer = asNonEmptyString(raw.safety_disclaimer);
  const resolvedSafetyNotes = safetyNotes.length > 0 ? safetyNotes : safetyDisclaimer ? [safetyDisclaimer] : [];
  const resolvedQuestions = questions.length > 0 ? questions : legacyQuestions;
  if (resolvedQuestions.length === 0 || resolvedSafetyNotes.length === 0) return null;
  return {
    schema_version: "1.2",
    request_id: asNonEmptyString(raw.request_id) || topRequestId,
    summary_plain: summary,
    key_points: asStringArray(raw.key_points),
    questions_for_doctor: resolvedQuestions,
    what_was_checked: asStringArray(raw.what_was_checked),
    safety_notes: resolvedSafetyNotes,
    drug_safety: parsePatientDrugSafety(raw.drug_safety),
    sources_used: asStringArray(raw.sources_used),
    generated_at: asNonEmptyString(raw.generated_at) || new Date(0).toISOString()
  };
}

function parseRoutingMeta(value: unknown): RunMetaV0_2["routing_meta"] | undefined {
  if (!isObject(value)) return undefined;
  return {
    resolved_disease_id: asNonEmptyString(value.resolved_disease_id) || undefined,
    resolved_cancer_type: asNonEmptyString(value.resolved_cancer_type) || undefined,
    match_strategy: asNonEmptyString(value.match_strategy) || undefined,
    source_ids: asStringArray(value.source_ids),
    doc_ids: asStringArray(value.doc_ids),
    candidate_chunks: asNumber(value.candidate_chunks, 0),
    baseline_candidate_chunks: asNumber(value.baseline_candidate_chunks, 0),
    reduction_ratio: typeof value.reduction_ratio === "number" ? value.reduction_ratio : undefined
  };
}

function parseRunMetaV0_2(value: unknown): RunMetaV0_2 | undefined {
  if (!isObject(value)) return undefined;
  const timings = isObject(value.timings_ms)
    ? {
        total: asNumber(value.timings_ms.total, asNumber(value.latency_ms_total, 0)),
        retrieval: asNumber(value.timings_ms.retrieval, 0),
        llm: asNumber(value.timings_ms.llm, 0),
        postprocess: asNumber(value.timings_ms.postprocess, 0)
      }
    : undefined;
  return {
    schema_version: "0.2",
    request_id: asNonEmptyString(value.request_id) || undefined,
    timings_ms: timings,
    docs_retrieved_count: asNumber(value.docs_retrieved_count, asNumber(value.retrieval_k, 0)),
    docs_after_filter_count: asNumber(value.docs_after_filter_count, asNumber(value.rerank_n, 0)),
    citations_count: asNumber(value.citations_count, 0),
    evidence_valid_ratio: typeof value.evidence_valid_ratio === "number" ? value.evidence_valid_ratio : undefined,
    retrieval_engine:
      value.retrieval_engine === "llamaindex" ? "llamaindex" : value.retrieval_engine === "other" ? "other" : "basic",
    llm_path: asNonEmptyString(value.llm_path) || undefined,
    vector_backend: asNonEmptyString(value.vector_backend) || undefined,
    embedding_backend: asNonEmptyString(value.embedding_backend) || undefined,
    reranker_backend: asNonEmptyString(value.reranker_backend) || undefined,
    report_generation_path: asNonEmptyString(value.report_generation_path) || undefined,
    fallback_reason: asNonEmptyString(value.fallback_reason) || undefined,
    retrieval_k: asNumber(value.retrieval_k, 0),
    rerank_n: asNumber(value.rerank_n, 0),
    latency_ms_total: asNumber(value.latency_ms_total, timings?.total ?? 0),
    kb_version: asNonEmptyString(value.kb_version) || undefined,
    routing_meta: parseRoutingMeta(value.routing_meta)
  };
}

function parseInsufficientData(value: unknown): AnalyzeResponse["insufficient_data"] {
  if (!isObject(value)) return undefined;
  return {
    status: Boolean(value.status),
    reason: asNonEmptyString(value.reason) || "Sufficient evidence available."
  };
}

function parseCompatProjectionStatus(value: unknown): AnalyzeCompatibility["doctor_report_v1_1"] | undefined {
  if (!isObject(value)) return undefined;
  return {
    valid: Boolean(value.valid),
    errors: asStringArray(value.errors),
    schema_path: asNonEmptyString(value.schema_path) || undefined
  };
}

function parseCompatibility(value: unknown): AnalyzeCompatibility | undefined {
  if (!isObject(value)) return undefined;
  const doctor = parseCompatProjectionStatus(value.doctor_report_v1_1);
  const patient = parseCompatProjectionStatus(value.patient_explain_alt);
  if (!doctor && !patient) return undefined;
  return {
    doctor_report_v1_1: doctor,
    patient_explain_alt: patient
  };
}

function parseAnalyzeResponseV1_2(payload: unknown): AnalyzeResponse | null {
  if (!isObject(payload)) return null;
  const topRequestId = asNonEmptyString(payload.request_id) || "";
  const doctorReport = parseDoctorReportV1_2(payload.doctor_report, topRequestId);
  if (!doctorReport) return null;
  const requestId = topRequestId || doctorReport.request_id;
  const patientExplain = parsePatientExplainV1_2(payload.patient_explain, requestId);
  const runMeta = parseRunMetaV0_2(payload.run_meta);
  const insufficientData = parseInsufficientData(payload.insufficient_data);
  const compatibility = parseCompatibility(payload.compatibility ?? payload._compatibility);
  const sourcesOnlyResult: AnalyzeResponse["sources_only_result"] = isObject(payload.sources_only_result)
    ? {
        mode: "SOURCES_ONLY",
        items: (Array.isArray(payload.sources_only_result.items) ? payload.sources_only_result.items : [])
          .filter((item) => isObject(item))
          .map((item, index) => ({
            item_id: asNonEmptyString(item.item_id) || `sources-only-item-${index + 1}`,
            title: asNonEmptyString(item.title) || "",
            summary: asNonEmptyString(item.summary) || "",
            citation_ids: asStringArray(item.citation_ids),
            source_ids: asStringArray(item.source_ids)
          }))
          .filter((item) => item.title.length > 0 && item.summary.length > 0),
        policy: asNonEmptyString(payload.sources_only_result.policy) || undefined
      }
    : undefined;
  const historicalAssessment: AnalyzeResponse["historical_assessment"] = isObject(payload.historical_assessment)
    ? {
        requested_as_of_date: asNonEmptyString(payload.historical_assessment.requested_as_of_date) || "",
        status: payload.historical_assessment.status === "insufficient_data" ? "insufficient_data" : "ok",
        reason_code:
          payload.historical_assessment.reason_code === "missing_as_of_date" ||
          payload.historical_assessment.reason_code === "future_as_of_date" ||
          payload.historical_assessment.reason_code === "historical_sources_unavailable"
            ? payload.historical_assessment.reason_code
            : "ok",
        current_guideline: isObject(payload.historical_assessment.current_guideline)
          ? {
              as_of_date: asNonEmptyString(payload.historical_assessment.current_guideline.as_of_date) || "",
              source_ids: asStringArray(payload.historical_assessment.current_guideline.source_ids),
              note: asNonEmptyString(payload.historical_assessment.current_guideline.note) || ""
            }
          : { as_of_date: "", source_ids: [], note: "" },
        as_of_date_guideline: isObject(payload.historical_assessment.as_of_date_guideline)
          ? {
              as_of_date: asNonEmptyString(payload.historical_assessment.as_of_date_guideline.as_of_date) || "",
              source_ids: asStringArray(payload.historical_assessment.as_of_date_guideline.source_ids),
              note: asNonEmptyString(payload.historical_assessment.as_of_date_guideline.note) || ""
            }
          : { as_of_date: "", source_ids: [], note: "" },
        conflicts: (Array.isArray(payload.historical_assessment.conflicts) ? payload.historical_assessment.conflicts : [])
          .filter((item) => isObject(item))
          .map((item) => ({
            topic: asNonEmptyString(item.topic) || "",
            description: asNonEmptyString(item.description) || "",
            citation_ids: asStringArray(item.citation_ids)
          }))
          .filter((item) => item.topic.length > 0 && item.description.length > 0)
      }
    : undefined;
  const meta: AnalyzeResponse["meta"] = isObject(payload.meta)
    ? {
        execution_profile: payload.meta.execution_profile === "strict_full" ? "strict_full" : "compat",
        strict_mode: Boolean(payload.meta.strict_mode),
        retrieval_backend: payload.meta.retrieval_backend === "qdrant" ? "qdrant" : "local",
        embedding_backend: payload.meta.embedding_backend === "openai" ? "openai" : "hash",
        reranker_backend: payload.meta.reranker_backend === "llm" ? "llm" : "lexical",
        fail_closed: Boolean(payload.meta.fail_closed)
      }
    : undefined;
  return {
    schema_version: "0.2",
    request_id: requestId,
    doctor_report: doctorReport,
    patient_explain: patientExplain || undefined,
    run_meta: runMeta,
    insufficient_data: insufficientData,
    sources_only_result: sourcesOnlyResult,
    historical_assessment: historicalAssessment,
    meta,
    compatibility
  };
}

function normalizeLegacyAnalyzeResponseV0(payload: unknown): AnalyzeResponse | null {
  if (!isObject(payload)) return null;
  if (!isObject(payload.doctor_report)) return null;
  const schemaVersion = asString(payload.doctor_report.schema_version);
  if (!(schemaVersion === "0.1" || schemaVersion === "0.2")) return null;
  const requestId = asNonEmptyString(payload.request_id) || asNonEmptyString(payload.doctor_report.request_id) || "";
  const doctorReport = parseDoctorReportCore(payload.doctor_report, requestId);
  if (!doctorReport) return null;
  const patientExplain = parsePatientExplainV1_2(payload.patient_explain, requestId);
  const runMeta = parseRunMetaV0_2(payload.run_meta);
  const insufficientData = parseInsufficientData(payload.insufficient_data);
  const compatibility = parseCompatibility(payload.compatibility ?? payload._compatibility);
  return {
    schema_version: "0.2",
    request_id: requestId || doctorReport.request_id,
    doctor_report: doctorReport,
    patient_explain: patientExplain || undefined,
    run_meta: runMeta,
    insufficient_data: insufficientData,
    meta: isObject(payload.meta)
      ? {
          execution_profile: payload.meta.execution_profile === "strict_full" ? "strict_full" : "compat",
          strict_mode: Boolean(payload.meta.strict_mode),
          retrieval_backend: payload.meta.retrieval_backend === "qdrant" ? "qdrant" : "local",
          embedding_backend: payload.meta.embedding_backend === "openai" ? "openai" : "hash",
          reranker_backend: payload.meta.reranker_backend === "llm" ? "llm" : "lexical",
          fail_closed: Boolean(payload.meta.fail_closed)
        }
      : undefined,
    compatibility
  };
}

export function normalizeAnalyzeResponse(payload: unknown): AnalyzeResponse | null {
  const parsedV12 = parseAnalyzeResponseV1_2(payload);
  if (parsedV12) return parsedV12;
  return normalizeLegacyAnalyzeResponseV0(payload);
}

export function isAnalyzeResponse(payload: unknown): payload is AnalyzeResponse {
  return normalizeAnalyzeResponse(payload) !== null;
}
