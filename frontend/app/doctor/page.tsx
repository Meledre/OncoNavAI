"use client";

import { useEffect, useMemo, useState } from "react";

import DoctorProgressSteps from "@/components/doctor/DoctorProgressSteps";
import DoctorSectionNav from "@/components/doctor/DoctorSectionNav";
import EvidenceViewer from "@/components/doctor/EvidenceViewer";
import ExportButtons from "@/components/doctor/ExportButtons";
import type {
  AnalyzeResponse,
  CitationV1_2,
  DoctorIssueSeverityV1_2,
  QueryMode,
  QueryType
} from "@/lib/contracts/types";
import { normalizeAnalyzeResponse } from "@/lib/contracts/validate";
import { projectDoctorContextView } from "@/lib/viewmodels/doctor";
import type { DoctorAnalyzeBffResponse, DoctorContextView, DoctorTimelineView } from "@/lib/viewmodels/types";

type SourcePreset = "minzdrav" | "russco" | "both";
type StageKey = "import" | "analyze" | "build" | null;
type StepState = "todo" | "active" | "done" | "error";
type TimelineMode = "text" | "scale";

let doctorRequestCounter = 0;

type CaseImportResponse = {
  import_run_id: string;
  case_id: string;
  status: string;
};

type CaseImportBatchRun = {
  index: number;
  filename?: string;
  status: string;
  import_run_id?: string;
  case_id?: string;
  error?: string;
};

type CaseImportBatchResponse = {
  batch_id: string;
  total_files: number;
  successful_imports: number;
  failed_imports: number;
  merged_case_id?: string;
  status: string;
  runs: CaseImportBatchRun[];
};

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function parseJsonSafe(raw: string): Record<string, unknown> {
  try {
    return raw ? JSON.parse(raw) : {};
  } catch {
    return { error: raw || "Некорректный JSON-ответ" };
  }
}

function toBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result !== "string") {
        reject(new Error("Не удалось прочитать файл в base64"));
        return;
      }
      const comma = reader.result.indexOf(",");
      resolve(comma >= 0 ? reader.result.slice(comma + 1) : reader.result);
    };
    reader.onerror = () => reject(new Error("Ошибка чтения выбранного файла"));
    reader.readAsDataURL(file);
  });
}

function sourceConfig(sourcePreset: SourcePreset): { mode: "SINGLE" | "AUTO"; source_ids: string[] } {
  if (sourcePreset === "both") {
    return { mode: "AUTO", source_ids: ["minzdrav", "russco", "asco", "esmo", "nccn", "nci_pdq"] };
  }
  return { mode: "SINGLE", source_ids: [sourcePreset] };
}

function severityOrder(value: DoctorIssueSeverityV1_2): number {
  if (value === "critical") return 0;
  if (value === "warning") return 1;
  return 2;
}

function stepStateFromFailure(failedStage: StageKey): { importState: StepState; analyzeState: StepState; buildState: StepState } {
  if (failedStage === "import") return { importState: "error", analyzeState: "todo", buildState: "todo" };
  if (failedStage === "analyze") return { importState: "done", analyzeState: "error", buildState: "todo" };
  if (failedStage === "build") return { importState: "done", analyzeState: "done", buildState: "error" };
  return { importState: "todo", analyzeState: "todo", buildState: "todo" };
}

function normalizeTimeline(raw: unknown): DoctorTimelineView[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .map((entry) => {
      if (typeof entry === "string") {
        return {
          event: entry,
          kind: "other"
        } satisfies DoctorTimelineView;
      }
      if (!isObject(entry)) return null;
      const kindRaw = String(entry.kind || entry.type || "").trim().toLowerCase();
      const kind: DoctorTimelineView["kind"] =
        kindRaw === "therapy" || kindRaw === "diagnostics" || kindRaw === "other"
          ? (kindRaw as DoctorTimelineView["kind"])
          : "other";
      const event = String(entry.event || entry.text || entry.summary || "").trim();
      if (!event) return null;
      return {
        date: String(entry.date || entry.at || entry.timestamp || "").trim() || undefined,
        event,
        kind
      } satisfies DoctorTimelineView;
    })
    .filter((item): item is DoctorTimelineView => Boolean(item));
}

function normalizeDoctorContext(raw: unknown, fallback: DoctorContextView): DoctorContextView {
  if (!isObject(raw)) return fallback;
  const counters = isObject(raw.counters) ? raw.counters : {};
  return {
    diagnosis: isObject(raw.diagnosis) || raw.diagnosis === null ? (raw.diagnosis as DoctorContextView["diagnosis"]) : fallback.diagnosis,
    comorbidities: Array.isArray(raw.comorbidities) ? (raw.comorbidities as DoctorContextView["comorbidities"]) : fallback.comorbidities,
    therapy_timeline: normalizeTimeline(raw.therapy_timeline),
    diagnostics_timeline: normalizeTimeline(raw.diagnostics_timeline),
    current_therapy: Array.isArray(raw.current_therapy) ? (raw.current_therapy as DoctorContextView["current_therapy"]) : fallback.current_therapy,
    upcoming_actions: Array.isArray(raw.upcoming_actions) ? (raw.upcoming_actions as DoctorContextView["upcoming_actions"]) : fallback.upcoming_actions,
    counters: {
      confidence:
        typeof counters.confidence === "number" && Number.isFinite(counters.confidence)
          ? Math.max(0, Math.min(1, counters.confidence))
          : fallback.counters.confidence,
      cases:
        typeof counters.cases === "number" && Number.isFinite(counters.cases) && counters.cases > 0
          ? Math.floor(counters.cases)
          : fallback.counters.cases,
      alerts:
        typeof counters.alerts === "number" && Number.isFinite(counters.alerts) && counters.alerts >= 0
          ? Math.floor(counters.alerts)
          : fallback.counters.alerts
    }
  };
}

function asPercent(value: number | null): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return `${(Math.max(0, Math.min(1, value)) * 100).toFixed(1)}%`;
}

function computeScaleWidth(index: number, total: number): number {
  if (total <= 1) return 100;
  return Math.max(10, Math.floor(((index + 1) / total) * 100));
}

function nextDoctorRequestId(): string {
  doctorRequestCounter += 1;
  return `doctor-${doctorRequestCounter}`;
}

export default function DoctorPage() {
  const [files, setFiles] = useState<File[]>([]);
  const [sourcePreset, setSourcePreset] = useState<SourcePreset>("both");
  const [queryType, setQueryType] = useState<QueryType>("NEXT_STEPS");
  const [queryMode, setQueryMode] = useState<QueryMode>("FULL_ANALYSIS");
  const [historicalAssessment, setHistoricalAssessment] = useState<boolean>(false);
  const [asOfDate, setAsOfDate] = useState<string>("");
  const [requestId, setRequestId] = useState<string>("doctor-pending");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [response, setResponse] = useState<AnalyzeResponse | null>(null);
  const [contextView, setContextView] = useState<DoctorContextView | null>(null);
  const [, setContextMeta] = useState<Record<string, unknown> | null>(null);
  const [importRun, setImportRun] = useState<CaseImportResponse | null>(null);
  const [importBatch, setImportBatch] = useState<CaseImportBatchResponse | null>(null);
  const [failedStage, setFailedStage] = useState<StageKey>(null);
  const [flowStage, setFlowStage] = useState<"idle" | "importing" | "analyzing" | "building" | "done">("idle");

  const [drugTimelineMode, setDrugTimelineMode] = useState<TimelineMode>("text");
  const [diagTimelineMode, setDiagTimelineMode] = useState<TimelineMode>("text");

  useEffect(() => {
    setRequestId((prev) => (prev === "doctor-pending" ? nextDoctorRequestId() : prev));
  }, []);

  const citationById = useMemo(() => {
    const map = new Map<string, CitationV1_2>();
    const citations = response?.doctor_report.citations || [];
    for (const citation of citations) {
      map.set(citation.citation_id, citation);
    }
    return map;
  }, [response]);

  const orderedIssues = useMemo(() => {
    return [...(response?.doctor_report.issues || [])].sort((left, right) => severityOrder(left.severity) - severityOrder(right.severity));
  }, [response]);

  const visibleIssues = useMemo(() => {
    return orderedIssues.filter((issue) => issue.severity === "critical" || issue.severity === "warning");
  }, [orderedIssues]);

  const progress = useMemo<{ importState: StepState; analyzeState: StepState; buildState: StepState }>(() => {
    if (failedStage) return stepStateFromFailure(failedStage);
    if (flowStage === "importing") return { importState: "active", analyzeState: "todo", buildState: "todo" };
    if (flowStage === "analyzing") return { importState: "done", analyzeState: "active", buildState: "todo" };
    if (flowStage === "building") return { importState: "done", analyzeState: "done", buildState: "active" };
    if (flowStage === "done") return { importState: "done", analyzeState: "done", buildState: "done" };
    return { importState: "todo", analyzeState: "todo", buildState: "todo" };
  }, [flowStage, failedStage]);

  function resolveCitations(citationIds: string[]): CitationV1_2[] {
    return citationIds.map((citationId) => citationById.get(citationId)).filter((item): item is CitationV1_2 => Boolean(item));
  }

  async function importAndAnalyze() {
    setError("");
    setResponse(null);
    setContextView(null);
    setContextMeta(null);
    setImportRun(null);
    setImportBatch(null);
    setFailedStage(null);

    if (files.length === 0) {
      setError("Сначала выберите хотя бы один файл кейса (PDF/DOCX/TXT/MD).");
      setFailedStage("import");
      return;
    }

    setLoading(true);
    setFlowStage("importing");
    try {
      let caseId = "";
      if (files.length === 1) {
        const onlyFile = files[0];
        const contentBase64 = await toBase64(onlyFile);
        const importRes = await fetch("/api/case/import-file", {
          method: "POST",
          headers: {
            "content-type": "application/json"
          },
          body: JSON.stringify({
            filename: onlyFile.name,
            content_base64: contentBase64,
            mime_type: onlyFile.type || undefined,
            data_mode: "DEID"
          })
        });
        const importRaw = await importRes.text();
        const importData = parseJsonSafe(importRaw);
        if (!importRes.ok) {
          setError(String(importData.error || importData.detail || `HTTP ${importRes.status}`));
          setFailedStage("import");
          return;
        }
        caseId = String(importData.case_id || "").trim();
        const importRunId = String(importData.import_run_id || "").trim();
        if (!caseId || !importRunId) {
          setError("Импорт вернул неполные данные (нет case_id/import_run_id).");
          setFailedStage("import");
          return;
        }
        setImportRun({
          case_id: caseId,
          import_run_id: importRunId,
          status: String(importData.status || "UNKNOWN")
        });
      } else {
        const batchFiles = await Promise.all(
          files.map(async (item) => ({
            filename: item.name,
            content_base64: await toBase64(item),
            mime_type: item.type || undefined
          }))
        );
        const batchRes = await fetch("/api/case/import/batch", {
          method: "POST",
          headers: {
            "content-type": "application/json"
          },
          body: JSON.stringify({
            files: batchFiles,
            data_mode: "DEID"
          })
        });
        const batchRaw = await batchRes.text();
        const batchData = parseJsonSafe(batchRaw);
        if (!batchRes.ok) {
          setError(String(batchData.error || batchData.detail || `HTTP ${batchRes.status}`));
          setFailedStage("import");
          return;
        }
        const mergedCaseId = String(batchData.merged_case_id || "").trim();
        const runs = Array.isArray(batchData.runs) ? batchData.runs : [];
        setImportBatch({
          batch_id: String(batchData.batch_id || ""),
          total_files: Number(batchData.total_files || files.length),
          successful_imports: Number(batchData.successful_imports || 0),
          failed_imports: Number(batchData.failed_imports || 0),
          merged_case_id: mergedCaseId,
          status: String(batchData.status || "UNKNOWN"),
          runs: runs as CaseImportBatchRun[]
        });
        if (!mergedCaseId) {
          setError("Batch-импорт завершился без merged_case_id. Проверьте загруженные файлы.");
          setFailedStage("import");
          return;
        }
        caseId = mergedCaseId;
        setImportRun({
          case_id: caseId,
          import_run_id: String(batchData.batch_id || ""),
          status: String(batchData.status || "UNKNOWN")
        });
      }

      setFlowStage("analyzing");
      const analyzePayload = {
        schema_version: "0.2",
        request_id: requestId,
        query_type: queryType,
        query_mode: queryMode,
        sources: sourceConfig(sourcePreset),
        language: "ru",
        as_of_date: asOfDate || undefined,
        historical_assessment: historicalAssessment,
        case: { case_id: caseId },
        options: {
          strict_evidence: true,
          max_chunks: 40,
          max_citations: 40,
          timeout_ms: 120000,
          ui_case_count: files.length
        }
      };

      const analyzeRes = await fetch("/api/doctor/analyze", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-client-id": "doctor-ui-release-ru"
        },
        body: JSON.stringify(analyzePayload)
      });
      const analyzeRaw = await analyzeRes.text();
      const envelope = parseJsonSafe(analyzeRaw) as unknown as Partial<DoctorAnalyzeBffResponse>;
      if (!analyzeRes.ok) {
        setError(String((envelope as Record<string, unknown>).error || (envelope as Record<string, unknown>).detail || `HTTP ${analyzeRes.status}`));
        setFailedStage("analyze");
        return;
      }

      setFlowStage("building");
      const normalized = normalizeAnalyzeResponse(envelope.analyze_response || envelope);
      if (!normalized) {
        setError("SCHEMA_VALIDATION_ERROR: ответ не соответствует контракту v1.2.");
        setFailedStage("build");
        return;
      }

      const fallbackProjection = projectDoctorContextView({
        analyzeResponse: normalized,
        requestedCaseCount: files.length
      }).doctorContextView;
      setResponse(normalized);
      setContextView(normalizeDoctorContext(envelope.doctor_context_view, fallbackProjection));
      setContextMeta(isObject(envelope.context_meta) ? (envelope.context_meta as Record<string, unknown>) : null);
      setRequestId(nextDoctorRequestId());
      setFlowStage("done");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Неизвестная ошибка");
      setFailedStage("analyze");
    } finally {
      setLoading(false);
    }
  }

  const sections = [
    { id: "loaded-data", label: "Загруженные данные" },
    { id: "diagnosis", label: "Диагноз и сопутствующие" },
    { id: "summary", label: "Сводка" },
    { id: "drug-timeline", label: "Таймлайн терапии" },
    { id: "diag-timeline", label: "Таймлайн диагностики" },
    { id: "therapy", label: "Проводимая терапия" },
    { id: "plan", label: "План действий" },
    { id: "issues", label: "Клинические замечания" },
    { id: "drug-safety", label: "Безопасность лекарств" },
    { id: "citations", label: "Все цитаты" }
  ];

  const confidenceValue = contextView?.counters.confidence ?? response?.run_meta?.evidence_valid_ratio ?? null;

  return (
    <div data-testid="doctor-layout">
      <div className="header">
        <div className="title-block">
          <span className="subtitle">Режим врача // OncoAI Diagnostic Engine</span>
          <h1>Анализ случая</h1>
        </div>
        <div style={{ display: "flex", gap: "18px", alignItems: "center" }}>
          <div style={{ textAlign: "center" }}>
            <div className="mono muted" style={{ fontSize: "0.6rem" }}>
              AI CONF.
            </div>
            <div className="mono" style={{ color: "var(--accent-glow-bright)" }}>
              {asPercent(confidenceValue)}
            </div>
          </div>
          <div style={{ width: 1, height: 30, background: "var(--border-metal)" }} />
          <div style={{ textAlign: "center" }}>
            <div className="mono muted" style={{ fontSize: "0.6rem" }}>
              КЕЙСЫ
            </div>
            <div className="mono" style={{ color: "var(--accent-bronze)" }}>
              {String(contextView?.counters.cases ?? files.length)}
            </div>
          </div>
          <div style={{ width: 1, height: 30, background: "var(--border-metal)" }} />
          <div style={{ textAlign: "center" }}>
            <div className="mono muted" style={{ fontSize: "0.6rem" }}>
              ALERTS
            </div>
            <div className="mono" style={{ color: "#ff9e9e" }}>
              {String(contextView?.counters.alerts ?? 0)}
            </div>
          </div>
        </div>
      </div>

      <div className="panel" style={{ marginBottom: 12 }}>
        <div className="control-grid">
          <label>
            Файлы кейса
            <input
              type="file"
              multiple
              accept=".pdf,.docx,.txt,.md,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown"
              onChange={(event) => setFiles(Array.from(event.target.files || []))}
            />
          </label>
          <label>
            Дата (as_of)
            <input type="date" value={asOfDate} onChange={(event) => setAsOfDate(event.target.value)} />
          </label>
          <label>
            Источник руководств
            <select value={sourcePreset} onChange={(event) => setSourcePreset(event.target.value as SourcePreset)}>
              <option value="both">Минздрав + RUSSCO + ASCO/ESMO/NCCN</option>
              <option value="minzdrav">Минздрав</option>
              <option value="russco">RUSSCO</option>
            </select>
          </label>
          <label>
            Тип запроса
            <select value={queryType} onChange={(event) => setQueryType(event.target.value as QueryType)}>
              <option value="NEXT_STEPS">Следующий шаг</option>
              <option value="CHECK_LAST_TREATMENT">Проверка терапии</option>
            </select>
          </label>
          <button className="btn btn-primary" disabled={loading || files.length === 0} onClick={importAndAnalyze}>
            {loading ? "Обработка..." : "Анализ"}
          </button>
        </div>

        <div className="control-grid-compact">
          <label>
            Режим
            <div className="action-row">
              <button className={queryMode === "FULL_ANALYSIS" ? "btn btn-primary" : "btn"} onClick={() => setQueryMode("FULL_ANALYSIS")}>FULL</button>
              <button className={queryMode === "SOURCES_ONLY" ? "btn btn-primary" : "btn"} onClick={() => setQueryMode("SOURCES_ONLY")}>SOURCES</button>
            </div>
          </label>
          <label>
            Historical assessment
            <div className="action-row">
              <button className={historicalAssessment ? "btn btn-primary" : "btn"} onClick={() => setHistoricalAssessment((prev) => !prev)}>
                {historicalAssessment ? "ON" : "OFF"}
              </button>
            </div>
          </label>
          <label>
            Request ID
            <input value={requestId} onChange={(event) => setRequestId(event.target.value)} />
          </label>
          <label>
            Экспорт
            <ExportButtons report={response} />
          </label>
        </div>

        {importRun ? <p className="muted">Импорт кейса: {importRun.status} · case_id={importRun.case_id}</p> : null}
        {importBatch ? (
          <p className="muted">
            Batch: {importBatch.successful_imports}/{importBatch.total_files} успешно, {importBatch.failed_imports} ошибок.
          </p>
        ) : null}
        {error ? <p className="error">{error}</p> : null}

        <DoctorProgressSteps
          testId="doctor-progress-steps"
          importState={progress.importState}
          analyzeState={progress.analyzeState}
          buildState={progress.buildState}
        />
      </div>

      {response && contextView ? (
        <div className="doctor-layout-grid">
          <DoctorSectionNav sections={sections} testId="doctor-section-nav" />

          <div className="report-column">
            <details id="loaded-data" className="panel section-anchor" open data-testid="doctor-section-loaded-data">
              <summary style={{ cursor: "pointer" }}>
                <span className="mono" style={{ color: "var(--accent-bronze)", fontSize: "0.65rem" }}>
                  00
                </span>{" "}
                Загруженные данные
              </summary>
              <div style={{ marginTop: 10 }}>
                <div className="terminal-line">
                  <span className="terminal-prompt">◈</span>
                  <span className="terminal-text">{files.length} файл(ов) загружено в импорт-контур.</span>
                </div>
                {importBatch?.runs?.slice(0, 5).map((run) => (
                  <div key={`${run.index}-${run.filename}`} className="terminal-line">
                    <span className="terminal-prompt">◈</span>
                    <span className="terminal-text">{run.filename || `file-${run.index}`}: {run.status}</span>
                  </div>
                ))}
              </div>
            </details>

            <section id="diagnosis" className="panel section-anchor" data-testid="doctor-section-diagnosis">
              <div className="section-head">
                <h3>Полный диагноз и сопутствующие заболевания</h3>
              </div>
              <div className="grid two">
                <div className="panel" style={{ background: "rgba(107,102,255,0.06)" }}>
                  <div className="mono muted" style={{ fontSize: "0.6rem", marginBottom: 6 }}>
                    ОСНОВНОЙ ДИАГНОЗ
                  </div>
                  <p>{contextView.diagnosis?.name || "Не удалось автоматически определить"}</p>
                  <div className="action-row" style={{ marginTop: 6 }}>
                    {contextView.diagnosis?.icd10 ? <span className="status-badge">{contextView.diagnosis.icd10}</span> : null}
                    {contextView.diagnosis?.stage ? <span className="status-badge stable">{contextView.diagnosis.stage}</span> : null}
                  </div>
                  <div className="action-row" style={{ marginTop: 8 }}>
                    {(contextView.diagnosis?.biomarkers || []).map((marker) => (
                      <span key={`${marker.name}:${marker.value}`} className="status-badge">
                        {marker.name}: {marker.value || "—"}
                      </span>
                    ))}
                  </div>
                </div>

                <div className="panel" style={{ background: "rgba(140,123,88,0.06)" }}>
                  <div className="mono muted" style={{ fontSize: "0.6rem", marginBottom: 6 }}>
                    СОПУТСТВУЮЩИЕ
                  </div>
                  {contextView.comorbidities.length > 0 ? (
                    <ul>
                      {contextView.comorbidities.map((item, index) => (
                        <li key={`${item.name}-${index}`}>
                          {item.name}
                          {item.code ? ` (${item.code})` : ""}
                          {item.status ? ` · ${item.status}` : ""}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="muted">Сопутствующие заболевания не выделены автоматически.</p>
                  )}
                </div>
              </div>
            </section>

            <section id="summary" className="panel section-anchor" data-testid="doctor-section-summary">
              <div id="consilium" />
              <div className="section-head">
                <h3>Сводная информация</h3>
                {response.doctor_report.verification_summary ? (
                  <span className="status-badge stable">{response.doctor_report.verification_summary.category}</span>
                ) : null}
              </div>
              <p className="muted">{response.doctor_report.summary_md || response.doctor_report.consilium_md.slice(0, 280) || "Сводка недоступна."}</p>
              {response.sources_only_result ? (
                <div className="panel" style={{ marginTop: 10 }}>
                  <div className="mono" style={{ fontSize: "0.62rem", color: "var(--accent-bronze)", marginBottom: 6 }}>
                    SOURCES_ONLY_RESULT
                  </div>
                  {response.sources_only_result.items.slice(0, 4).map((item) => (
                    <div key={item.item_id} className="terminal-line">
                      <span className="terminal-prompt">◈</span>
                      <span className="terminal-text">{item.title}: {item.summary}</span>
                    </div>
                  ))}
                </div>
              ) : null}
              {response.historical_assessment ? (
                <div className="panel" style={{ marginTop: 10 }}>
                  <div className="mono" style={{ fontSize: "0.62rem", color: "var(--accent-bronze)", marginBottom: 6 }}>
                    HISTORICAL ASSESSMENT
                  </div>
                  <p className="muted">
                    as_of_date={response.historical_assessment.requested_as_of_date} · status={response.historical_assessment.status} · reason={response.historical_assessment.reason_code}
                  </p>
                </div>
              ) : null}
            </section>

            <section id="drug-timeline" className="panel section-anchor" data-testid="doctor-section-timeline">
              <div id="timeline" />
              <div className="section-head">
                <h3>Таймлайн лекарственной терапии</h3>
                <div className="action-row">
                  <button className={drugTimelineMode === "text" ? "btn btn-primary" : "btn"} onClick={() => setDrugTimelineMode("text")}>Текст</button>
                  <button className={drugTimelineMode === "scale" ? "btn btn-primary" : "btn"} onClick={() => setDrugTimelineMode("scale")}>Шкала</button>
                </div>
              </div>
              {contextView.therapy_timeline.length === 0 ? <p className="muted">Терапевтический таймлайн не найден.</p> : null}
              {drugTimelineMode === "text" ? (
                <div className="grid">
                  {contextView.therapy_timeline.map((item, index) => (
                    <div key={`${item.event}-${index}`} className="panel" style={{ background: "rgba(107,102,255,0.05)" }}>
                      <div className="mono muted" style={{ fontSize: "0.62rem" }}>{item.date || "дата не указана"}</div>
                      <div>{item.event}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="grid">
                  {contextView.therapy_timeline.map((item, index) => (
                    <div key={`${item.event}-${index}`}>
                      <div className="mono muted" style={{ marginBottom: 4, fontSize: "0.62rem" }}>
                        {item.event}
                      </div>
                      <div style={{ height: 8, background: "#222", borderRadius: 2 }}>
                        <div
                          style={{
                            width: `${computeScaleWidth(index, contextView.therapy_timeline.length)}%`,
                            height: "100%",
                            background: "rgba(107,102,255,0.6)",
                            boxShadow: "0 0 6px rgba(107,102,255,0.4)"
                          }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>

            <section id="diag-timeline" className="panel section-anchor" data-testid="doctor-section-diagnostics">
              <div className="section-head">
                <h3>Таймлайн диагностики</h3>
                <div className="action-row">
                  <button className={diagTimelineMode === "text" ? "btn btn-primary" : "btn"} onClick={() => setDiagTimelineMode("text")}>Текст</button>
                  <button className={diagTimelineMode === "scale" ? "btn btn-primary" : "btn"} onClick={() => setDiagTimelineMode("scale")}>Шкала</button>
                </div>
              </div>
              {contextView.diagnostics_timeline.length === 0 ? <p className="muted">Диагностический таймлайн не найден.</p> : null}
              {diagTimelineMode === "text" ? (
                <div className="grid">
                  {contextView.diagnostics_timeline.map((item, index) => (
                    <div key={`${item.event}-${index}`} className="panel" style={{ background: "rgba(140,123,88,0.05)" }}>
                      <div className="mono muted" style={{ fontSize: "0.62rem" }}>{item.date || "дата не указана"}</div>
                      <div>{item.event}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="grid">
                  {contextView.diagnostics_timeline.map((item, index) => (
                    <div key={`${item.event}-${index}`}>
                      <div className="mono muted" style={{ marginBottom: 4, fontSize: "0.62rem" }}>{item.event}</div>
                      <div style={{ height: 8, background: "#222", borderRadius: 2 }}>
                        <div
                          style={{
                            width: `${computeScaleWidth(index, contextView.diagnostics_timeline.length)}%`,
                            height: "100%",
                            background: "rgba(140,123,88,0.66)",
                            boxShadow: "0 0 6px rgba(140,123,88,0.4)"
                          }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>

            <section id="therapy" className="panel section-anchor" data-testid="doctor-section-therapy">
              <div className="section-head">
                <h3>Проводимая терапия</h3>
              </div>
              {contextView.current_therapy.length > 0 ? (
                <div className="grid two">
                  {contextView.current_therapy.map((item, index) => (
                    <div key={`${item.name}-${index}`} className="panel" style={{ background: "rgba(107,102,255,0.05)" }}>
                      <div className="mono" style={{ fontSize: "0.62rem", color: "var(--accent-glow-bright)" }}>АКТИВНАЯ ТЕРАПИЯ</div>
                      <p>{item.name}</p>
                      <p className="muted">{item.dose || "доза не указана"}{item.schedule ? ` · ${item.schedule}` : ""}</p>
                      {item.status ? <span className="status-badge stable">{item.status}</span> : null}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="muted">Текущая терапия не определена автоматически.</p>
              )}
            </section>

            <section id="plan" className="panel section-anchor" data-testid="doctor-section-plan">
              <div className="section-head">
                <h3>План действий</h3>
              </div>
              {contextView.upcoming_actions.length > 0 ? (
                <div className="grid">
                  {contextView.upcoming_actions.map((item, index) => (
                    <div key={`${item.text}-${index}`} className="panel" style={{ background: "rgba(107,102,255,0.06)" }}>
                      <div className="mono muted" style={{ fontSize: "0.62rem" }}>
                        PRIORITY {item.priority.toUpperCase()} · {item.section || "other"}
                      </div>
                      <p>{item.text}</p>
                      {item.rationale ? <p className="muted">{item.rationale}</p> : null}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="muted">Нет выделенных next-step действий.</p>
              )}
            </section>

            <section id="issues" className="panel section-anchor" data-testid="doctor-section-issues">
              <div className="section-head">
                <h3>Клинические замечания</h3>
              </div>
              {visibleIssues.length > 0 ? (
                <div className="grid">
                  {visibleIssues.map((issue) => (
                    <div
                      key={issue.issue_id}
                      className="panel"
                      style={{
                        background: issue.severity === "critical" ? "rgba(255,77,77,0.05)" : "rgba(140,123,88,0.05)",
                        borderColor: issue.severity === "critical" ? "rgba(255,77,77,0.3)" : "var(--accent-bronze-dim)"
                      }}
                    >
                      <div className="action-row">
                        <span className={`status-badge ${issue.severity === "critical" ? "critical" : "stable"}`}>{issue.severity}</span>
                        <span className="mono muted">{issue.kind}</span>
                      </div>
                      <p>{issue.summary}</p>
                      {issue.details ? <p className="muted">{issue.details}</p> : null}
                      {issue.citation_ids.length > 0 ? (
                        <details>
                          <summary className="mono" style={{ fontSize: "0.66rem" }}>Источники</summary>
                          <EvidenceViewer citations={resolveCitations(issue.citation_ids)} />
                        </details>
                      ) : null}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="muted">Критичных/предупреждающих замечаний не найдено.</p>
              )}
            </section>

            <section id="drug-safety" className="panel section-anchor" data-testid="doctor-section-drug-safety">
              <div className="section-head">
                <h3>Безопасность лекарств</h3>
                <span className="status-badge stable">{response.doctor_report.drug_safety.status}</span>
              </div>
              {response.doctor_report.drug_safety.signals.length > 0 ? (
                <div className="grid">
                  {response.doctor_report.drug_safety.signals.map((signal, index) => (
                    <div key={`${signal.summary}-${index}`} className="terminal-line">
                      <span className="terminal-prompt">{signal.severity === "critical" ? "⚠" : "◈"}</span>
                      <span className="terminal-text">{signal.summary}{signal.details ? ` · ${signal.details}` : ""}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="muted">Сигналы drug safety отсутствуют.</p>
              )}
              {response.doctor_report.drug_safety.unresolved_candidates.length > 0 ? (
                <p className="muted" style={{ marginTop: 8 }}>
                  Неопознанные кандидаты: {response.doctor_report.drug_safety.unresolved_candidates.slice(0, 5).map((item) => item.mention).join(", ")}
                </p>
              ) : null}
            </section>

            <section id="citations" className="panel section-anchor" data-testid="doctor-section-citations">
              <div className="section-head">
                <h3>Все цитаты</h3>
              </div>
              <EvidenceViewer citations={response.doctor_report.citations} />
            </section>
          </div>

          <aside className="panel" data-testid="doctor-ai-insights">
            <div className="section-head">
              <h3>AI Insights</h3>
              <span className="mono" style={{ color: "var(--accent-glow-bright)" }}>{asPercent(confidenceValue)}</span>
            </div>
            <div style={{ height: 3, background: "#222", marginBottom: 12 }}>
              <div
                style={{
                  height: "100%",
                  width: `${Math.round((confidenceValue || 0) * 100)}%`,
                  background: "linear-gradient(to right,var(--accent-bronze-dim),var(--accent-glow))",
                  boxShadow: "0 0 8px var(--accent-glow)"
                }}
              />
            </div>
            <div className="grid" style={{ marginBottom: 12 }}>
              <div className="terminal-line">
                <span className="terminal-prompt">◈</span>
                <span className="terminal-text">Stage: {contextView.diagnosis?.stage || "—"}</span>
              </div>
              <div className="terminal-line">
                <span className="terminal-prompt">◈</span>
                <span className="terminal-text">ICD10: {contextView.diagnosis?.icd10 || "—"}</span>
              </div>
              <div className="terminal-line">
                <span className="terminal-prompt">◈</span>
                <span className="terminal-text">Comorbidities: {contextView.comorbidities.length}</span>
              </div>
              <div className="terminal-line">
                <span className="terminal-prompt">◈</span>
                <span className="terminal-text">Citations: {response.doctor_report.citations.length}</span>
              </div>
            </div>

            <p className="muted" style={{ marginBottom: 14 }}>
              {response.doctor_report.summary_md || "Сводка не сформирована. Проверьте достаточность данных и качество источников."}
            </p>

            <div className="action-row">
              <button className="btn btn-primary">Отчёт</button>
              <button className="btn">✦</button>
            </div>
          </aside>
        </div>
      ) : null}
    </div>
  );
}
