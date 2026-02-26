from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal


@dataclass
class EvidenceSpan:
    source: Literal["case_document"] = "case_document"
    file_id: str | None = None
    page: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    text: str = ""


@dataclass
class TNM:
    prefix: Literal["c", "p", "yp", "r", "unknown"] = "unknown"
    tnm: str | None = None
    stage_group: str | None = None
    evidence_spans: list[EvidenceSpan] = field(default_factory=list)


@dataclass
class Biomarkers:
    her2: str | None = None
    her2_interpretation: Literal["positive", "negative", "unknown"] = "unknown"
    her2_alias: str | None = None
    pd_l1_cps_values: list[float] = field(default_factory=list)
    msi_status: Literal["MSI-H", "MSS", "dMMR", "pMMR", "unknown"] = "unknown"
    cldn18_2_percent: float | None = None
    cldn18_2_interpretation: Literal["positive", "negative", "unknown"] = "unknown"
    evidence_spans: list[EvidenceSpan] = field(default_factory=list)


@dataclass
class Metastasis:
    site: str
    evidence_spans: list[EvidenceSpan] = field(default_factory=list)


@dataclass
class TreatmentCourse:
    name: str
    start: str | None = None
    end: str | None = None
    response: str | None = None
    evidence_spans: list[EvidenceSpan] = field(default_factory=list)


@dataclass
class CaseFacts:
    initial_stage: TNM | None = None
    current_stage: TNM | None = None
    biomarkers: Biomarkers = field(default_factory=Biomarkers)
    metastases: list[Metastasis] = field(default_factory=list)
    treatment_history: list[TreatmentCourse] = field(default_factory=list)
    complications: list[str] = field(default_factory=list)
    key_unknowns: list[str] = field(default_factory=list)

    def model_dump(self) -> dict:
        return asdict(self)
