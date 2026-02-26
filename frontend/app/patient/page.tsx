"use client";

import { useEffect, useMemo, useState } from "react";

import PatientQuestionsCard from "@/components/patient/PatientQuestionsCard";
import PatientSafetyCard from "@/components/patient/PatientSafetyCard";
import PatientSummaryCard from "@/components/patient/PatientSummaryCard";
import type { PatientContext, PatientExplainV1_2 } from "@/lib/contracts/types";
import { normalizePatientContext } from "@/lib/contracts/validate";

type SourcePreset = "minzdrav" | "russco" | "both";
type QueryType = "NEXT_STEPS" | "CHECK_LAST_TREATMENT";

let patientRequestCounter = 0;

type PatientAnalyzeResponse = {
  request_id: string;
  case_id: string;
  import_run_id: string;
  patient_explain: PatientExplainV1_2;
  insufficient_data?: { status: boolean; reason: string };
  patient_context?: PatientContext;
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

function stringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item).trim()).filter((item) => item.length > 0);
}

function normalizePatientExplain(raw: unknown): PatientExplainV1_2 | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const data = raw as Record<string, unknown>;

  const summaryPlain = String(data.summary_plain || data.summary || "").trim();
  if (!summaryPlain) return null;

  const questionsForDoctor = stringArray(data.questions_for_doctor);
  if (questionsForDoctor.length === 0) return null;

  const safetyNotes = stringArray(data.safety_notes);
  if (safetyNotes.length === 0) return null;

  const statusRaw = String(isObject(data.drug_safety) ? (data.drug_safety.status || "") : "").trim().toLowerCase();
  const status = statusRaw === "ok" || statusRaw === "partial" || statusRaw === "unavailable" ? statusRaw : "unavailable";

  return {
    schema_version: "1.2",
    request_id: String(data.request_id || ""),
    summary_plain: summaryPlain,
    key_points: stringArray(data.key_points),
    questions_for_doctor: questionsForDoctor,
    what_was_checked: stringArray(data.what_was_checked),
    safety_notes: safetyNotes,
    drug_safety: {
      status,
      important_risks: stringArray(isObject(data.drug_safety) ? data.drug_safety.important_risks : []),
      questions_for_doctor: stringArray(isObject(data.drug_safety) ? data.drug_safety.questions_for_doctor : [])
    },
    sources_used: stringArray(data.sources_used),
    generated_at: String(data.generated_at || "")
  };
}

function confidenceFromContext(context?: PatientContext): string {
  if (!context) return "—";
  const hasDiagnosis = Boolean(context.diagnosis && (context.diagnosis.name || context.diagnosis.icd10 || context.diagnosis.stage));
  const hasTherapy = Boolean(context.current_therapy && context.current_therapy.length > 0);
  const hasActions = Boolean(context.upcoming_actions && context.upcoming_actions.length > 0);
  const score = [hasDiagnosis, hasTherapy, hasActions].filter(Boolean).length;
  return `${(score / 3 * 100).toFixed(0)}%`;
}

function nextPatientRequestId(): string {
  patientRequestCounter += 1;
  return `patient-${patientRequestCounter}`;
}

export default function PatientPage() {
  const [file, setFile] = useState<File | null>(null);
  const [sourcePreset, setSourcePreset] = useState<SourcePreset>("both");
  const [queryType, setQueryType] = useState<QueryType>("NEXT_STEPS");
  const [requestId, setRequestId] = useState<string>("patient-pending");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [response, setResponse] = useState<PatientAnalyzeResponse | null>(null);

  const patientContext = useMemo(() => response?.patient_context, [response]);

  useEffect(() => {
    setRequestId((prev) => (prev === "patient-pending" ? nextPatientRequestId() : prev));
  }, []);

  async function analyzeForPatient() {
    setError("");
    setResponse(null);

    if (!file) {
      setError("Сначала выберите файл кейса (PDF/DOCX/TXT/MD).");
      return;
    }

    setLoading(true);
    try {
      const contentBase64 = await toBase64(file);
      const payload = {
        filename: file.name,
        content_base64: contentBase64,
        mime_type: file.type || undefined,
        request_id: requestId,
        query_type: queryType,
        sources: sourceConfig(sourcePreset),
        language: "ru"
      };

      const res = await fetch("/api/patient/analyze", {
        method: "POST",
        headers: {
          "content-type": "application/json"
        },
        body: JSON.stringify(payload)
      });
      const raw = await res.text();
      const data = parseJsonSafe(raw);
      if (!res.ok) {
        setError(String(data.error || data.detail || `HTTP ${res.status}`));
        return;
      }

      if (data.doctor_report) {
        setError("Техническая ошибка: в пациентском ответе обнаружен doctor_report.");
        return;
      }

      const explain = normalizePatientExplain(data.patient_explain);
      if (!explain) {
        setError("patient_explain отсутствует или не соответствует контракту v1.2.");
        return;
      }

      setResponse({
        request_id: String(data.request_id || requestId),
        case_id: String(data.case_id || ""),
        import_run_id: String(data.import_run_id || ""),
        patient_explain: explain,
        insufficient_data:
          typeof data.insufficient_data === "object" && data.insufficient_data !== null
            ? (data.insufficient_data as { status: boolean; reason: string })
            : undefined,
        patient_context: normalizePatientContext(data.patient_context)
      });
      setRequestId(nextPatientRequestId());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Неизвестная ошибка");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div data-testid="patient-layout">
      <div className="header">
        <div className="title-block">
          <span className="subtitle">Режим пациента // Личный кабинет</span>
          <h1>Мои данные и лечение</h1>
        </div>
        <div className="action-row">
          <div className="panel" style={{ padding: "8px 12px" }}>
            <div className="mono muted" style={{ fontSize: "0.58rem" }}>AI CONF.</div>
            <div className="mono" style={{ color: "var(--accent-glow-bright)" }}>{confidenceFromContext(patientContext)}</div>
          </div>
        </div>
      </div>

      <div className="panel" style={{ marginBottom: 12 }}>
        <div className="control-grid" style={{ gridTemplateColumns: "1fr 220px 220px auto" }}>
          <label>
            Мой документ (PDF/DOCX/TXT/MD)
            <input
              type="file"
              accept=".pdf,.docx,.txt,.md,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown"
              onChange={(event) => setFile(event.target.files?.[0] || null)}
            />
          </label>
          <label>
            Источники
            <select value={sourcePreset} onChange={(event) => setSourcePreset(event.target.value as SourcePreset)}>
              <option value="both">Минздрав + RUSSCO + ASCO/ESMO</option>
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
          <button className="btn btn-primary" disabled={loading || !file} onClick={analyzeForPatient}>
            {loading ? "Формируем ответ..." : "Получить объяснение"}
          </button>
        </div>
        {error ? <p className="error" style={{ marginTop: 8 }}>{error}</p> : null}
      </div>

      {response ? (
        <div className="doctor-layout-grid" style={{ gridTemplateColumns: "1fr 320px", height: "auto" }}>
          <div className="report-column">
            <section className="panel" data-testid="patient-context-diagnosis">
              <h3 style={{ marginBottom: 10 }}>Ваше заболевание и стадия</h3>
              {patientContext?.diagnosis ? (
                <div className="grid two">
                  <div className="panel" style={{ background: "rgba(107,102,255,0.06)" }}>
                    <div className="mono muted" style={{ fontSize: "0.6rem", marginBottom: 6 }}>ДИАГНОЗ</div>
                    <p>{patientContext.diagnosis.name || "Не указано"}</p>
                    <div className="action-row" style={{ marginTop: 6 }}>
                      {patientContext.diagnosis.icd10 ? <span className="status-badge">{patientContext.diagnosis.icd10}</span> : null}
                      {patientContext.diagnosis.stage ? <span className="status-badge stable">{patientContext.diagnosis.stage}</span> : null}
                    </div>
                    <div className="action-row" style={{ marginTop: 8 }}>
                      {(patientContext.diagnosis.biomarkers || []).map((marker) => (
                        <span key={`${marker.name}:${marker.value}`} className="status-badge">{marker.name}: {marker.value || "—"}</span>
                      ))}
                    </div>
                  </div>
                  <div className="panel" style={{ background: "rgba(140,123,88,0.06)" }}>
                    <div className="mono muted" style={{ fontSize: "0.6rem", marginBottom: 6 }}>СОПУТСТВУЮЩИЕ</div>
                    {patientContext.comorbidities && patientContext.comorbidities.length > 0 ? (
                      <ul>
                        {patientContext.comorbidities.map((item, index) => (
                          <li key={`${item.name}-${index}`}>
                            {item.name}
                            {item.code ? ` (${item.code})` : ""}
                            {item.status ? ` · ${item.status}` : ""}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="muted">Сопутствующие состояния не выделены.</p>
                    )}
                  </div>
                </div>
              ) : (
                <p className="muted">Структурированный patient_context неполный. Показан fallback из patient_explain.</p>
              )}
            </section>

            <PatientSummaryCard
              testId="patient-card-summary"
              summary={response.patient_explain.summary_plain}
              keyPoints={response.patient_explain.key_points}
            />

            {response.insufficient_data?.status ? <p className="warn">Ограниченность данных: {response.insufficient_data.reason}</p> : null}

            <section className="panel" data-testid="patient-context-actions">
              <h3 style={{ marginBottom: 10 }}>План действий</h3>
              {patientContext?.upcoming_actions && patientContext.upcoming_actions.length > 0 ? (
                <div className="grid">
                  {patientContext.upcoming_actions.map((item, index) => (
                    <div key={`${item.text}-${index}`} className="panel" style={{ background: "rgba(107,102,255,0.05)" }}>
                      <div className="mono muted" style={{ fontSize: "0.62rem" }}>
                        PRIORITY {String(item.priority || "medium").toUpperCase()}
                      </div>
                      <p>{item.text}</p>
                      {item.rationale ? <p className="muted">{item.rationale}</p> : null}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="muted">Следуйте рекомендациям лечащего врача и блоку &quot;Что делать дальше&quot;.</p>
              )}
            </section>

            <PatientQuestionsCard testId="patient-card-questions" questions={response.patient_explain.questions_for_doctor} />

            <PatientSafetyCard
              testId="patient-card-safety"
              safetyNotes={response.patient_explain.safety_notes}
              whatWasChecked={response.patient_explain.what_was_checked}
              drugSafety={response.patient_explain.drug_safety}
            />
          </div>

          <aside className="panel">
            <h3 style={{ marginBottom: 10 }}>История и терапия</h3>
            {patientContext?.current_therapy && patientContext.current_therapy.length > 0 ? (
              <div className="grid" style={{ marginBottom: 12 }}>
                {patientContext.current_therapy.map((therapy, index) => (
                  <div key={`${therapy.name}-${index}`} className="terminal-line">
                    <span className="terminal-prompt">◈</span>
                    <span className="terminal-text">
                      {therapy.name}
                      {therapy.dose ? ` · ${therapy.dose}` : ""}
                      {therapy.schedule ? ` · ${therapy.schedule}` : ""}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="muted" style={{ marginBottom: 12 }}>Текущая терапия не выделена из structured context.</p>
            )}

            <h3 style={{ marginBottom: 8 }}>Таймлайн</h3>
            {(patientContext?.diagnostics_timeline || []).slice(0, 8).map((item, index) => (
              <div key={`${item.event}-${index}`} className="terminal-line">
                <span className="terminal-prompt">◈</span>
                <span className="terminal-text">{item.date ? `${item.date} · ` : ""}{item.event}</span>
              </div>
            ))}
            {(!patientContext?.diagnostics_timeline || patientContext.diagnostics_timeline.length === 0) ? (
              <p className="muted">Диагностический таймлайн отсутствует.</p>
            ) : null}
          </aside>
        </div>
      ) : null}
    </div>
  );
}
