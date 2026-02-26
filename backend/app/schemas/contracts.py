from __future__ import annotations

from typing import Any

from backend.app.exceptions import ValidationError
from backend.app.reporting.compat_doctor_v1_1 import validate_doctor_projection_v1_1
from backend.app.reporting.compat_patient_projection import validate_patient_projection_alt
from backend.app.schemas.analyze_bridge import (
    SCHEMA_VERSION_V1,
    SCHEMA_VERSION_V2,
    SUPPORTED_SCHEMA_VERSIONS,
    is_pack_v0_2_request,
    validate_pack_request_payload,
)

_PACK_DOCTOR_SCHEMA_VERSIONS = {"1.0", "1.2"}
_PACK_PATIENT_SCHEMA_VERSIONS = {"1.0", "1.2"}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)



def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())



def validate_analyze_request(payload: dict[str, Any]) -> None:
    _require(isinstance(payload, dict), "Payload must be an object")

    if is_pack_v0_2_request(payload):
        validate_pack_request_payload(payload)
        return

    schema_version = payload.get("schema_version")
    _require(schema_version in SUPPORTED_SCHEMA_VERSIONS, "schema_version must be 0.1 or 0.2")

    case = payload.get("case")
    _require(isinstance(case, dict), "case must be an object")
    _require(bool(case.get("cancer_type")), "case.cancer_type is required")
    _require(case.get("language") in {"ru", "en"}, "case.language must be ru or en")
    if case.get("data_mode") is not None:
        _require(case.get("data_mode") in {"DEID", "FULL"}, "case.data_mode must be DEID or FULL")
    if schema_version == SCHEMA_VERSION_V2:
        if "patient" in case:
            _require(isinstance(case.get("patient"), dict), "case.patient must be an object")
        if "diagnosis" in case:
            _require(isinstance(case.get("diagnosis"), dict), "case.diagnosis must be an object")
        if "biomarkers" in case:
            _require(isinstance(case.get("biomarkers"), list), "case.biomarkers must be an array")
        if "comorbidities" in case:
            _require(isinstance(case.get("comorbidities"), list), "case.comorbidities must be an array")
        if "contraindications" in case:
            _require(isinstance(case.get("contraindications"), list), "case.contraindications must be an array")

    treatment_plan = payload.get("treatment_plan")
    _require(isinstance(treatment_plan, dict), "treatment_plan must be an object")
    if schema_version == SCHEMA_VERSION_V1:
        _require(bool(treatment_plan.get("plan_text")), "treatment_plan.plan_text is required")
        return

    has_plan_text = bool(treatment_plan.get("plan_text"))
    plan_structured = treatment_plan.get("plan_structured")
    has_plan_structured = isinstance(plan_structured, list) and len(plan_structured) > 0
    _require(
        has_plan_text or has_plan_structured,
        "For schema_version=0.2 provide treatment_plan.plan_text or treatment_plan.plan_structured",
    )
    if plan_structured is not None:
        _require(isinstance(plan_structured, list), "treatment_plan.plan_structured must be an array")



def validate_doctor_report(report: dict[str, Any]) -> None:
    _require(
        report.get("schema_version") in SUPPORTED_SCHEMA_VERSIONS,
        "doctor_report.schema_version must be 0.1 or 0.2",
    )
    _require(bool(report.get("kb_version")), "doctor_report.kb_version is required")
    _require(isinstance(report.get("summary"), str) and report["summary"].strip(), "doctor_report.summary is required")
    _require(isinstance(report.get("issues"), list), "doctor_report.issues must be array")
    _require(isinstance(report.get("missing_data"), list), "doctor_report.missing_data must be array")

    for issue in report["issues"]:
        _require(issue.get("severity") in {"critical", "important", "note"}, "issue.severity invalid")
        _require(isinstance(issue.get("evidence"), list) and len(issue["evidence"]) >= 1, "issue.evidence required")



def validate_patient_explain(payload: dict[str, Any]) -> None:
    _require(
        payload.get("schema_version") in SUPPORTED_SCHEMA_VERSIONS,
        "patient_explain.schema_version must be 0.1 or 0.2",
    )
    _require(bool(payload.get("kb_version")), "patient_explain.kb_version is required")
    _require(bool(payload.get("summary")), "patient_explain.summary is required")
    _require(isinstance(payload.get("key_points"), list) and payload["key_points"], "patient_explain.key_points required")
    _require(
        isinstance(payload.get("questions_to_ask_doctor"), list) and payload["questions_to_ask_doctor"],
        "patient_explain.questions_to_ask_doctor required",
    )
    _require(bool(payload.get("safety_disclaimer")), "patient_explain.safety_disclaimer required")



def validate_run_meta(payload: dict[str, Any]) -> None:
    _require(isinstance(payload.get("retrieval_k"), int) and payload["retrieval_k"] >= 0, "run_meta.retrieval_k invalid")
    _require(isinstance(payload.get("rerank_n"), int) and payload["rerank_n"] >= 0, "run_meta.rerank_n invalid")
    _require(isinstance(payload.get("llm_path"), str) and payload["llm_path"], "run_meta.llm_path invalid")
    _require(
        str(payload.get("reasoning_mode") or "").strip() in {"compat", "llm_rag_only"},
        "run_meta.reasoning_mode invalid",
    )
    _require(
        isinstance(payload.get("latency_ms_total"), (int, float)) and payload["latency_ms_total"] >= 0,
        "run_meta.latency_ms_total invalid",
    )
    _require(isinstance(payload.get("kb_version"), str) and payload["kb_version"], "run_meta.kb_version invalid")
    _require(payload.get("vector_backend") in {"local", "qdrant"}, "run_meta.vector_backend invalid")
    _require(payload.get("embedding_backend") in {"hash", "openai"}, "run_meta.embedding_backend invalid")
    _require(payload.get("reranker_backend") in {"lexical", "llm"}, "run_meta.reranker_backend invalid")
    _require(
        payload.get("report_generation_path") in {"llm_primary", "llm_fallback", "deterministic"},
        "run_meta.report_generation_path invalid",
    )
    _require(payload.get("retrieval_engine") in {"basic", "llamaindex"}, "run_meta.retrieval_engine invalid")
    if payload.get("fallback_reason") is not None:
        _require(
            isinstance(payload.get("fallback_reason"), str) and bool(str(payload["fallback_reason"]).strip()),
            "run_meta.fallback_reason invalid",
        )
    if str(payload.get("reasoning_mode") or "").strip() == "llm_rag_only":
        _require(payload.get("llm_path") == "primary", "run_meta.llm_path must be primary in llm_rag_only")
        _require(
            payload.get("report_generation_path") == "llm_primary",
            "run_meta.report_generation_path must be llm_primary in llm_rag_only",
        )
        _require(
            str(payload.get("fallback_reason") or "none").strip() == "none",
            "run_meta.fallback_reason must be none in llm_rag_only",
        )



def _is_pack_analyze_response(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("schema_version") != SCHEMA_VERSION_V2:
        return False
    doctor_report = payload.get("doctor_report")
    if not isinstance(doctor_report, dict):
        return False
    return str(doctor_report.get("schema_version")) in _PACK_DOCTOR_SCHEMA_VERSIONS



def _validate_pack_doctor_report(
    payload: dict[str, Any],
    request_id: str,
    *,
    allow_pack_legacy_v1_0: bool,
    sources_only_mode: bool = False,
) -> None:
    schema_version = str(payload.get("schema_version"))
    if allow_pack_legacy_v1_0:
        _require(schema_version in _PACK_DOCTOR_SCHEMA_VERSIONS, "doctor_report.schema_version must be 1.0 or 1.2")
    else:
        _require(schema_version == "1.2", "doctor_report.schema_version must be 1.2")
    _require(_is_non_empty_string(payload.get("report_id")), "doctor_report.report_id is required")
    _require(payload.get("request_id") == request_id, "doctor_report.request_id must match top-level request_id")
    _require(payload.get("query_type") in {"NEXT_STEPS", "CHECK_LAST_TREATMENT"}, "doctor_report.query_type invalid")

    disease_context = payload.get("disease_context")
    _require(isinstance(disease_context, dict), "doctor_report.disease_context required")
    _require(_is_non_empty_string(disease_context.get("disease_id")), "doctor_report.disease_context.disease_id required")
    if schema_version == "1.2":
        _require(isinstance(payload.get("case_facts"), dict), "doctor_report.case_facts required for v1.2")
        _require(isinstance(payload.get("timeline"), list), "doctor_report.timeline required for v1.2")
        _require(_is_non_empty_string(payload.get("consilium_md")), "doctor_report.consilium_md required for v1.2")
        _require(isinstance(payload.get("sanity_checks"), list), "doctor_report.sanity_checks required for v1.2")
        _require(isinstance(payload.get("drug_safety"), dict), "doctor_report.drug_safety required for v1.2")
        _validate_pack_doctor_drug_safety(payload.get("drug_safety"))

    plan = payload.get("plan")
    _require(isinstance(plan, list), "doctor_report.plan must be array")
    if sources_only_mode:
        _require(len(plan) == 0, "doctor_report.plan must be empty for SOURCES_ONLY mode")
    for section in plan:
        _require(isinstance(section, dict), "doctor_report.plan item must be object")
        _require(
            section.get("section") in {"diagnostics", "staging", "treatment", "follow_up", "supportive", "other"},
            "doctor_report.plan.section invalid",
        )
        steps = section.get("steps")
        _require(isinstance(steps, list), "doctor_report.plan.steps must be array")
        for step in steps:
            _require(isinstance(step, dict), "doctor_report.plan.steps item must be object")
            _require(_is_non_empty_string(step.get("step_id")), "doctor_report.plan.steps.step_id required")
            _require(_is_non_empty_string(step.get("text")), "doctor_report.plan.steps.text required")
            _require(step.get("priority") in {"high", "medium", "low"}, "doctor_report.plan.steps.priority invalid")
            _require(
                isinstance(step.get("citation_ids"), list) and len(step["citation_ids"]) > 0,
                "doctor_report.plan.steps.citation_ids required",
            )
            if step.get("evidence_level") is not None:
                _require(_is_non_empty_string(step.get("evidence_level")), "doctor_report.plan.steps.evidence_level invalid")
            if step.get("recommendation_strength") is not None:
                _require(
                    _is_non_empty_string(step.get("recommendation_strength")),
                    "doctor_report.plan.steps.recommendation_strength invalid",
                )
            if step.get("confidence") is not None:
                confidence = step.get("confidence")
                _require(
                    isinstance(confidence, (int, float)) and 0.0 <= float(confidence) <= 1.0,
                    "doctor_report.plan.steps.confidence invalid",
                )

    issues = payload.get("issues")
    _require(isinstance(issues, list), "doctor_report.issues must be array")
    for issue in issues:
        _require(isinstance(issue, dict), "doctor_report.issues item must be object")
        _require(_is_non_empty_string(issue.get("issue_id")), "doctor_report.issue_id required")
        _require(issue.get("severity") in {"critical", "warning", "info"}, "doctor_report.issue.severity invalid")
        _require(
            issue.get("kind") in {"missing_data", "deviation", "contraindication", "inconsistency", "other"},
            "doctor_report.issue.kind invalid",
        )
        _require(_is_non_empty_string(issue.get("summary")), "doctor_report.issue.summary required")
        _require(isinstance(issue.get("citation_ids"), list), "doctor_report.issue.citation_ids must be array")
        if issue.get("kind") != "missing_data":
            _require(
                len(issue["citation_ids"]) > 0,
                "doctor_report.issue.citation_ids required for non-missing_data issues",
            )

    verification_summary = payload.get("verification_summary")
    if verification_summary is not None:
        _require(isinstance(verification_summary, dict), "doctor_report.verification_summary must be object")
        _require(
            str(verification_summary.get("category") or "").strip()
            in {"OK", "NOT_COMPLIANT", "NEEDS_DATA", "RISK"},
            "doctor_report.verification_summary.category invalid",
        )
        if verification_summary.get("status_line") is not None:
            _require(
                _is_non_empty_string(verification_summary.get("status_line")),
                "doctor_report.verification_summary.status_line invalid",
            )
        counts = verification_summary.get("counts")
        _require(isinstance(counts, dict), "doctor_report.verification_summary.counts required")
        for key in ("ok", "not_compliant", "needs_data", "risk"):
            value = counts.get(key)
            _require(
                isinstance(value, int) and value >= 0,
                f"doctor_report.verification_summary.counts.{key} invalid",
            )

    comparative_claims = payload.get("comparative_claims")
    if comparative_claims is not None:
        _require(isinstance(comparative_claims, list), "doctor_report.comparative_claims must be array")
        for claim in comparative_claims:
            _require(isinstance(claim, dict), "doctor_report.comparative_claims item must be object")
            _require(_is_non_empty_string(claim.get("claim_id")), "doctor_report.comparative_claims.claim_id required")
            _require(_is_non_empty_string(claim.get("text")), "doctor_report.comparative_claims.text required")
            _require(
                isinstance(claim.get("citation_ids"), list) and len(claim["citation_ids"]) > 0,
                "doctor_report.comparative_claims.citation_ids required",
            )
            comparative_superiority = bool(claim.get("comparative_superiority"))
            if comparative_superiority:
                pubmed_id = str(claim.get("pubmed_id") or "").strip()
                pubmed_url = str(claim.get("pubmed_url") or "").strip()
                _require(
                    bool(pubmed_id) or bool(pubmed_url),
                    "doctor_report.comparative_claims comparative_superiority requires pubmed_id or pubmed_url",
                )

    citations = payload.get("citations")
    _require(isinstance(citations, list), "doctor_report.citations must be array")
    citation_ids = set()
    for citation in citations:
        _require(isinstance(citation, dict), "doctor_report.citations item must be object")
        for field in ("citation_id", "source_id", "document_id", "version_id", "page_start", "page_end", "file_uri"):
            _require(citation.get(field) is not None, f"doctor_report.citations.{field} required")
        _require(_is_non_empty_string(citation.get("citation_id")), "doctor_report.citation_id invalid")
        _require(_is_non_empty_string(citation.get("source_id")), "doctor_report.source_id invalid")
        _require(isinstance(citation.get("page_start"), int) and citation["page_start"] >= 1, "citation.page_start invalid")
        _require(isinstance(citation.get("page_end"), int) and citation["page_end"] >= 1, "citation.page_end invalid")
        if citation.get("official_page_url") is not None:
            _require(_is_non_empty_string(citation.get("official_page_url")), "citation.official_page_url invalid")
        if citation.get("official_pdf_url") is not None:
            _require(_is_non_empty_string(citation.get("official_pdf_url")), "citation.official_pdf_url invalid")
        citation_ids.add(str(citation["citation_id"]))

    for section in plan:
        for step in section.get("steps", []):
            for citation_id in step.get("citation_ids", []):
                _require(str(citation_id) in citation_ids, "doctor_report.plan citation_ids must reference doctor_report.citations")
    for issue in issues:
        for citation_id in issue.get("citation_ids", []):
            _require(str(citation_id) in citation_ids, "doctor_report.issue citation_ids must reference doctor_report.citations")



def _validate_pack_patient_explain(
    payload: dict[str, Any],
    request_id: str,
    *,
    allow_pack_legacy_v1_0: bool,
) -> None:
    schema_version = str(payload.get("schema_version"))
    if allow_pack_legacy_v1_0:
        _require(schema_version in _PACK_PATIENT_SCHEMA_VERSIONS, "patient_explain.schema_version must be 1.0 or 1.2")
    else:
        _require(schema_version == "1.2", "patient_explain.schema_version must be 1.2")
    _require(payload.get("request_id") == request_id, "patient_explain.request_id must match top-level request_id")
    _require(_is_non_empty_string(payload.get("summary_plain")), "patient_explain.summary_plain required")
    _require(
        isinstance(payload.get("questions_for_doctor"), list) and len(payload["questions_for_doctor"]) > 0,
        "patient_explain.questions_for_doctor required",
    )
    _require(
        isinstance(payload.get("safety_notes"), list) and len(payload["safety_notes"]) > 0,
        "patient_explain.safety_notes required",
    )
    if schema_version == "1.2":
        _require(isinstance(payload.get("drug_safety"), dict), "patient_explain.drug_safety required")
        _validate_pack_patient_drug_safety(payload.get("drug_safety"))


def _validate_pack_doctor_drug_safety(payload: Any) -> None:
    _require(isinstance(payload, dict), "doctor_report.drug_safety must be object")
    _require(
        payload.get("status") in {"ok", "partial", "unavailable"},
        "doctor_report.drug_safety.status invalid",
    )
    for key in ("extracted_inn", "unresolved_candidates", "profiles", "signals", "warnings"):
        _require(isinstance(payload.get(key), list), f"doctor_report.drug_safety.{key} must be array")
    for signal in payload.get("signals", []):
        _require(isinstance(signal, dict), "doctor_report.drug_safety.signals entry must be object")
        _require(
            signal.get("severity") in {"critical", "warning", "info"},
            "doctor_report.drug_safety.signals.severity invalid",
        )
        _require(
            signal.get("kind") in {"contraindication", "inconsistency", "missing_data"},
            "doctor_report.drug_safety.signals.kind invalid",
        )
        _require(
            isinstance(signal.get("citation_ids"), list),
            "doctor_report.drug_safety.signals.citation_ids must be array",
        )
        if signal.get("severity") in {"critical", "warning"}:
            _require(
                len(signal.get("citation_ids", [])) > 0,
                "doctor_report.drug_safety.signals.citation_ids required for critical/warning",
            )
        if signal.get("source_origin") is not None:
            _require(
                str(signal.get("source_origin") or "").strip()
                in {"guideline_heuristic", "rule_engine", "api_derived", "supplementary"},
                "doctor_report.drug_safety.signals.source_origin invalid",
            )


def _validate_pack_patient_drug_safety(payload: Any) -> None:
    _require(isinstance(payload, dict), "patient_explain.drug_safety must be object")
    _require(
        payload.get("status") in {"ok", "partial", "unavailable"},
        "patient_explain.drug_safety.status invalid",
    )
    _require(
        isinstance(payload.get("important_risks"), list),
        "patient_explain.drug_safety.important_risks must be array",
    )
    _require(
        isinstance(payload.get("questions_for_doctor"), list),
        "patient_explain.drug_safety.questions_for_doctor must be array",
    )



def _validate_pack_run_meta(payload: dict[str, Any], request_id: str) -> None:
    _require(payload.get("schema_version") == "0.2", "run_meta.schema_version must be 0.2")
    _require(payload.get("request_id") == request_id, "run_meta.request_id must match top-level request_id")

    timings = payload.get("timings_ms")
    _require(isinstance(timings, dict), "run_meta.timings_ms required")
    _require(isinstance(timings.get("total"), int) and timings["total"] >= 0, "run_meta.timings_ms.total invalid")
    for field in ("retrieval", "llm", "postprocess"):
        if timings.get(field) is not None:
            _require(isinstance(timings.get(field), int) and timings[field] >= 0, f"run_meta.timings_ms.{field} invalid")

    _require(
        isinstance(payload.get("docs_retrieved_count"), int) and payload["docs_retrieved_count"] >= 0,
        "run_meta.docs_retrieved_count invalid",
    )
    _require(
        isinstance(payload.get("docs_after_filter_count"), int) and payload["docs_after_filter_count"] >= 0,
        "run_meta.docs_after_filter_count invalid",
    )
    _require(
        isinstance(payload.get("citations_count"), int) and payload["citations_count"] >= 0,
        "run_meta.citations_count invalid",
    )
    _require(
        isinstance(payload.get("evidence_valid_ratio"), (int, float)) and 0 <= float(payload["evidence_valid_ratio"]) <= 1,
        "run_meta.evidence_valid_ratio invalid",
    )
    _require(payload.get("retrieval_engine") in {"basic", "llamaindex", "other"}, "run_meta.retrieval_engine invalid")
    _require(payload.get("llm_path") in {"primary", "fallback", "deterministic"}, "run_meta.llm_path invalid")
    _require(
        str(payload.get("reasoning_mode") or "").strip() in {"compat", "llm_rag_only"},
        "run_meta.reasoning_mode invalid",
    )
    _require(
        payload.get("report_generation_path") in {"primary", "fallback", "deterministic_only"},
        "run_meta.report_generation_path invalid",
    )
    _require(
        payload.get("fallback_reason")
        in {
            "none",
            "no_docs",
            "low_recall",
            "llm_invalid_json",
            "llm_not_configured",
            "llm_no_valid_response",
            "llm_error",
            "timeout",
            "other",
        },
        "run_meta.fallback_reason invalid",
    )
    if str(payload.get("reasoning_mode") or "").strip() == "llm_rag_only":
        _require(payload.get("llm_path") == "primary", "run_meta.llm_path must be primary in llm_rag_only")
        _require(
            payload.get("report_generation_path") == "primary",
            "run_meta.report_generation_path must be primary in llm_rag_only",
        )
        _require(
            payload.get("fallback_reason") == "none",
            "run_meta.fallback_reason must be none in llm_rag_only",
        )



def _validate_pack_sources_only_result(payload: dict[str, Any]) -> None:
    mode = str(payload.get("mode") or "").strip().upper()
    _require(mode == "SOURCES_ONLY", "sources_only_result.mode must be SOURCES_ONLY")
    items = payload.get("items")
    _require(isinstance(items, list), "sources_only_result.items must be array")
    for item in items:
        _require(isinstance(item, dict), "sources_only_result.items entry must be object")
        _require(_is_non_empty_string(item.get("item_id")), "sources_only_result.items.item_id required")
        _require(_is_non_empty_string(item.get("title")), "sources_only_result.items.title required")
        _require(_is_non_empty_string(item.get("summary")), "sources_only_result.items.summary required")
        _require(isinstance(item.get("citation_ids"), list), "sources_only_result.items.citation_ids must be array")


def _validate_pack_historical_assessment(payload: dict[str, Any]) -> None:
    _require(_is_non_empty_string(payload.get("requested_as_of_date")), "historical_assessment.requested_as_of_date required")
    _require(payload.get("status") in {"ok", "insufficient_data"}, "historical_assessment.status invalid")
    _require(
        payload.get("reason_code")
        in {"ok", "missing_as_of_date", "future_as_of_date", "historical_sources_unavailable"},
        "historical_assessment.reason_code invalid",
    )
    for key in ("current_guideline", "as_of_date_guideline"):
        block = payload.get(key)
        _require(isinstance(block, dict), f"historical_assessment.{key} required")
        _require(_is_non_empty_string(block.get("as_of_date")), f"historical_assessment.{key}.as_of_date required")
        _require(isinstance(block.get("source_ids"), list), f"historical_assessment.{key}.source_ids must be array")
        _require(_is_non_empty_string(block.get("note")), f"historical_assessment.{key}.note required")
    _require(isinstance(payload.get("conflicts"), list), "historical_assessment.conflicts must be array")


def _validate_pack_analyze_response(payload: dict[str, Any], *, allow_pack_legacy_v1_0: bool) -> None:
    request_id = payload.get("request_id")
    _require(_is_non_empty_string(request_id), "request_id is required")

    doctor_report = payload.get("doctor_report")
    _require(isinstance(doctor_report, dict), "doctor_report is required")
    sources_only_result = payload.get("sources_only_result")
    sources_only_mode = isinstance(sources_only_result, dict) and str(sources_only_result.get("mode") or "").strip().upper() == "SOURCES_ONLY"
    _validate_pack_doctor_report(
        doctor_report,
        request_id=str(request_id),
        allow_pack_legacy_v1_0=allow_pack_legacy_v1_0,
        sources_only_mode=sources_only_mode,
    )

    patient_explain = payload.get("patient_explain")
    _require(isinstance(patient_explain, dict), "patient_explain is required")
    _validate_pack_patient_explain(
        patient_explain,
        request_id=str(request_id),
        allow_pack_legacy_v1_0=allow_pack_legacy_v1_0,
    )

    run_meta = payload.get("run_meta")
    _require(isinstance(run_meta, dict), "run_meta is required")
    _validate_pack_run_meta(run_meta, request_id=str(request_id))

    if sources_only_result is not None:
        _require(isinstance(sources_only_result, dict), "sources_only_result must be object")
        _validate_pack_sources_only_result(sources_only_result)

    historical_assessment = payload.get("historical_assessment")
    if historical_assessment is not None:
        _require(isinstance(historical_assessment, dict), "historical_assessment must be object")
        _validate_pack_historical_assessment(historical_assessment)

    meta = payload.get("meta")
    if meta is not None:
        _require(isinstance(meta, dict), "meta must be object")
        _require(
            str(meta.get("execution_profile") or "").strip() in {"compat", "strict_full"},
            "meta.execution_profile invalid",
        )
        _require(isinstance(meta.get("strict_mode"), bool), "meta.strict_mode must be boolean")
        _require(
            str(meta.get("retrieval_backend") or "").strip() in {"local", "qdrant"},
            "meta.retrieval_backend invalid",
        )
        _require(
            str(meta.get("embedding_backend") or "").strip() in {"hash", "openai"},
            "meta.embedding_backend invalid",
        )
        _require(
            str(meta.get("reranker_backend") or "").strip() in {"lexical", "llm"},
            "meta.reranker_backend invalid",
        )
        _require(isinstance(meta.get("fail_closed"), bool), "meta.fail_closed must be boolean")



def validate_analyze_response(
    payload: dict[str, Any],
    *,
    allow_pack_legacy_v1_0: bool = False,
) -> None:
    _require(isinstance(payload, dict), "response must be object")

    if _is_pack_analyze_response(payload):
        _validate_pack_analyze_response(payload, allow_pack_legacy_v1_0=allow_pack_legacy_v1_0)
        return

    _require(isinstance(payload.get("doctor_report"), dict), "doctor_report is required")
    validate_doctor_report(payload["doctor_report"])
    schema_version = payload["doctor_report"].get("schema_version")

    patient_explain = payload.get("patient_explain")
    if patient_explain is not None:
        _require(isinstance(patient_explain, dict), "patient_explain must be object")
        validate_patient_explain(patient_explain)
        _require(
            patient_explain.get("schema_version") == schema_version,
            "patient_explain.schema_version must match doctor_report.schema_version",
        )

    run_meta = payload.get("run_meta")
    if schema_version == SCHEMA_VERSION_V2:
        _require(isinstance(run_meta, dict), "run_meta is required for schema_version 0.2")
        validate_run_meta(run_meta)
    elif run_meta is not None:
        _require(isinstance(run_meta, dict), "run_meta must be object")
        validate_run_meta(run_meta)

    insufficient_data = payload.get("insufficient_data")
    if insufficient_data is not None:
        _require(isinstance(insufficient_data, dict), "insufficient_data must be object")
        _require(isinstance(insufficient_data.get("status"), bool), "insufficient_data.status must be boolean")
        _require(
            isinstance(insufficient_data.get("reason"), str) and bool(insufficient_data["reason"].strip()),
            "insufficient_data.reason is required",
        )

    sources_only_result = payload.get("sources_only_result")
    if sources_only_result is not None:
        _require(isinstance(sources_only_result, dict), "sources_only_result must be object")
        _validate_pack_sources_only_result(sources_only_result)

    historical_assessment = payload.get("historical_assessment")
    if historical_assessment is not None:
        _require(isinstance(historical_assessment, dict), "historical_assessment must be object")
        _validate_pack_historical_assessment(historical_assessment)


def validate_external_compatibility_projections(
    *,
    doctor_projection_v1_1: dict[str, Any],
    patient_projection_alt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    doctor_errors = validate_doctor_projection_v1_1(doctor_projection_v1_1)
    patient_errors = validate_patient_projection_alt(patient_projection_alt) if isinstance(patient_projection_alt, dict) else []
    return {
        "doctor_report_v1_1": {
            "valid": len(doctor_errors) == 0,
            "errors": doctor_errors,
        },
        "patient_explain_alt": {
            "valid": len(patient_errors) == 0,
            "errors": patient_errors,
        },
    }
