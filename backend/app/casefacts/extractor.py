from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from backend.app.casefacts.models import Biomarkers, CaseFacts, EvidenceSpan, Metastasis, TNM, TreatmentCourse


_TNM_PATTERN = re.compile(
    r"\b(?P<prefix>yp|cp|c|p|r)?\s*T\s*(?P<t>(?:is|[0-4xX])(?:[a-cA-C])?)\s*N\s*(?P<n>[0-3xX](?:[a-cA-C])?)\s*M\s*(?P<m>[01xX])\b",
    flags=re.IGNORECASE,
)
_STAGE_GROUP_PATTERN = re.compile(
    r"\b(?:yp\s*stage|p\s*stage|c\s*stage|стадия|stage)\s*[:\-]?\s*(?P<stage>[IVX]{1,4}(?:[A-Ca-c])?)\b"
    r"|\b(?P<stage_rev>[IVX]{1,4}(?:[A-Ca-c])?)\s*(?:стадия|stage)\b",
    flags=re.IGNORECASE,
)

_HER2_PATTERN = re.compile(
    r"\b(?P<alias>HER2(?:/neu)?|ERBB2)\b(?P<context>.{0,48}?)"
    r"(?:(?:IHC|иммуногистохимия)\s*)?(?:score|балл)?\s*[:=]?\s*"
    r"(?P<value>3\+|2\+|1\+|0|positive|negative|pos|neg)(?:\b|(?=[^A-Za-z0-9]))",
    flags=re.IGNORECASE | re.DOTALL,
)
_HER2_IHC_FALLBACK_PATTERN = re.compile(
    r"\bIHC\s*[:=]?\s*(?P<value>3\+|2\+|1\+|0)(?:\b|(?=[^A-Za-z0-9]))",
    flags=re.IGNORECASE,
)

_PDL1_CPS_PATTERN = re.compile(
    r"\bPD[-\s]?L1\b(?P<context>.{0,64}?)(?:\(\s*CPS\s*\)|CPS|combined\s+positive\s+score)\s*[:=]?\s*(?P<cps>\d+(?:[.,]\d+)?)",
    flags=re.IGNORECASE | re.DOTALL,
)
_PDL1_CPS_FALLBACK_PATTERN = re.compile(r"\bCPS\s*[:=]?\s*(?P<cps>\d+(?:[.,]\d+)?)", flags=re.IGNORECASE)

_MSS_PATTERN = re.compile(r"\bMSS\b|microsatellite\s+stable|микросателлит\w*\s+стабил", flags=re.IGNORECASE)
_MSIH_PATTERN = re.compile(r"\bMSI[-\s]?H\b|microsatellite\s+instab\w*|микросателлит\w*\s+нестабил", flags=re.IGNORECASE)
_DMMR_PATTERN = re.compile(r"\bdMMR\b|дефицит\w*\s+MMR", flags=re.IGNORECASE)
_PMMR_PATTERN = re.compile(r"\bpMMR\b|сохран\w*\s+MMR", flags=re.IGNORECASE)

_CLDN_PATTERN = re.compile(
    r"\bCLDN\s*18(?:[.,]\s*2)?\b(?P<context>.{0,56}?)(?P<value>\d{1,3}(?:[.,]\d+)?)\s*%?",
    flags=re.IGNORECASE | re.DOTALL,
)
_CLDN_POSNEG_PATTERN = re.compile(r"\bCLDN\s*18(?:[.,]\s*2)?\b.{0,40}?\b(positive|negative|pos|neg)\b", flags=re.IGNORECASE)

_DATE_TOKEN = r"(?:\d{2}\.\d{2}\.\d{4}|\d{2}\.\d{4})"
_DATE_RANGE_PATTERN = re.compile(rf"(?P<start>{_DATE_TOKEN})\s*[—–-]\s*(?P<end>{_DATE_TOKEN})")
_DATE_FROM_TO_PATTERN = re.compile(
    rf"(?:с|от)\s*(?P<start>{_DATE_TOKEN})\s*(?:г\.?)?\s*(?:по|до)\s*(?P<end>{_DATE_TOKEN})",
    flags=re.IGNORECASE,
)
_THERAPY_LINE_PATTERN = re.compile(
    r"(?P<segment>(?:пхт|хтт|хт|ит|мхт|терап\w*)[^.\n]{0,220}?\b(?P<line>\d{1,2})\s*(?:[- ]?(?:я|й))?\s*линии?\b[^.\n]{0,260})",
    flags=re.IGNORECASE,
)

_MET_SITE_PATTERNS: dict[str, str] = {
    "печень": r"\bпечен[ьи]\b",
    "брюшина": r"\bбрюшин\w*\b|перитоне\w*",
    "легкие": r"\bл[её]гк\w*\b",
    "кости": r"\bкост\w*\b",
    "цнс": r"\bцнс\b|мозг\w*",
}
_MET_TRIGGER_PATTERN = re.compile(r"\b(метастаз\w*|мтс|mts|очаг\w*|поражен\w*|диссемин\w*|имплант\w*)\b", flags=re.IGNORECASE)
_NEGATION_PATTERN = re.compile(r"\b(без|не\s+выявлен\w*|нет|исключен\w*|отрицательн\w*)\b", flags=re.IGNORECASE)

_INR_PATTERN = re.compile(r"\b(?:INR|МНО)\s*[:=]?\s*(\d+(?:[.,]\d+)?)", flags=re.IGNORECASE)
_NEUROPATHY_GRADE_PATTERN = re.compile(
    r"\bнейропат\w*(?:.{0,20}?(?:grade|степен\w*|ctcae)\s*[:=]?\s*(\d))?",
    flags=re.IGNORECASE | re.DOTALL,
)
_AGE_PATTERN = re.compile(r"\b(\d{1,3})\s*лет\b", flags=re.IGNORECASE)
_WEIGHT_PATTERN = re.compile(r"\bвес\b\s*[:=]?\s*(\d{2,3}(?:[.,]\d+)?)\s*кг", flags=re.IGNORECASE)
_CREATININE_VALUE_PATTERN = re.compile(
    r"\b(?:креатинин|creatinine)\b\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*(мкмоль\/л|умоль\/л|mg\/dl)?",
    flags=re.IGNORECASE,
)

_PROGRESSION_PATTERN = re.compile(r"прогресс\w*|progress\w*", flags=re.IGNORECASE)


def _normalize_case_text(case_text: str, case_json: dict[str, Any] | None) -> str:
    base = str(case_text or "").strip()
    if base:
        return base
    if not isinstance(case_json, dict):
        return ""
    return str(case_json.get("notes") or "").strip()


def _parse_page_map(case_json: dict[str, Any] | None) -> dict[int, tuple[int, int]]:
    if not isinstance(case_json, dict):
        return {}
    raw_map = case_json.get("page_map")
    if not isinstance(raw_map, dict):
        return {}
    normalized: dict[int, tuple[int, int]] = {}
    for key, value in raw_map.items():
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


def _evidence_from_match(
    text: str,
    *,
    start: int,
    end: int,
    page_map: dict[int, tuple[int, int]],
    file_id: str | None = None,
) -> EvidenceSpan:
    safe_start = max(0, min(start, len(text)))
    safe_end = max(safe_start, min(end, len(text)))
    return EvidenceSpan(
        source="case_document",
        file_id=file_id,
        page=_page_from_position(page_map, safe_start),
        char_start=safe_start,
        char_end=safe_end,
        text=text[safe_start:safe_end].strip(),
    )


def _canonical_tnm(prefix: str, t_value: str, n_value: str, m_value: str) -> TNM:
    normalized_prefix = str(prefix or "").strip().lower()
    if normalized_prefix not in {"yp", "p", "c", "r"}:
        normalized_prefix = "unknown"
    token = f"{'' if normalized_prefix == 'unknown' else normalized_prefix}T{t_value}N{n_value}M{m_value}"
    token = token.replace(" ", "")
    return TNM(
        prefix=normalized_prefix,  # type: ignore[arg-type]
        tnm=token,
        stage_group=None,
        evidence_spans=[],
    )


def _merge_stage_group(base: TNM, stage_group: str | None) -> TNM:
    if not stage_group:
        return base
    return replace(base, stage_group=stage_group.upper())


def _extract_stage_mentions(text: str, *, page_map: dict[int, tuple[int, int]]) -> list[TNM]:
    mentions: list[TNM] = []
    tnm_spans: list[tuple[int, int]] = []
    for match in _TNM_PATTERN.finditer(text):
        prefix = str(match.group("prefix") or "")
        t_value = str(match.group("t") or "").upper()
        n_value = str(match.group("n") or "").upper()
        m_value = str(match.group("m") or "").upper()
        tnm_item = _canonical_tnm(prefix=prefix, t_value=t_value, n_value=n_value, m_value=m_value)
        tnm_item.evidence_spans.append(
            _evidence_from_match(text, start=match.start(), end=match.end(), page_map=page_map)
        )
        mentions.append(tnm_item)
        tnm_spans.append((match.start(), match.end()))

    for match in _STAGE_GROUP_PATTERN.finditer(text):
        stage_group = str(match.group("stage") or match.group("stage_rev") or "").upper()
        if not stage_group:
            continue
        hint_window = text[max(0, match.start() - 16):match.start()].lower()
        prefix = "unknown"
        if "yp" in hint_window:
            prefix = "yp"
        elif re.search(r"\bp\b", hint_window):
            prefix = "p"
        elif re.search(r"\bc\b", hint_window):
            prefix = "c"
        nearest_index: int | None = None
        nearest_distance = 10_000
        for idx, (start, end) in enumerate(tnm_spans):
            if start <= match.start() <= end:
                nearest_index = idx
                break
            distance = min(abs(match.start() - start), abs(match.start() - end))
            if distance < nearest_distance:
                nearest_distance = distance
                nearest_index = idx
        if nearest_index is not None and nearest_distance <= 48:
            mentions[nearest_index] = _merge_stage_group(mentions[nearest_index], stage_group)
            mentions[nearest_index].evidence_spans.append(
                _evidence_from_match(text, start=match.start(), end=match.end(), page_map=page_map)
            )
            continue
        mention = TNM(
            prefix=prefix,  # type: ignore[arg-type]
            tnm=None,
            stage_group=stage_group,
            evidence_spans=[_evidence_from_match(text, start=match.start(), end=match.end(), page_map=page_map)],
        )
        mentions.append(mention)
    return mentions


def _stage_priority(prefix: str) -> int:
    order = {"yp": 0, "p": 1, "c": 2, "r": 3, "unknown": 4}
    return order.get(prefix, 5)


def _pick_initial_and_current_stage(mentions: list[TNM]) -> tuple[TNM | None, TNM | None]:
    if not mentions:
        return None, None
    initial_stage = mentions[0]
    current_stage = sorted(mentions, key=lambda item: _stage_priority(item.prefix))[0]
    return initial_stage, current_stage


def _her2_interpretation(value: str) -> str:
    token = value.strip().lower()
    if token in {"positive", "pos", "3+"}:
        return "positive"
    if token in {"negative", "neg", "1+", "0"}:
        return "negative"
    return "unknown"


def _extract_biomarkers(text: str, *, page_map: dict[int, tuple[int, int]]) -> Biomarkers:
    her2 = None
    her2_alias = None
    her2_interpretation = "unknown"
    pd_l1_values: list[float] = []
    msi_status = "unknown"
    cldn_percent: float | None = None
    cldn_interpretation = "unknown"
    spans: list[EvidenceSpan] = []

    her2_match = _HER2_PATTERN.search(text)
    if her2_match:
        her2_alias = str(her2_match.group("alias") or "").strip()
        her2 = str(her2_match.group("value") or "").strip()
        her2_interpretation = _her2_interpretation(her2)
        spans.append(_evidence_from_match(text, start=her2_match.start(), end=her2_match.end(), page_map=page_map))
    else:
        for fallback in _HER2_IHC_FALLBACK_PATTERN.finditer(text):
            window = text[max(0, fallback.start() - 60):fallback.start()]
            if re.search(r"HER2|ERBB2", window, flags=re.IGNORECASE):
                her2 = str(fallback.group("value") or "").strip()
                her2_alias = "HER2"
                her2_interpretation = _her2_interpretation(her2)
                spans.append(_evidence_from_match(text, start=fallback.start(), end=fallback.end(), page_map=page_map))
                break

    for match in _PDL1_CPS_PATTERN.finditer(text):
        raw_value = str(match.group("cps") or "").replace(",", ".")
        try:
            pd_l1_values.append(float(raw_value))
        except ValueError:
            continue
        spans.append(_evidence_from_match(text, start=match.start(), end=match.end(), page_map=page_map))

    if not pd_l1_values:
        for match in _PDL1_CPS_FALLBACK_PATTERN.finditer(text):
            left_context = text[max(0, match.start() - 40):match.start()]
            if "PD" not in left_context.upper():
                continue
            raw_value = str(match.group("cps") or "").replace(",", ".")
            try:
                pd_l1_values.append(float(raw_value))
            except ValueError:
                continue
            spans.append(_evidence_from_match(text, start=match.start(), end=match.end(), page_map=page_map))

    if _DMMR_PATTERN.search(text):
        msi_status = "dMMR"
        dm = _DMMR_PATTERN.search(text)
        if dm:
            spans.append(_evidence_from_match(text, start=dm.start(), end=dm.end(), page_map=page_map))
    elif _PMMR_PATTERN.search(text):
        msi_status = "pMMR"
        pm = _PMMR_PATTERN.search(text)
        if pm:
            spans.append(_evidence_from_match(text, start=pm.start(), end=pm.end(), page_map=page_map))
    elif _MSS_PATTERN.search(text):
        msi_status = "MSS"
        mss = _MSS_PATTERN.search(text)
        if mss:
            spans.append(_evidence_from_match(text, start=mss.start(), end=mss.end(), page_map=page_map))
    elif _MSIH_PATTERN.search(text):
        msi_status = "MSI-H"
        msih = _MSIH_PATTERN.search(text)
        if msih:
            spans.append(_evidence_from_match(text, start=msih.start(), end=msih.end(), page_map=page_map))

    cldn_match = _CLDN_PATTERN.search(text)
    if cldn_match:
        raw = str(cldn_match.group("value") or "").replace(",", ".")
        try:
            cldn_percent = float(raw)
            cldn_interpretation = "positive" if cldn_percent > 0 else "negative"
        except ValueError:
            cldn_percent = None
        spans.append(_evidence_from_match(text, start=cldn_match.start(), end=cldn_match.end(), page_map=page_map))
    else:
        cldn_posneg = _CLDN_POSNEG_PATTERN.search(text)
        if cldn_posneg:
            token = str(cldn_posneg.group(1) or "").lower()
            cldn_interpretation = "positive" if token in {"positive", "pos"} else "negative"
            spans.append(
                _evidence_from_match(text, start=cldn_posneg.start(), end=cldn_posneg.end(), page_map=page_map)
            )

    return Biomarkers(
        her2=her2,
        her2_interpretation=her2_interpretation,  # type: ignore[arg-type]
        her2_alias=her2_alias,
        pd_l1_cps_values=pd_l1_values,
        msi_status=msi_status,  # type: ignore[arg-type]
        cldn18_2_percent=cldn_percent,
        cldn18_2_interpretation=cldn_interpretation,  # type: ignore[arg-type]
        evidence_spans=spans,
    )


def _extract_metastases(text: str, *, page_map: dict[int, tuple[int, int]]) -> list[Metastasis]:
    metastases: list[Metastasis] = []
    seen_sites: set[str] = set()

    for segment_match in re.finditer(r"[^.\n\r;]+", text):
        segment = segment_match.group(0)
        if not segment.strip():
            continue
        if not _MET_TRIGGER_PATTERN.search(segment):
            continue
        if _NEGATION_PATTERN.search(segment):
            continue

        for site, pattern in _MET_SITE_PATTERNS.items():
            site_match = re.search(pattern, segment, flags=re.IGNORECASE)
            if not site_match or site in seen_sites:
                continue
            seen_sites.add(site)
            absolute_start = segment_match.start() + site_match.start()
            absolute_end = segment_match.start() + site_match.end()
            metastases.append(
                Metastasis(
                    site=site,
                    evidence_spans=[
                        _evidence_from_match(text, start=absolute_start, end=absolute_end, page_map=page_map),
                    ],
                )
            )
    return metastases


def _extract_treatment_history(text: str, *, page_map: dict[int, tuple[int, int]]) -> list[TreatmentCourse]:
    courses: list[TreatmentCourse] = []
    seen: set[tuple[str, str, str]] = set()

    def _append_course(
        *,
        name: str,
        start: str | None,
        end: str | None,
        response: str | None,
        start_idx: int,
        end_idx: int,
    ) -> None:
        normalized_name = re.sub(r"\s+", " ", str(name or "")).strip(" .,:;")
        if not normalized_name:
            return
        key = (normalized_name.lower(), str(start or ""), str(end or ""))
        if key in seen:
            return
        seen.add(key)
        courses.append(
            TreatmentCourse(
                name=normalized_name,
                start=start,
                end=end,
                response=response,
                evidence_spans=[_evidence_from_match(text, start=start_idx, end=end_idx, page_map=page_map)],
            )
        )

    regimen_patterns = [
        (r"рамуцирумаб\s*\+\s*паклитаксел", "рамуцирумаб + паклитаксел"),
        (r"ramucirumab\s*\+\s*paclitaxel", "ramucirumab + paclitaxel"),
    ]
    for pattern, normalized_name in regimen_patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            window = text[max(0, match.start() - 80): min(len(text), match.end() + 120)]
            date_match = _DATE_RANGE_PATTERN.search(window) or _DATE_FROM_TO_PATTERN.search(window)
            response = "progression" if _PROGRESSION_PATTERN.search(window) else None
            _append_course(
                name=normalized_name,
                start=date_match.group("start") if date_match else None,
                end=date_match.group("end") if date_match else None,
                response=response,
                start_idx=match.start(),
                end_idx=match.end(),
            )

    for match in _THERAPY_LINE_PATTERN.finditer(text):
        segment = str(match.group("segment") or "").strip()
        if not segment:
            continue
        line_token = str(match.group("line") or "").strip()
        segment_start = match.start("segment")
        segment_end = match.end("segment")
        window = text[max(0, segment_start - 80): min(len(text), segment_end + 140)]

        regimen_name = ""
        parens = re.search(r"\(([^()]{3,180})\)", segment)
        if parens:
            regimen_name = str(parens.group(1) or "").strip()
        if not regimen_name:
            tail = re.search(r"\bлинии?\b\s*(?:по\s+схеме\s*[:\-]?)?([^\n.;]{3,180})", segment, flags=re.IGNORECASE)
            if tail:
                candidate = str(tail.group(1) or "").strip()
                candidate = re.sub(r"\b(?:с|от)\s*(?:\d{2}\.\d{2}\.\d{4}|\d{2}\.\d{4}).*$", "", candidate, flags=re.IGNORECASE)
                candidate = re.sub(r"\b(?:по|до)\s*(?:\d{2}\.\d{2}\.\d{4}|\d{2}\.\d{4}).*$", "", candidate, flags=re.IGNORECASE)
                regimen_name = candidate.strip(" .,:;")
        if not regimen_name:
            regimen_name = f"line {line_token} therapy" if line_token else "systemic_therapy"
        if line_token and "line" not in regimen_name.lower():
            regimen_name = f"{regimen_name} (line {line_token})"

        date_match = (
            _DATE_RANGE_PATTERN.search(segment)
            or _DATE_FROM_TO_PATTERN.search(segment)
            or _DATE_RANGE_PATTERN.search(window)
            or _DATE_FROM_TO_PATTERN.search(window)
        )
        response = "progression" if _PROGRESSION_PATTERN.search(window) else None
        _append_course(
            name=regimen_name,
            start=date_match.group("start") if date_match else None,
            end=date_match.group("end") if date_match else None,
            response=response,
            start_idx=segment_start,
            end_idx=segment_end,
        )

    return courses


def _extract_complications(text: str) -> list[str]:
    lowered = text.lower()
    known = [
        "тромбоз воротной вены",
        "портальная гипертензия",
        "асцит",
        "кровотечение",
        "перфорация",
    ]
    return [item for item in known if item in lowered]


def extract_case_facts(case_text: str, case_json: dict[str, Any] | None) -> CaseFacts:
    text = _normalize_case_text(case_text=case_text, case_json=case_json)
    page_map = _parse_page_map(case_json)

    stage_mentions = _extract_stage_mentions(text, page_map=page_map)
    initial_stage, current_stage = _pick_initial_and_current_stage(stage_mentions)
    biomarkers = _extract_biomarkers(text, page_map=page_map)
    metastases = _extract_metastases(text, page_map=page_map)
    treatment_history = _extract_treatment_history(text, page_map=page_map)
    complications = _extract_complications(text)

    unknowns: list[str] = []
    if initial_stage is None and current_stage is None:
        unknowns.append("tnm_stage")
    if not treatment_history:
        unknowns.append("treatment_history")
    if not (
        biomarkers.her2
        or biomarkers.pd_l1_cps_values
        or biomarkers.msi_status != "unknown"
        or biomarkers.cldn18_2_percent is not None
        or biomarkers.cldn18_2_interpretation != "unknown"
    ):
        unknowns.append("biomarkers")
    if not metastases:
        unknowns.append("metastases")

    return CaseFacts(
        initial_stage=initial_stage,
        current_stage=current_stage,
        biomarkers=biomarkers,
        metastases=metastases,
        treatment_history=treatment_history,
        complications=complications,
        key_unknowns=unknowns,
    )


def extract_case_metrics(case_text: str) -> dict[str, Any]:
    text = str(case_text or "")
    inr_values: list[float] = []
    for match in _INR_PATTERN.finditer(text):
        raw = str(match.group(1) or "").replace(",", ".")
        try:
            inr_values.append(float(raw))
        except ValueError:
            continue

    neuropathy_grade: int | None = None
    for match in _NEUROPATHY_GRADE_PATTERN.finditer(text):
        raw_grade = match.group(1)
        if raw_grade is None:
            continue
        try:
            grade = int(raw_grade)
        except ValueError:
            continue
            neuropathy_grade = grade if neuropathy_grade is None else max(neuropathy_grade, grade)

    age: int | None = None
    age_match = _AGE_PATTERN.search(text)
    if age_match:
        try:
            age = int(age_match.group(1))
        except ValueError:
            age = None

    weight_kg: float | None = None
    weight_match = _WEIGHT_PATTERN.search(text)
    if weight_match:
        try:
            weight_kg = float(str(weight_match.group(1) or "").replace(",", "."))
        except ValueError:
            weight_kg = None

    creatinine_value: float | None = None
    creatinine_units: str | None = None
    creatinine_match = _CREATININE_VALUE_PATTERN.search(text)
    if creatinine_match:
        raw = str(creatinine_match.group(1) or "").replace(",", ".")
        try:
            creatinine_value = float(raw)
            units_raw = str(creatinine_match.group(2) or "").strip().lower()
            creatinine_units = units_raw or None
        except ValueError:
            creatinine_value = None
            creatinine_units = None

    sex: str | None = None
    if re.search(r"\b(мужчина|male|муж\.?)\b", text, flags=re.IGNORECASE):
        sex = "male"
    elif re.search(r"\b(женщина|female|жен\.?)\b", text, flags=re.IGNORECASE):
        sex = "female"

    return {
        "inr_max": max(inr_values) if inr_values else None,
        "neuropathy_grade": neuropathy_grade,
        "has_creatinine": bool(re.search(r"\bкреатинин\b|\bcreatinine\b", text, flags=re.IGNORECASE)),
        "has_egfr": bool(re.search(r"\bрскф\b|\begfr\b|\bckd-epi\b", text, flags=re.IGNORECASE)),
        "age": age,
        "weight_kg": weight_kg,
        "sex": sex,
        "creatinine_value": creatinine_value,
        "creatinine_units": creatinine_units,
    }
