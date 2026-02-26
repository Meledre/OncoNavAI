from __future__ import annotations

import math
import re
from typing import Any

from backend.app.casefacts.extractor import extract_case_facts
from backend.app.casefacts.models import EvidenceSpan
from backend.app.casefacts.models_v2 import (
    CaseFactsV2,
    Comorbidity,
    LabMeasurement,
    Medication,
    NormalizedMedication,
    PatientFacts,
    UnresolvedMedicationCandidate,
)
from backend.app.drugs.extractor import extract_drugs_and_regimens


_AGE_PATTERN = re.compile(r"\b(\d{1,3})\s*лет\b", flags=re.IGNORECASE)
_BIRTH_YEAR_PATTERN = re.compile(r"\b(19\d{2}|20\d{2})\s*(?:г\.?\s*р\.?|года?\s*рождени\w*)", flags=re.IGNORECASE)
_HEIGHT_PATTERN = re.compile(r"\bрост\b\s*[:=]?\s*(\d{2,3}(?:[.,]\d+)?)\s*см\b", flags=re.IGNORECASE)
_WEIGHT_PATTERN = re.compile(r"\bвес\b\s*[:=]?\s*(\d{2,3}(?:[.,]\d+)?)\s*кг\b", flags=re.IGNORECASE)
_ECOG_PATTERN = re.compile(r"\b(?:ECOG|ЭКОГ)\b\s*[:=]?\s*([0-4])\b", flags=re.IGNORECASE)

_MALE_PATTERN = re.compile(r"\b(мужчина|муж\.?|male)\b", flags=re.IGNORECASE)
_FEMALE_PATTERN = re.compile(r"\b(женщина|жен\.?|female)\b", flags=re.IGNORECASE)

_MEDS_SECTION_PATTERN = re.compile(
    r"\b(?:постоянная\s+терапия|текущие\s+препарат\w*|принимает(?:\s+постоянно)?)\b\s*[:\-]\s*([^\n]+)",
    flags=re.IGNORECASE,
)
_MED_NAME_PATTERN = re.compile(r"^\s*([A-Za-zА-Яа-яЁё\-]+(?:\s+[A-Za-zА-Яа-яЁё\-]+){0,2})")
_MED_DOSE_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?\s*(?:мг|mg|мкг|г|гр|iu|ед|мг/сут|мг/д|мг/кг))", flags=re.IGNORECASE)
_MED_FREQ_PATTERN = re.compile(
    r"(?:\b\d+\s*р\/д\b|\b\d+\s*раз(?:а)?\s*в\s*день\b|утром|вечером|ежедневно|кажд\w+\s+день)",
    flags=re.IGNORECASE,
)

_LAB_PATTERNS: list[tuple[str, re.Pattern[str], str | None]] = [
    ("creatinine", re.compile(r"\bкреатинин\b\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*(мкмоль\/л|ммоль\/л|mg\/dl)?", re.IGNORECASE), None),
    ("egfr", re.compile(r"\b(?:egfr|рскф|ckd-epi)\b\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*([^\s,;]+)?", re.IGNORECASE), None),
    ("hb", re.compile(r"\b(?:hb|гемоглобин)\b\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*(г\/л|g\/l)?", re.IGNORECASE), None),
    ("anc", re.compile(r"\b(?:anc|нейтрофил\w*)\b\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*([^\s,;]+)?", re.IGNORECASE), None),
    ("platelets", re.compile(r"\b(?:тромбоцит\w*|plt)\b\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*([^\s,;]+)?", re.IGNORECASE), None),
    ("bilirubin", re.compile(r"\b(?:билирубин|bilirubin)\b\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*(мкмоль\/л|umol\/l)?", re.IGNORECASE), None),
    ("ast", re.compile(r"\b(?:аст|ast)\b\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*([^\s,;]+)?", re.IGNORECASE), None),
    ("alt", re.compile(r"\b(?:алт|alt)\b\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*([^\s,;]+)?", re.IGNORECASE), None),
    ("inr", re.compile(r"\b(?:inr|мно)\b\s*[:=]?\s*(\d+(?:[.,]\d+)?)", re.IGNORECASE), None),
]
_LAB_DATE_PATTERN = re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\b")

_COMORBIDITY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("хбп", re.compile(r"\b(?:хбп|ckd|хроническ\w+\s+болезн\w+\s+почек)\b", re.IGNORECASE)),
    ("сахарный диабет", re.compile(r"\b(?:сахарн\w+\s+диабет|diabetes)\b", re.IGNORECASE)),
    ("цирроз", re.compile(r"\b(?:цирроз|cirrhosis)\b", re.IGNORECASE)),
    ("артериальная гипертензия", re.compile(r"\b(?:гипертенз\w*|артериальн\w+\s+гиперт\w*)\b", re.IGNORECASE)),
    ("ишемическая болезнь сердца", re.compile(r"\b(?:ишемическ\w+\s+болезн\w+\s+сердц|ибс|coronary)\b", re.IGNORECASE)),
]


def _normalize_case_text(case_text: str, case_json: dict[str, Any] | None) -> str:
    text = str(case_text or "").strip()
    if text:
        return text
    if not isinstance(case_json, dict):
        return ""
    return str(case_json.get("notes") or "").strip()


def _parse_page_map(case_json: dict[str, Any] | None) -> dict[int, tuple[int, int]]:
    if not isinstance(case_json, dict):
        return {}
    raw = case_json.get("page_map")
    if not isinstance(raw, dict):
        return {}
    normalized: dict[int, tuple[int, int]] = {}
    for key, value in raw.items():
        if not isinstance(value, list) or len(value) != 2:
            continue
        try:
            page = int(str(key))
            start = int(value[0])
            end = int(value[1])
        except (TypeError, ValueError):
            continue
        if page <= 0 or start < 0 or end < start:
            continue
        normalized[page] = (start, end)
    return normalized


def _page_from_position(page_map: dict[int, tuple[int, int]], pos: int) -> int | None:
    if not page_map:
        return None
    for page, (start, end) in page_map.items():
        if start <= pos <= end:
            return page
    return None


def _span(text: str, *, start: int, end: int, page_map: dict[int, tuple[int, int]]) -> EvidenceSpan:
    safe_start = max(0, min(int(start), len(text)))
    safe_end = max(safe_start, min(int(end), len(text)))
    return EvidenceSpan(
        source="case_document",
        page=_page_from_position(page_map, safe_start),
        char_start=safe_start,
        char_end=safe_end,
        text=text[safe_start:safe_end].strip(),
    )


def _extract_patient(text: str, *, case_json: dict[str, Any] | None, page_map: dict[int, tuple[int, int]]) -> PatientFacts:
    patient_payload = case_json.get("patient") if isinstance(case_json, dict) and isinstance(case_json.get("patient"), dict) else {}
    spans: list[EvidenceSpan] = []

    sex: str | None = str(patient_payload.get("sex") or "").strip().lower() or None
    if _MALE_PATTERN.search(text):
        match = _MALE_PATTERN.search(text)
        sex = "male"
        if match:
            spans.append(_span(text, start=match.start(), end=match.end(), page_map=page_map))
    elif _FEMALE_PATTERN.search(text):
        match = _FEMALE_PATTERN.search(text)
        sex = "female"
        if match:
            spans.append(_span(text, start=match.start(), end=match.end(), page_map=page_map))

    age: int | None = None
    age_match = _AGE_PATTERN.search(text)
    if age_match:
        age = int(age_match.group(1))
        spans.append(_span(text, start=age_match.start(), end=age_match.end(), page_map=page_map))
    elif isinstance(patient_payload.get("age"), int):
        age = int(patient_payload.get("age"))

    birth_year: int | None = None
    birth_match = _BIRTH_YEAR_PATTERN.search(text)
    if birth_match:
        birth_year = int(birth_match.group(1))
        spans.append(_span(text, start=birth_match.start(), end=birth_match.end(), page_map=page_map))
    elif isinstance(patient_payload.get("birth_year"), int):
        birth_year = int(patient_payload.get("birth_year"))

    height_cm: float | None = None
    height_match = _HEIGHT_PATTERN.search(text)
    if height_match:
        height_cm = float(str(height_match.group(1)).replace(",", "."))
        spans.append(_span(text, start=height_match.start(), end=height_match.end(), page_map=page_map))
    elif isinstance(patient_payload.get("height_cm"), (int, float)):
        height_cm = float(patient_payload.get("height_cm"))

    weight_kg: float | None = None
    weight_match = _WEIGHT_PATTERN.search(text)
    if weight_match:
        weight_kg = float(str(weight_match.group(1)).replace(",", "."))
        spans.append(_span(text, start=weight_match.start(), end=weight_match.end(), page_map=page_map))
    elif isinstance(patient_payload.get("weight_kg"), (int, float)):
        weight_kg = float(patient_payload.get("weight_kg"))

    ecog: int | None = None
    ecog_match = _ECOG_PATTERN.search(text)
    if ecog_match:
        ecog = int(ecog_match.group(1))
        spans.append(_span(text, start=ecog_match.start(), end=ecog_match.end(), page_map=page_map))
    elif isinstance(patient_payload.get("ecog"), int):
        ecog = int(patient_payload.get("ecog"))

    bsa_m2: float | None = None
    if isinstance(height_cm, float) and isinstance(weight_kg, float) and height_cm > 0 and weight_kg > 0:
        bsa_m2 = round(math.sqrt((height_cm * weight_kg) / 3600.0), 4)

    return PatientFacts(
        sex=sex,
        age=age,
        birth_year=birth_year,
        height_cm=height_cm,
        weight_kg=weight_kg,
        ecog=ecog,
        bsa_m2=bsa_m2,
        evidence_spans=spans,
    )


def _extract_medications(text: str, *, page_map: dict[int, tuple[int, int]]) -> list[Medication]:
    meds: list[Medication] = []
    seen: set[str] = set()
    for section_match in _MEDS_SECTION_PATTERN.finditer(text):
        section = str(section_match.group(1) or "").strip()
        if not section:
            continue
        for item in re.split(r"[;,]", section):
            chunk = item.strip().strip(".")
            if not chunk:
                continue
            name_match = _MED_NAME_PATTERN.search(chunk)
            if not name_match:
                continue
            name = str(name_match.group(1) or "").strip().lower()
            if not name or name in seen:
                continue
            seen.add(name)
            dose_match = _MED_DOSE_PATTERN.search(chunk)
            freq_match = _MED_FREQ_PATTERN.search(chunk)
            absolute_start = section_match.start(1) + section.lower().find(chunk.lower())
            absolute_end = absolute_start + len(chunk)
            meds.append(
                Medication(
                    name=name,
                    dose=str(dose_match.group(1) or "").strip() if dose_match else None,
                    frequency=str(freq_match.group(0) or "").strip() if freq_match else None,
                    evidence_spans=[_span(text, start=absolute_start, end=absolute_end, page_map=page_map)],
                )
            )
    return meds


def _extract_labs(text: str, *, page_map: dict[int, tuple[int, int]]) -> list[LabMeasurement]:
    labs: list[LabMeasurement] = []
    date_match = _LAB_DATE_PATTERN.search(text)
    date_value = str(date_match.group(1)) if date_match else None
    for name, pattern, default_units in _LAB_PATTERNS:
        for match in pattern.finditer(text):
            raw_value = str(match.group(1) or "").replace(",", ".")
            try:
                value = float(raw_value)
            except ValueError:
                continue
            units_group = match.group(2) if (match.lastindex or 0) >= 2 else None
            units = str(units_group or default_units or "").strip() or None
            labs.append(
                LabMeasurement(
                    name=name,
                    value=value,
                    units=units,
                    date=date_value,
                    evidence_spans=[_span(text, start=match.start(), end=match.end(), page_map=page_map)],
                )
            )
            break
    return labs


def _extract_comorbidities(text: str, *, page_map: dict[int, tuple[int, int]]) -> list[Comorbidity]:
    out: list[Comorbidity] = []
    seen: set[str] = set()
    for name, pattern in _COMORBIDITY_PATTERNS:
        match = pattern.search(text)
        if not match or name in seen:
            continue
        seen.add(name)
        out.append(
            Comorbidity(
                name=name,
                evidence_spans=[_span(text, start=match.start(), end=match.end(), page_map=page_map)],
            )
        )
    return out


def _convert_drug_evidence_spans(
    *,
    spans: list[Any],
) -> list[EvidenceSpan]:
    out: list[EvidenceSpan] = []
    for item in spans:
        if not hasattr(item, "text"):
            continue
        try:
            start = int(getattr(item, "char_start", 0))
            end = int(getattr(item, "char_end", 0))
        except (TypeError, ValueError):
            continue
        out.append(
            EvidenceSpan(
                source="case_document",
                page=getattr(item, "page", None),
                char_start=max(0, start),
                char_end=max(max(0, start), end),
                text=str(getattr(item, "text", "")).strip(),
            )
        )
    return out


def extract_case_facts_v2(
    case_text: str,
    case_json: dict[str, Any] | None,
    *,
    drug_dictionary_entries: list[dict[str, Any]] | None = None,
    drug_regimen_aliases: list[dict[str, Any]] | None = None,
    drug_synonyms_extra: dict[str, Any] | None = None,
) -> CaseFactsV2:
    text = _normalize_case_text(case_text=case_text, case_json=case_json)
    page_map = _parse_page_map(case_json)
    tumor = extract_case_facts(case_text=text, case_json=case_json).model_dump()

    patient = _extract_patient(text, case_json=case_json, page_map=page_map)
    labs = _extract_labs(text, page_map=page_map)
    meds = _extract_medications(text, page_map=page_map)
    comorbidities = _extract_comorbidities(text, page_map=page_map)
    normalized_meds: list[NormalizedMedication] = []
    unresolved_meds: list[UnresolvedMedicationCandidate] = []
    if isinstance(drug_dictionary_entries, list) and drug_dictionary_entries:
        extracted_drugs, unresolved_candidates = extract_drugs_and_regimens(
            case_text=text,
            entries=drug_dictionary_entries,
            regimens=drug_regimen_aliases if isinstance(drug_regimen_aliases, list) else [],
            synonyms_extra=drug_synonyms_extra if isinstance(drug_synonyms_extra, dict) else {},
            page_map=page_map,
        )
        normalized_meds = [
            NormalizedMedication(
                inn=str(item.inn or "").strip().lower(),
                mentions=[str(value).strip() for value in item.mentions if str(value).strip()],
                source=str(item.source or "").strip() or None,
                confidence=float(item.confidence) if isinstance(item.confidence, (int, float)) else None,
                evidence_spans=_convert_drug_evidence_spans(spans=item.evidence_spans if isinstance(item.evidence_spans, list) else []),
            )
            for item in extracted_drugs
            if str(item.inn or "").strip()
        ]
        unresolved_meds = [
            UnresolvedMedicationCandidate(
                mention=str(item.mention or "").strip(),
                context=str(item.context or "").strip(),
                reason=str(item.reason or "").strip() or "not_found_in_dictionary",
            )
            for item in unresolved_candidates
            if str(item.mention or "").strip()
        ]

    unknowns: list[str] = []
    if not any([patient.sex, patient.age, patient.birth_year]):
        unknowns.append("patient_identity")
    if patient.height_cm is None or patient.weight_kg is None:
        unknowns.append("anthropometry")
    if patient.ecog is None:
        unknowns.append("ecog")
    if not labs:
        unknowns.append("labs")
    if not meds:
        unknowns.append("current_medications")
    if meds and not normalized_meds:
        unknowns.append("medication_inn_normalization")
    if not comorbidities:
        unknowns.append("comorbidities")

    therapy_timeline = tumor.get("treatment_history") if isinstance(tumor.get("treatment_history"), list) else []
    if not therapy_timeline:
        unknowns.append("therapy_timeline")

    return CaseFactsV2(
        patient=patient,
        labs=labs,
        current_medications=meds,
        normalized_medications=normalized_meds,
        unresolved_medication_candidates=unresolved_meds,
        comorbidities=comorbidities,
        tumor=tumor,
        therapy_timeline=therapy_timeline,
        key_unknowns=unknowns,
    )
