from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from backend.app.casefacts.models import EvidenceSpan


@dataclass
class PatientFacts:
    sex: str | None = None
    age: int | None = None
    birth_year: int | None = None
    height_cm: float | None = None
    weight_kg: float | None = None
    ecog: int | None = None
    bsa_m2: float | None = None
    evidence_spans: list[EvidenceSpan] = field(default_factory=list)


@dataclass
class LabMeasurement:
    name: str
    value: float | None = None
    units: str | None = None
    date: str | None = None
    evidence_spans: list[EvidenceSpan] = field(default_factory=list)


@dataclass
class Medication:
    name: str
    dose: str | None = None
    frequency: str | None = None
    evidence_spans: list[EvidenceSpan] = field(default_factory=list)


@dataclass
class Comorbidity:
    name: str
    evidence_spans: list[EvidenceSpan] = field(default_factory=list)


@dataclass
class NormalizedMedication:
    inn: str
    mentions: list[str] = field(default_factory=list)
    source: str | None = None
    confidence: float | None = None
    evidence_spans: list[EvidenceSpan] = field(default_factory=list)


@dataclass
class UnresolvedMedicationCandidate:
    mention: str
    context: str
    reason: str


@dataclass
class CaseFactsV2:
    patient: PatientFacts = field(default_factory=PatientFacts)
    labs: list[LabMeasurement] = field(default_factory=list)
    current_medications: list[Medication] = field(default_factory=list)
    normalized_medications: list[NormalizedMedication] = field(default_factory=list)
    unresolved_medication_candidates: list[UnresolvedMedicationCandidate] = field(default_factory=list)
    comorbidities: list[Comorbidity] = field(default_factory=list)
    tumor: dict[str, Any] = field(default_factory=dict)
    therapy_timeline: list[dict[str, Any]] = field(default_factory=list)
    key_unknowns: list[str] = field(default_factory=list)

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)
