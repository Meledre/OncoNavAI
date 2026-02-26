from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Literal


DrugSafetyStatus = Literal["ok", "partial", "unavailable"]
DrugExtractionSource = Literal["regimen", "drug", "fallback"]
DrugSignalKind = Literal["contraindication", "inconsistency", "missing_data"]
DrugSignalSeverity = Literal["critical", "warning", "info"]


@dataclass
class DrugEvidenceSpan:
    text: str
    char_start: int
    char_end: int
    page: int | None = None


@dataclass
class DrugExtractedInn:
    inn: str
    mentions: list[str] = field(default_factory=list)
    source: DrugExtractionSource = "drug"
    confidence: float = 0.0
    evidence_spans: list[DrugEvidenceSpan] = field(default_factory=list)


@dataclass
class DrugUnresolvedCandidate:
    mention: str
    context: str
    reason: str


@dataclass
class DrugSafetyProfile:
    inn: str
    source: str
    contraindications_ru: list[str] = field(default_factory=list)
    warnings_ru: list[str] = field(default_factory=list)
    interactions_ru: list[str] = field(default_factory=list)
    adverse_reactions_ru: list[str] = field(default_factory=list)
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class DrugSafetySignal:
    severity: DrugSignalSeverity
    kind: DrugSignalKind
    summary: str
    details: str = ""
    linked_inn: list[str] = field(default_factory=list)
    citation_ids: list[str] = field(default_factory=list)
    source_origin: str = "guideline_heuristic"


@dataclass
class DrugSafetyWarning:
    code: str
    message: str


@dataclass
class DoctorDrugSafety:
    status: DrugSafetyStatus = "unavailable"
    extracted_inn: list[DrugExtractedInn] = field(default_factory=list)
    unresolved_candidates: list[DrugUnresolvedCandidate] = field(default_factory=list)
    profiles: list[DrugSafetyProfile] = field(default_factory=list)
    signals: list[DrugSafetySignal] = field(default_factory=list)
    warnings: list[DrugSafetyWarning] = field(default_factory=list)

    def model_dump(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class PatientDrugSafety:
    status: DrugSafetyStatus = "unavailable"
    important_risks: list[str] = field(default_factory=list)
    questions_for_doctor: list[str] = field(default_factory=list)

    def model_dump(self) -> dict[str, object]:
        return asdict(self)


def build_patient_drug_safety(payload: DoctorDrugSafety) -> PatientDrugSafety:
    risks: list[str] = []
    for signal in payload.signals:
        summary = str(signal.summary).strip()
        if not summary:
            continue
        if summary in risks:
            continue
        risks.append(summary)
    questions: list[str] = []
    if risks:
        questions.append("Какие риски взаимодействия лекарств критичны в моей ситуации?")
        questions.append("Нужно ли корректировать текущие лекарства с учетом лечения опухоли?")
    if payload.status in {"partial", "unavailable"}:
        questions.append("Какие данные о текущих препаратах стоит уточнить для безопасного лечения?")
    return PatientDrugSafety(status=payload.status, important_risks=risks[:6], questions_for_doctor=questions[:4])
