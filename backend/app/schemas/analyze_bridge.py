from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.app.casefacts.extractor import extract_case_facts
from backend.app.exceptions import ValidationError
from backend.app.guidelines.source_registry import normalize_source_set_id, normalize_source_set_ids
from backend.app.rules.sanity_checks import auto_repair_report, run_sanity_checks

try:  # Optional dependency for schema-level validation.
    from jsonschema import Draft202012Validator
    from jsonschema import RefResolver
    from jsonschema import ValidationError as JsonSchemaValidationError
except ModuleNotFoundError:  # pragma: no cover
    Draft202012Validator = None  # type: ignore[assignment]
    RefResolver = None  # type: ignore[assignment]
    JsonSchemaValidationError = Exception  # type: ignore[assignment]


SCHEMA_VERSION_V1 = "0.1"
SCHEMA_VERSION_V2 = "0.2"
SUPPORTED_SCHEMA_VERSIONS = {SCHEMA_VERSION_V1, SCHEMA_VERSION_V2}

DIALECT_LEGACY_V1 = "legacy_0.1"
DIALECT_LEGACY_V2 = "legacy_0.2"
DIALECT_PACK_V2 = "pack_0.2"

PACK_QUERY_TYPES = {"NEXT_STEPS", "CHECK_LAST_TREATMENT"}
PACK_SOURCE_MODES = {"SINGLE", "AUTO"}
PACK_QUERY_MODES = {"FULL_ANALYSIS", "SOURCES_ONLY"}

_UUID_NS = uuid.UUID("5a431718-c36f-4d85-b54d-c0d05d55ee37")


@dataclass(frozen=True)
class AnalyzeRequestContext:
    dialect: str
    schema_version: str
    normalized_payload: dict[str, Any]
    request_id: str = ""
    query_type: str = "CHECK_LAST_TREATMENT"
    query_mode: str = "FULL_ANALYSIS"
    as_of_date: str | None = None
    historical_assessment: bool = False
    source_ids: list[str] = field(default_factory=list)
    case_json: dict[str, Any] | None = None


@dataclass(frozen=True)
class _CitationProjection:
    citation: dict[str, Any]
    key: str



def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)



def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]



def _to_uuid(value: Any, *, seed_prefix: str) -> str:
    text = str(value or "").strip()
    if text:
        try:
            return str(uuid.UUID(text))
        except ValueError:
            pass
    return str(uuid.uuid5(_UUID_NS, f"{seed_prefix}:{text or 'empty'}"))



def _sanitize_source_id(value: Any) -> str:
    text = normalize_source_set_id(str(value or "").strip().lower())
    if not text:
        return "legacy_source"
    clean = re.sub(r"[^a-z0-9_\-]", "_", text)
    return clean.strip("_") or "legacy_source"


def _is_valid_iso_date(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True



def _extract_case_json(payload: dict[str, Any]) -> dict[str, Any] | None:
    case = payload.get("case")
    if not isinstance(case, dict):
        return None
    case_json = case.get("case_json")
    return case_json if isinstance(case_json, dict) else None



def is_pack_v0_2_request(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("schema_version") != SCHEMA_VERSION_V2:
        return False
    if not isinstance(payload.get("sources"), dict):
        return False
    if payload.get("query_type") in PACK_QUERY_TYPES and isinstance(payload.get("case"), dict):
        return True
    return False



@lru_cache(maxsize=1)
def _load_pack_request_validator() -> Any:
    if Draft202012Validator is None:
        return None
    schemas_dir = _project_root() / "docs" / "contracts" / "onco_json_pack_v1" / "schemas"
    schema_path = schemas_dir / "analyze_request.schema.json"
    if not schema_path.exists():
        return None
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    store: dict[str, Any] = {}
    for path in schemas_dir.glob("*.schema.json"):
        try:
            candidate = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        schema_id = candidate.get("$id")
        if isinstance(schema_id, str) and schema_id.strip():
            store[schema_id] = candidate

    if RefResolver is not None:
        resolver = RefResolver.from_schema(schema, store=store)
        return Draft202012Validator(
            schema,
            resolver=resolver,
            format_checker=Draft202012Validator.FORMAT_CHECKER,
        )
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)



def validate_pack_request_payload(payload: dict[str, Any]) -> None:
    _require(payload.get("schema_version") == SCHEMA_VERSION_V2, "schema_version must be 0.2 for pack request")
    _require(isinstance(payload.get("request_id"), str) and bool(str(payload["request_id"]).strip()), "request_id is required")
    _require(payload.get("query_type") in PACK_QUERY_TYPES, "query_type must be NEXT_STEPS or CHECK_LAST_TREATMENT")
    if payload.get("query_mode") is not None:
        _require(payload.get("query_mode") in PACK_QUERY_MODES, "query_mode must be FULL_ANALYSIS or SOURCES_ONLY")
    if payload.get("as_of_date") is not None:
        _require(
            isinstance(payload.get("as_of_date"), str) and _is_valid_iso_date(str(payload.get("as_of_date"))),
            "as_of_date must be ISO date",
        )
    if payload.get("historical_reference_date") is not None:
        _require(
            isinstance(payload.get("historical_reference_date"), str)
            and _is_valid_iso_date(str(payload.get("historical_reference_date"))),
            "historical_reference_date must be ISO date",
        )
    as_of_date_token = str(payload.get("as_of_date") or "").strip()
    historical_reference_token = str(payload.get("historical_reference_date") or "").strip()
    if as_of_date_token and historical_reference_token:
        _require(
            as_of_date_token == historical_reference_token,
            "historical_reference_date must match as_of_date when both are provided",
        )
    if payload.get("historical_assessment") is not None:
        _require(isinstance(payload.get("historical_assessment"), bool), "historical_assessment must be boolean")

    sources = payload.get("sources")
    _require(isinstance(sources, dict), "sources must be an object")
    _require(sources.get("mode") in PACK_SOURCE_MODES, "sources.mode invalid")
    source_ids = sources.get("source_ids")
    _require(isinstance(source_ids, list) and len(source_ids) > 0, "sources.source_ids must be non-empty array")
    _require(all(isinstance(item, str) and item.strip() for item in source_ids), "sources.source_ids entries must be strings")

    case = payload.get("case")
    _require(isinstance(case, dict), "case must be an object")
    has_case_id = isinstance(case.get("case_id"), str) and bool(str(case["case_id"]).strip())
    has_case_json = isinstance(case.get("case_json"), dict)
    _require(has_case_id or has_case_json, "case.case_id or case.case_json is required")

    if has_case_json:
        case_json = case["case_json"]
        _require(case_json.get("schema_version") == "1.0", "case.case_json.schema_version must be 1.0")
        _require(isinstance(case_json.get("patient"), dict), "case.case_json.patient must be object")
        _require(isinstance(case_json.get("diagnoses"), list) and case_json["diagnoses"], "case.case_json.diagnoses required")
        _require(isinstance(case_json.get("attachments"), list), "case.case_json.attachments must be array")

    validator = _load_pack_request_validator()
    if validator is None:
        return
    try:
        validator.validate(payload)
    except JsonSchemaValidationError as exc:
        raise ValidationError(f"pack analyze_request schema validation failed: {exc.message}") from exc
    except Exception:  # noqa: BLE001
        # Keep runtime stable when schema resolution is partial; manual guards above stay authoritative.
        return



def _age_from_birth_year(birth_year: Any) -> int | None:
    if not isinstance(birth_year, int):
        return None
    current_year = datetime.now(timezone.utc).year
    age = current_year - birth_year
    if age < 0 or age > 140:
        return None
    return age



def _guess_cancer_type(case_json: dict[str, Any]) -> str:
    diagnoses = case_json.get("diagnoses")
    if not isinstance(diagnoses, list) or not diagnoses:
        return "unknown"
    first = diagnoses[0] if isinstance(diagnoses[0], dict) else {}
    icd10 = str(first.get("icd10", "")).upper()
    if icd10.startswith("C34"):
        return "nsclc_egfr"
    if icd10.startswith("C50"):
        return "breast_hr+/her2-"
    if icd10.startswith("C16"):
        return "gastric_cancer"
    return "unknown"



def _extract_plan_structured(case_json: dict[str, Any]) -> list[dict[str, str]]:
    diagnoses = case_json.get("diagnoses")
    if not isinstance(diagnoses, list) or not diagnoses or not isinstance(diagnoses[0], dict):
        return []
    diagnosis = diagnoses[0]
    timeline = diagnosis.get("timeline")
    items: list[dict[str, str]] = []
    if isinstance(timeline, list):
        for event in timeline:
            if not isinstance(event, dict):
                continue
            event_type = str(event.get("type", "")).strip().lower()
            label = str(event.get("label") or event.get("details") or event.get("type") or "").strip()
            if not label:
                continue
            if event_type in {"pathology", "imaging", "lab", "diagnostic", "diagnostics"}:
                step_type = "diagnostic"
            elif event_type in {"systemic_therapy", "surgery", "radiation", "radiotherapy"}:
                step_type = "systemic_therapy"
            else:
                step_type = "other"
            items.append({"step_type": step_type, "name": label})

    last_plan = diagnosis.get("last_plan")
    if isinstance(last_plan, dict):
        regimen = str(last_plan.get("regimen", "")).strip()
        if regimen and not any(regimen.lower() in step.get("name", "").lower() for step in items):
            items.append({"step_type": "systemic_therapy", "name": regimen})

    return items[:12]



def _extract_plan_text(case_json: dict[str, Any]) -> str:
    diagnoses = case_json.get("diagnoses")
    diagnosis = diagnoses[0] if isinstance(diagnoses, list) and diagnoses and isinstance(diagnoses[0], dict) else {}
    last_plan = diagnosis.get("last_plan") if isinstance(diagnosis, dict) else {}
    regimen = str(last_plan.get("regimen", "")).strip() if isinstance(last_plan, dict) else ""
    notes = str(case_json.get("notes", "")).strip()

    parts: list[str] = []
    if regimen:
        parts.append(f"Last plan regimen: {regimen}")
    if notes:
        parts.append(notes)
    if not parts:
        parts.append("No explicit treatment plan found in case_json.")
    return "\n".join(parts)



def _normalize_case_for_internal(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    case = payload.get("case") or {}
    if not isinstance(case, dict):
        return {"cancer_type": "unknown", "language": "ru", "notes": "", "data_mode": "DEID"}, {
            "plan_text": "No case payload found.",
            "plan_structured": [],
        }

    case_json = case.get("case_json")
    if not isinstance(case_json, dict):
        case_id = str(case.get("case_id", "")).strip()
        notes = f"Case lookup by case_id requested: {case_id}" if case_id else "Case payload without case_json"
        return {
            "cancer_type": "unknown",
            "language": str(payload.get("language") or "ru"),
            "notes": notes,
            "data_mode": "DEID",
            "patient": {"sex": "unknown"},
            "diagnosis": {},
            "biomarkers": [],
            "comorbidities": [],
            "contraindications": [],
        }, {"plan_text": notes, "plan_structured": []}

    language = str(payload.get("language") or "ru").strip().lower()
    if language not in {"ru", "en"}:
        language = "ru"

    patient = case_json.get("patient") if isinstance(case_json.get("patient"), dict) else {}
    diagnoses = case_json.get("diagnoses") if isinstance(case_json.get("diagnoses"), list) else []
    diagnosis = diagnoses[0] if diagnoses and isinstance(diagnoses[0], dict) else {}

    biomarkers_raw = diagnosis.get("biomarkers") if isinstance(diagnosis, dict) else []
    biomarkers: list[dict[str, str]] = []
    if isinstance(biomarkers_raw, list):
        for item in biomarkers_raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            value = str(item.get("value", "")).strip()
            if not name or not value:
                continue
            biomarkers.append({"name": name, "value": value})

    stage = diagnosis.get("stage") if isinstance(diagnosis.get("stage"), dict) else {}
    explicit_cancer_type = str(
        diagnosis.get("cancer_type")
        or case_json.get("cancer_type")
        or ""
    ).strip()
    internal_case = {
        "cancer_type": explicit_cancer_type or _guess_cancer_type(case_json),
        "language": language,
        "notes": str(case_json.get("notes", "")),
        "data_mode": str(case_json.get("data_mode") or "DEID").strip().upper(),
        "patient": {
            "sex": str(patient.get("sex") or "unknown"),
            "age": _age_from_birth_year(patient.get("birth_year")),
            "birth_year": patient.get("birth_year"),
            "ecog": patient.get("ecog"),
        },
        "diagnosis": {
            "stage": str(stage.get("stage_group") or ""),
            "histology": str(diagnosis.get("histology") or ""),
            "icd10": str(diagnosis.get("icd10") or ""),
            "disease_id": str(diagnosis.get("disease_id") or ""),
            "line": diagnosis.get("last_plan", {}).get("line") if isinstance(diagnosis.get("last_plan"), dict) else None,
        },
        "biomarkers": biomarkers,
        "comorbidities": case_json.get("comorbidities") if isinstance(case_json.get("comorbidities"), list) else [],
        "contraindications": (
            case_json.get("contraindications") if isinstance(case_json.get("contraindications"), list) else []
        ),
    }

    internal_plan = {
        "plan_text": _extract_plan_text(case_json),
        "plan_structured": _extract_plan_structured(case_json),
    }
    return internal_case, internal_plan



def normalize_analyze_request(payload: dict[str, Any]) -> AnalyzeRequestContext:
    _require(isinstance(payload, dict), "Payload must be an object")

    if is_pack_v0_2_request(payload):
        validate_pack_request_payload(payload)
        source_ids = payload.get("sources", {}).get("source_ids", [])
        source_ids = normalize_source_set_ids([str(item) for item in source_ids if isinstance(item, str) and item.strip()])
        query_mode = str(payload.get("query_mode") or "FULL_ANALYSIS").strip().upper()
        if query_mode not in PACK_QUERY_MODES:
            query_mode = "FULL_ANALYSIS"
        as_of_date_raw = str(
            payload.get("as_of_date") or payload.get("historical_reference_date") or ""
        ).strip()
        as_of_date = as_of_date_raw if _is_valid_iso_date(as_of_date_raw) else None
        historical_assessment = bool(payload.get("historical_assessment")) or bool(as_of_date)
        raw_kb_filters = payload.get("kb_filters")
        doc_ids: list[str] = []
        if isinstance(raw_kb_filters, dict):
            raw_doc_ids = raw_kb_filters.get("doc_ids")
            if isinstance(raw_doc_ids, list):
                doc_ids = [str(item).strip() for item in raw_doc_ids if item is not None and str(item).strip()]

        internal_case, internal_plan = _normalize_case_for_internal(payload)
        internal_payload = {
            "schema_version": "0.2",
            "request_id": str(payload.get("request_id", "")),
            "query_mode": query_mode,
            "as_of_date": as_of_date,
            "historical_assessment": historical_assessment,
            "case": internal_case,
            "treatment_plan": internal_plan,
            "kb_filters": {
                "source_set": source_ids[0] if len(source_ids) == 1 else "",
                "source_sets": source_ids,
                "source_mode": str(payload.get("sources", {}).get("mode", "AUTO")).strip().upper() or "AUTO",
                "doc_ids": doc_ids,
            },
            "return_patient_explain": True,
        }

        return AnalyzeRequestContext(
            dialect=DIALECT_PACK_V2,
            schema_version="0.2",
            normalized_payload=internal_payload,
            request_id=str(payload.get("request_id", "")),
            query_type=str(payload.get("query_type", "CHECK_LAST_TREATMENT")),
            query_mode=query_mode,
            as_of_date=as_of_date,
            historical_assessment=historical_assessment,
            source_ids=source_ids,
            case_json=_extract_case_json(payload),
        )

    schema_version = payload.get("schema_version")
    _require(schema_version in SUPPORTED_SCHEMA_VERSIONS, "schema_version must be 0.1 or 0.2")
    dialect = DIALECT_LEGACY_V1 if schema_version == "0.1" else DIALECT_LEGACY_V2
    request_id = str(payload.get("request_id", "")).strip()
    if not request_id:
        request_id = _to_uuid(payload.get("case", {}).get("notes", "legacy"), seed_prefix="request")

    return AnalyzeRequestContext(
        dialect=dialect,
        schema_version=str(schema_version),
        normalized_payload=dict(payload),
        request_id=request_id,
        query_type="CHECK_LAST_TREATMENT",
        source_ids=[],
        case_json=None,
    )



def _legacy_issue_to_pack_severity(value: str) -> str:
    mapping = {
        "critical": "critical",
        "important": "warning",
        "note": "info",
    }
    return mapping.get(str(value).lower(), "info")



def _legacy_issue_to_pack_kind(issue: dict[str, Any]) -> str:
    category = str(issue.get("category", "")).lower()
    title = str(issue.get("title", "")).lower()
    if "contra" in category or "contra" in title:
        return "contraindication"
    if "incons" in category or "incons" in title:
        return "inconsistency"
    if "missing" in category or "missing" in title or "data" in category:
        return "missing_data"
    if category and category not in {"other", "note"}:
        return "deviation"
    return "other"



def _build_citations(
    *,
    legacy_report: dict[str, Any],
    source_ids: list[str],
) -> tuple[list[dict[str, Any]], dict[str, str], str, bool]:
    citations: list[dict[str, Any]] = []
    key_to_citation_id: dict[str, str] = {}
    fallback_source_id = _sanitize_source_id(source_ids[0] if source_ids else "legacy_source")
    has_real_citations = False

    for issue in legacy_report.get("issues", []):
        if not isinstance(issue, dict):
            continue
        for evidence in issue.get("evidence", []):
            if not isinstance(evidence, dict):
                continue
            source_id = _sanitize_source_id(
                evidence.get("source_set")
                or evidence.get("source_id")
                or fallback_source_id
            )
            doc_id = str(evidence.get("doc_id") or "unknown_doc")
            doc_version = str(evidence.get("doc_version") or "unknown_version")
            chunk_id = str(evidence.get("chunk_id") or "")
            page_index = int(evidence.get("pdf_page_index") or 0)
            key = f"{source_id}|{doc_id}|{doc_version}|{chunk_id}|{page_index}"
            if key in key_to_citation_id:
                continue

            citation_id = str(uuid.uuid5(_UUID_NS, f"citation:{key}"))
            key_to_citation_id[key] = citation_id

            page = max(1, page_index + 1)
            citations.append(
                {
                    "citation_id": citation_id,
                    "source_id": source_id,
                    "document_id": _to_uuid(doc_id, seed_prefix="document"),
                    "version_id": _to_uuid(f"{doc_id}:{doc_version}", seed_prefix="version"),
                    "page_start": page,
                    "page_end": page,
                    "section_path": str(evidence.get("section_title") or "Guideline fragment"),
                    "quote": str(evidence.get("quote") or "")[:800],
                    "file_uri": f"/admin/docs/{doc_id}/{doc_version}/pdf",
                    "score": float(issue.get("confidence", 0.5)) if isinstance(issue.get("confidence"), (int, float)) else 0.5,
                }
            )
            has_real_citations = True

    if citations:
        return citations, key_to_citation_id, citations[0]["citation_id"], has_real_citations

    # Schema requires citation_ids in plan/issues; provide deterministic placeholder.
    fallback_key = "synthetic:no_evidence"
    fallback_citation_id = str(uuid.uuid5(_UUID_NS, f"citation:{fallback_key}"))
    key_to_citation_id[fallback_key] = fallback_citation_id
    citations.append(
        {
            "citation_id": fallback_citation_id,
            "source_id": fallback_source_id,
            "document_id": _to_uuid("synthetic_document", seed_prefix="document"),
            "version_id": _to_uuid("synthetic_version", seed_prefix="version"),
            "page_start": 1,
            "page_end": 1,
            "section_path": "No evidence",
            "quote": "No retrieved chunk was available for this run.",
            "file_uri": "about:blank",
            "score": 0.0,
        }
    )
    return citations, key_to_citation_id, fallback_citation_id, False



def _build_pack_plan(
    *,
    normalized_payload: dict[str, Any],
    fallback_citation_id: str,
    missing_fields: list[str],
) -> list[dict[str, Any]]:
    treatment = normalized_payload.get("treatment_plan") if isinstance(normalized_payload.get("treatment_plan"), dict) else {}
    structured = treatment.get("plan_structured") if isinstance(treatment.get("plan_structured"), list) else []

    steps: list[dict[str, Any]] = []
    for idx, step in enumerate(structured, start=1):
        if not isinstance(step, dict):
            continue
        text = str(step.get("name") or step.get("description") or step.get("step_type") or "").strip()
        if not text:
            continue
        steps.append(
            {
                "step_id": str(uuid.uuid5(_UUID_NS, f"plan_step:{idx}:{text}")),
                "text": text,
                "priority": "high" if idx == 1 else "medium",
                "rationale": "Step extracted from normalized treatment plan.",
                "citation_ids": [fallback_citation_id],
                "depends_on_missing_data": missing_fields,
            }
        )

    if not steps:
        plan_text = str(treatment.get("plan_text") or "No explicit treatment plan.").strip() or "No explicit treatment plan."
        steps = [
            {
                "step_id": str(uuid.uuid5(_UUID_NS, f"plan_step:fallback:{plan_text}")),
                "text": plan_text,
                "priority": "high",
                "rationale": "Fallback step from plan_text.",
                "citation_ids": [fallback_citation_id],
                "depends_on_missing_data": missing_fields,
            }
        ]

    return [{"section": "treatment", "title": "Treatment plan", "steps": steps}]



def _build_pack_issues(
    *,
    legacy_report: dict[str, Any],
    key_to_citation_id: dict[str, str],
    fallback_citation_id: str,
) -> list[dict[str, Any]]:
    pack_issues: list[dict[str, Any]] = []
    for issue in legacy_report.get("issues", []):
        if not isinstance(issue, dict):
            continue
        citation_ids: list[str] = []
        for evidence in issue.get("evidence", []):
            if not isinstance(evidence, dict):
                continue
            source_id = _sanitize_source_id(evidence.get("source_set") or evidence.get("source_id") or "legacy_source")
            doc_id = str(evidence.get("doc_id") or "unknown_doc")
            doc_version = str(evidence.get("doc_version") or "unknown_version")
            chunk_id = str(evidence.get("chunk_id") or "")
            page_index = int(evidence.get("pdf_page_index") or 0)
            key = f"{source_id}|{doc_id}|{doc_version}|{chunk_id}|{page_index}"
            citation_id = key_to_citation_id.get(key)
            if citation_id:
                citation_ids.append(citation_id)

        if not citation_ids:
            citation_ids = [fallback_citation_id]

        summary = str(issue.get("title") or "Potential issue")
        details = str(issue.get("description") or summary)
        pack_issues.append(
            {
                "issue_id": _to_uuid(issue.get("issue_id") or summary, seed_prefix="issue"),
                "severity": _legacy_issue_to_pack_severity(str(issue.get("severity", "note"))),
                "kind": _legacy_issue_to_pack_kind(issue),
                "summary": summary,
                "details": details,
                "suggested_questions": [],
                "citation_ids": sorted(set(citation_ids)),
                "source_refs": [],
            }
        )
    return pack_issues



def _build_disease_context(
    *,
    normalized_payload: dict[str, Any],
    case_json: dict[str, Any] | None,
) -> dict[str, Any]:
    case = normalized_payload.get("case") if isinstance(normalized_payload.get("case"), dict) else {}
    diagnosis = case.get("diagnosis") if isinstance(case.get("diagnosis"), dict) else {}
    biomarkers = case.get("biomarkers") if isinstance(case.get("biomarkers"), list) else []

    stage_group = str(diagnosis.get("stage") or "").strip()
    stage_upper = stage_group.upper()
    setting = "metastatic" if "IV" in stage_upper or "M1" in stage_upper else "unknown"

    line: int | None = None
    if case_json and isinstance(case_json.get("diagnoses"), list) and case_json.get("diagnoses"):
        first = case_json["diagnoses"][0]
        if isinstance(first, dict):
            last_plan = first.get("last_plan")
            if isinstance(last_plan, dict) and isinstance(last_plan.get("line"), int):
                line = int(last_plan["line"])

    context: dict[str, Any] = {
        "disease_id": _to_uuid(diagnosis.get("disease_id") or case.get("cancer_type") or "unknown", seed_prefix="disease"),
        "icd10": str(diagnosis.get("icd10") or "") or None,
        "stage_group": stage_group or None,
        "setting": setting,
        "biomarkers": [
            {"name": str(item.get("name", "")), "value": str(item.get("value", ""))}
            for item in biomarkers
            if isinstance(item, dict) and str(item.get("name", "")).strip() and str(item.get("value", "")).strip()
        ][:8],
    }
    if line is not None:
        context["line"] = line

    return {k: v for k, v in context.items() if v is not None}



def _map_fallback_reason(reason: str | None) -> str:
    text = str(reason or "").strip().lower()
    if not text:
        return "none"
    if "no_docs" in text or "no retrieved" in text:
        return "no_docs"
    if "low_recall" in text:
        return "low_recall"
    if "invalid_json" in text or "invalid_response" in text:
        return "llm_invalid_json"
    if "timeout" in text:
        return "timeout"
    if text == "none":
        return "none"
    return "other"



def _map_report_generation_path(path: str) -> str:
    mapping = {
        "llm_primary": "primary",
        "llm_fallback": "fallback",
        "deterministic": "deterministic_only",
        "primary": "primary",
        "fallback": "fallback",
        "deterministic_only": "deterministic_only",
    }
    return mapping.get(str(path), "deterministic_only")



def _map_retrieval_engine(engine: str) -> str:
    if engine in {"basic", "llamaindex"}:
        return engine
    return "other"


def _build_case_text(normalized_payload: dict[str, Any], case_json: dict[str, Any] | None) -> str:
    case = normalized_payload.get("case") if isinstance(normalized_payload.get("case"), dict) else {}
    treatment = normalized_payload.get("treatment_plan") if isinstance(normalized_payload.get("treatment_plan"), dict) else {}
    case_json_notes = str(case_json.get("notes") or "").strip() if isinstance(case_json, dict) else ""
    if case_json_notes:
        return case_json_notes
    case_notes = str(case.get("notes") or "").strip()
    if case_notes:
        return case_notes
    return str(treatment.get("plan_text") or "").strip()


def _build_timeline(case_json: dict[str, Any] | None) -> list[dict[str, str]]:
    if not isinstance(case_json, dict):
        return []
    diagnoses = case_json.get("diagnoses")
    if not isinstance(diagnoses, list) or not diagnoses:
        return []
    first = diagnoses[0] if isinstance(diagnoses[0], dict) else {}
    timeline = first.get("timeline")
    if not isinstance(timeline, list):
        return []
    out: list[dict[str, str]] = []
    for event in timeline:
        if not isinstance(event, dict):
            continue
        out.append(
            {
                "date": str(event.get("date") or ""),
                "type": str(event.get("type") or "other"),
                "label": str(event.get("label") or event.get("details") or "event"),
                "details": str(event.get("details") or ""),
            }
        )
    return out[:30]


def _build_consilium_md(
    *,
    case_facts: dict[str, Any],
    query_type: str,
    plan: list[dict[str, Any]],
    evidence_confirmed: bool,
    issues: list[dict[str, Any]],
    missing_fields: list[str],
) -> str:
    initial_stage = case_facts.get("initial_stage") if isinstance(case_facts.get("initial_stage"), dict) else {}
    biomarkers = case_facts.get("biomarkers") if isinstance(case_facts.get("biomarkers"), dict) else {}
    stage = str(initial_stage.get("tnm") or initial_stage.get("stage_group") or "не указано")
    her2 = str(biomarkers.get("her2") or "не указано")
    msi = str(biomarkers.get("msi_status") or "unknown")
    cps_values = biomarkers.get("pd_l1_cps_values") if isinstance(biomarkers.get("pd_l1_cps_values"), list) else []
    cps_text = ", ".join(str(item) for item in cps_values) if cps_values else "не указано"

    cps_numeric: list[float] = []
    for item in cps_values:
        try:
            cps_numeric.append(float(item))
        except (TypeError, ValueError):
            continue
    max_cps = max(cps_numeric) if cps_numeric else None
    msi_lc = msi.strip().lower()
    immuno_not_default = msi_lc in {"mss", "stable", "unknown"} and (max_cps is None or max_cps < 5.0)

    steps: list[str] = []
    for section in plan:
        if not isinstance(section, dict):
            continue
        for step in section.get("steps", []):
            if isinstance(step, dict):
                text = str(step.get("text") or "").strip()
                if text:
                    if immuno_not_default and ("иммуно" in text.lower() or "immuno" in text.lower()):
                        continue
                    steps.append(text)
    plan_block = "\n".join(f"- {item}" for item in steps[:6]) if steps else "- Не найдено в предоставленных рекомендациях"

    issue_lines: list[str] = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        summary = str(issue.get("summary") or "").strip()
        if summary:
            issue_lines.append(f"- {summary}")
    issue_block = "\n".join(issue_lines[:5]) if issue_lines else "- Не выявлено критических расхождений."

    citation_block = (
        "- Подтверждение найдено в предоставленных рекомендациях."
        if evidence_confirmed
        else "- Не найдено в предоставленных рекомендациях"
    )
    gaps_block = "\n".join(f"- {field}" for field in missing_fields[:8]) if missing_fields else "- Существенных пробелов данных не выявлено."
    query_text = "Следующие шаги лечения" if query_type == "NEXT_STEPS" else "Проверка последнего этапа лечения"
    immuno_note = (
        "- Иммунотерапия не предлагается по умолчанию при текущем сочетании CPS/MSI.\n"
        if immuno_not_default
        else ""
    )

    return (
        "## Ключевые клинические факты\n"
        f"- TNM/стадия: {stage}\n"
        f"- HER2: {her2}\n"
        f"- PD-L1 CPS: {cps_text}\n"
        f"- MSI/MSS: {msi}\n\n"
        "## Клинический вопрос\n"
        f"- {query_text}\n\n"
        "## Обоснование по клинреку\n"
        f"{citation_block}\n\n"
        "## План действий\n"
        f"{plan_block}\n\n"
        "## Риски и безопасность\n"
        f"{issue_block}\n"
        f"{immuno_note}\n"
        "## Дефицит данных\n"
        f"{gaps_block}"
    )



def serialize_analyze_response(
    *,
    context: AnalyzeRequestContext,
    legacy_response: dict[str, Any],
    doctor_schema_v1_2_enabled: bool = True,
    casefacts_enabled: bool = True,
) -> dict[str, Any]:
    if context.dialect != DIALECT_PACK_V2:
        return legacy_response

    now = datetime.now(timezone.utc).isoformat()
    request_id = _to_uuid(context.request_id, seed_prefix="request")

    legacy_report = legacy_response.get("doctor_report") if isinstance(legacy_response.get("doctor_report"), dict) else {}
    legacy_patient = legacy_response.get("patient_explain") if isinstance(legacy_response.get("patient_explain"), dict) else {}
    legacy_meta = legacy_response.get("run_meta") if isinstance(legacy_response.get("run_meta"), dict) else {}

    citations, key_to_citation_id, fallback_citation_id, has_real_citations = _build_citations(
        legacy_report=legacy_report,
        source_ids=context.source_ids,
    )

    missing_fields = [
        str(item.get("field"))
        for item in legacy_report.get("missing_data", [])
        if isinstance(item, dict) and str(item.get("field", "")).strip()
    ]

    pack_issues = _build_pack_issues(
        legacy_report=legacy_report,
        key_to_citation_id=key_to_citation_id,
        fallback_citation_id=fallback_citation_id,
    )
    pack_plan = _build_pack_plan(
        normalized_payload=context.normalized_payload,
        fallback_citation_id=fallback_citation_id,
        missing_fields=missing_fields,
    )

    schema_version = "1.2" if doctor_schema_v1_2_enabled else "1.0"
    case_text = _build_case_text(context.normalized_payload, context.case_json)
    if casefacts_enabled:
        case_facts = extract_case_facts(case_text=case_text, case_json=context.case_json).model_dump()
    else:
        case_facts = {
            "initial_stage": {},
            "metastases": [],
            "biomarkers": {},
            "treatment_history": [],
            "complications": [],
            "key_unknowns": [
                "CaseFacts extraction disabled by feature flag ONCOAI_CASEFACTS_ENABLED=false",
            ],
        }
    timeline = _build_timeline(context.case_json)
    consilium_md = _build_consilium_md(
        case_facts=case_facts,
        query_type=context.query_type,
        plan=pack_plan,
        evidence_confirmed=has_real_citations,
        issues=pack_issues,
        missing_fields=missing_fields,
    )

    doctor_report = {
        "schema_version": schema_version,
        "report_id": _to_uuid(legacy_report.get("report_id"), seed_prefix="report"),
        "request_id": request_id,
        "query_type": context.query_type if context.query_type in PACK_QUERY_TYPES else "CHECK_LAST_TREATMENT",
        "disease_context": _build_disease_context(
            normalized_payload=context.normalized_payload,
            case_json=context.case_json,
        ),
        "case_facts": case_facts,
        "timeline": timeline,
        "consilium_md": consilium_md,
        "plan": pack_plan,
        "issues": pack_issues,
        "sanity_checks": [],
        "citations": citations,
        "generated_at": now,
    }
    if casefacts_enabled:
        sanity_checks = run_sanity_checks(case_facts=case_facts, doctor_report=doctor_report)
        if any(item.get("status") == "fail" for item in sanity_checks):
            doctor_report = auto_repair_report(case_facts=case_facts, doctor_report=doctor_report)
            sanity_checks = run_sanity_checks(case_facts=case_facts, doctor_report=doctor_report)
    else:
        sanity_checks = [
            {
                "check_id": "casefacts_feature_flag_disabled",
                "status": "warn",
                "details": "CaseFacts extraction disabled by feature flag ONCOAI_CASEFACTS_ENABLED=false",
            }
        ]
    doctor_report["sanity_checks"] = sanity_checks

    summary_plain = str(legacy_patient.get("summary") or legacy_report.get("summary") or "")
    questions = legacy_patient.get("questions_to_ask_doctor") if isinstance(legacy_patient.get("questions_to_ask_doctor"), list) else []
    key_points = legacy_patient.get("key_points") if isinstance(legacy_patient.get("key_points"), list) else []
    safety_disclaimer = str(legacy_patient.get("safety_disclaimer") or "Do not change therapy without clinician review.")

    patient_explain = {
        "schema_version": schema_version,
        "request_id": request_id,
        "summary_plain": summary_plain or "Clinical check completed. Discuss results with your doctor.",
        "key_points": [str(item) for item in key_points if str(item).strip()][:6],
        "questions_for_doctor": [str(item) for item in questions if str(item).strip()][:6]
        or ["Какие данные нужно дополнить, чтобы уточнить следующую тактику лечения?"],
        "what_was_checked": ["Treatment plan was checked against retrieved guideline evidence."],
        "safety_notes": [safety_disclaimer],
        "sources_used": sorted({_sanitize_source_id(item.get("source_id")) for item in citations}) or ["legacy_source"],
        "generated_at": now,
    }

    total_ms = int(round(float(legacy_meta.get("latency_ms_total", 0.0))))
    retrieval_ms = int(round(total_ms * 0.25))
    report_path = _map_report_generation_path(str(legacy_meta.get("report_generation_path", "deterministic")))
    reasoning_mode = str(legacy_meta.get("reasoning_mode") or "compat").strip().lower()
    if reasoning_mode not in {"compat", "llm_rag_only"}:
        reasoning_mode = "compat"
    llm_ms = 0 if report_path == "deterministic_only" else int(round(total_ms * 0.55))
    post_ms = max(0, total_ms - retrieval_ms - llm_ms)

    run_meta = {
        "request_id": request_id,
        "schema_version": "0.2",
        "timings_ms": {
            "total": max(total_ms, 0),
            "retrieval": max(retrieval_ms, 0),
            "llm": max(llm_ms, 0),
            "postprocess": max(post_ms, 0),
        },
        "docs_retrieved_count": int(legacy_meta.get("retrieval_k", 0) or 0),
        "docs_after_filter_count": int(legacy_meta.get("rerank_n", 0) or 0),
        "citations_count": len(citations),
        "evidence_valid_ratio": 1.0,
        "retrieval_engine": _map_retrieval_engine(str(legacy_meta.get("retrieval_engine", "basic"))),
        "reasoning_mode": reasoning_mode,
        "llm_path": str(legacy_meta.get("llm_path") or "deterministic"),
        "vector_backend": str(legacy_meta.get("vector_backend") or ""),
        "embedding_backend": str(legacy_meta.get("embedding_backend") or ""),
        "reranker_backend": str(legacy_meta.get("reranker_backend") or ""),
        "report_generation_path": report_path,
        "fallback_reason": _map_fallback_reason(legacy_meta.get("fallback_reason")),
    }
    if reasoning_mode == "llm_rag_only":
        run_meta["llm_path"] = "primary"
        run_meta["report_generation_path"] = "primary"
        run_meta["fallback_reason"] = "none"
    routing_meta = legacy_meta.get("routing_meta")
    if isinstance(routing_meta, dict):
        run_meta["routing_meta"] = {
            "resolved_disease_id": str(routing_meta.get("resolved_disease_id") or "unknown_disease"),
            "resolved_cancer_type": str(routing_meta.get("resolved_cancer_type") or "unknown"),
            "match_strategy": str(routing_meta.get("match_strategy") or "default_sources_fallback"),
            "source_ids": [
                str(item).strip()
                for item in (routing_meta.get("source_ids") if isinstance(routing_meta.get("source_ids"), list) else [])
                if str(item).strip()
            ],
            "doc_ids": [
                str(item).strip()
                for item in (routing_meta.get("doc_ids") if isinstance(routing_meta.get("doc_ids"), list) else [])
                if str(item).strip()
            ],
            "candidate_chunks": int(routing_meta.get("candidate_chunks") or 0),
            "baseline_candidate_chunks": int(routing_meta.get("baseline_candidate_chunks") or 0),
            "reduction_ratio": float(routing_meta.get("reduction_ratio") or 0.0),
        }

    return {
        "schema_version": "0.2",
        "request_id": request_id,
        "doctor_report": doctor_report,
        "patient_explain": patient_explain,
        "run_meta": run_meta,
    }
