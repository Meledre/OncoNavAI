from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

from backend.app.guidelines.nosology_mapper import is_nosology_mapped
from backend.app.guidelines.source_registry import (
    OFFICIAL_SOURCE_RULES,
    evaluate_release_validity,
    normalize_source_set_id,
    normalize_source_set_ids,
    resolve_primary_source_url,
)
from backend.app.storage import SQLiteStore

_ICD10_RE = re.compile(r"\b([CD]\d{2}(?:\.[0-9A-Z]+)?)\b", re.IGNORECASE)


@dataclass(frozen=True)
class NosologyRouteDecision:
    resolved_disease_id: str
    resolved_cancer_type: str
    match_strategy: str
    source_ids: list[str]
    doc_ids: list[str]
    route_pairs: list[tuple[str, str]]
    candidate_chunks: int = 0


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _unique_pairs(values: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    result: list[tuple[str, str]] = []
    for source_id, doc_id in values:
        pair = (normalize_source_set_id(str(source_id)), str(doc_id).strip())
        if not pair[0] or not pair[1] or pair in seen:
            continue
        seen.add(pair)
        result.append(pair)
    return result


def _max_icd10_docs_per_source() -> int:
    raw = str(os.getenv("ONCOAI_ROUTER_MAX_ICD10_DOCS_PER_SOURCE", "1")).strip()
    try:
        value = int(raw)
    except ValueError:
        value = 1
    return max(0, min(value, 50))


def _max_support_docs_per_source() -> int:
    raw = str(os.getenv("ONCOAI_ROUTER_MAX_SUPPORT_DOCS_PER_SOURCE", "1")).strip()
    try:
        value = int(raw)
    except ValueError:
        value = 1
    return max(0, min(value, 20))


def _cap_routes_per_source(routes: list[dict[str, Any]], *, max_docs_per_source: int) -> list[dict[str, Any]]:
    if max_docs_per_source <= 0:
        return routes
    ordered = sorted(routes, key=lambda item: (int(item.get("priority", 100)), str(item.get("route_id") or "")))
    per_source_counts: dict[str, int] = {}
    seen_pairs: set[tuple[str, str]] = set()
    selected: list[dict[str, Any]] = []
    for row in ordered:
        source_id = normalize_source_set_id(str(row.get("source_id") or ""))
        doc_id = str(row.get("doc_id") or "").strip()
        if not source_id or not doc_id:
            continue
        pair = (source_id, doc_id)
        if pair in seen_pairs:
            continue
        current_count = int(per_source_counts.get(source_id, 0))
        if current_count >= max_docs_per_source:
            continue
        seen_pairs.add(pair)
        per_source_counts[source_id] = current_count + 1
        selected.append(row)
    return selected


def _normalize_language(value: Any) -> str:
    language = str(value or "ru").strip().lower()
    return language if language in {"ru", "en"} else "ru"


def _extract_icd10_code(case_payload: dict[str, Any]) -> str:
    diagnosis = case_payload.get("diagnosis")
    if isinstance(diagnosis, dict):
        candidate = str(diagnosis.get("icd10") or "").strip().upper()
        match = _ICD10_RE.search(candidate)
        if match:
            return match.group(1).upper()
    notes = str(case_payload.get("notes") or "")
    match = _ICD10_RE.search(notes)
    if match:
        return match.group(1).upper()
    return ""


def _icd10_prefix(icd10_code: str) -> str:
    token = str(icd10_code or "").strip().upper()
    if "." in token:
        return token.split(".", 1)[0]
    if re.fullmatch(r"[CD]\d{2}", token):
        return token
    return ""


def _normalize_cancer_type(value: Any, icd10_code: str, icd10_prefix: str) -> str:
    cancer_type = str(value or "").strip()
    if cancer_type and cancer_type.lower() not in {"unknown", "auto", "none", "null"}:
        return cancer_type
    if str(icd10_code or "").upper().startswith("C79.3"):
        return "cns_metastases_c79_3"
    mapping = {
        "C16": "gastric_cancer",
        "C34": "nsclc_egfr",
        "C50": "breast_hr+/her2-",
        "C71": "brain_primary_c71",
    }
    mapped = mapping.get(icd10_prefix)
    if mapped:
        return mapped
    if re.fullmatch(r"C\d{2}", icd10_prefix):
        return f"oncology_{icd10_prefix.lower()}"
    return "general_oncology"


def _is_ambiguous_brain_request(case_payload: dict[str, Any], icd10_code: str) -> bool:
    diagnosis = case_payload.get("diagnosis")
    if isinstance(diagnosis, dict):
        diagnosis_icd10 = str(diagnosis.get("icd10") or "").strip().upper()
        if _ICD10_RE.search(diagnosis_icd10):
            return False
    elif icd10_code:
        return False
    normalized = str(case_payload.get("cancer_type") or "").strip().lower()
    return normalized in {"brain", "malignant_brain_tumor"}


def _route_rows_to_decision(
    *,
    rows: list[dict[str, Any]],
    fallback_disease_id: str,
    fallback_cancer_type: str,
    match_strategy: str,
) -> NosologyRouteDecision:
    ordered_rows = sorted(rows, key=lambda item: (int(item.get("priority", 100)), str(item.get("route_id") or "")))
    source_ids = _unique([normalize_source_set_id(str(item.get("source_id") or "")) for item in ordered_rows])
    doc_ids = _unique([str(item.get("doc_id") or "").strip() for item in ordered_rows])
    route_pairs = _unique_pairs(
        [(normalize_source_set_id(str(item.get("source_id") or "")), str(item.get("doc_id") or "").strip()) for item in ordered_rows]
    )

    resolved_disease_id = fallback_disease_id
    resolved_cancer_type = fallback_cancer_type
    if ordered_rows:
        first = ordered_rows[0]
        row_disease_id = str(first.get("disease_id") or "").strip()
        row_cancer_type = str(first.get("cancer_type") or "").strip()
        if row_disease_id and row_disease_id != "unknown_disease":
            resolved_disease_id = row_disease_id
        if row_cancer_type and row_cancer_type != "unknown":
            resolved_cancer_type = row_cancer_type

    return NosologyRouteDecision(
        resolved_disease_id=resolved_disease_id or "unknown_disease",
        resolved_cancer_type=resolved_cancer_type or "unknown",
        match_strategy=match_strategy,
        source_ids=source_ids,
        doc_ids=doc_ids,
        route_pairs=route_pairs,
    )


def _match_icd10_routes(routes: list[dict[str, Any]], icd10_code: str, icd10_prefix: str) -> list[dict[str, Any]]:
    if not icd10_code and not icd10_prefix:
        return []
    normalized_code = str(icd10_code or "").strip().upper()
    normalized_prefix = str(icd10_prefix or "").strip().upper()
    matched: list[dict[str, Any]] = []
    for route in routes:
        route_prefix = str(route.get("icd10_prefix") or "").strip().upper()
        if not route_prefix or route_prefix == "*":
            continue
        if (
            normalized_code == route_prefix
            or normalized_code.startswith(f"{route_prefix}.")
            or normalized_prefix == route_prefix
        ):
            matched.append(route)
    return matched


def _match_keyword_routes(routes: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    haystack = str(text or "").strip().lower()
    if not haystack:
        return []
    scored: list[tuple[int, dict[str, Any]]] = []
    for route in routes:
        keyword = str(route.get("keyword") or "").strip().lower()
        if not keyword or keyword == "*":
            continue
        if keyword in haystack:
            score = 100 + len(keyword)
        else:
            tokens = [token for token in re.split(r"\s+", keyword) if len(token) > 2]
            if not tokens:
                continue
            hits = sum(1 for token in tokens if token in haystack)
            if hits == 0:
                continue
            score = hits
        scored.append((score, route))
    scored.sort(key=lambda item: (-item[0], int(item[1].get("priority", 100))))
    return [row for _score, row in scored]


def _fallback_rows_from_docs(
    *,
    store: SQLiteStore,
    language: str,
    cancer_type: str,
    fallback_disease_id: str,
    eligible_pairs: set[tuple[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    docs = store.list_docs()
    docs_by_language = [doc for doc in docs if str(doc.get("language") or "").strip().lower() == language]
    if eligible_pairs is not None:
        docs_by_language = [
            doc
            for doc in docs_by_language
            if (
                str(doc.get("source_set") or "").strip().lower(),
                str(doc.get("doc_id") or "").strip(),
            )
            in eligible_pairs
        ]
    docs_by_cancer = [doc for doc in docs_by_language if str(doc.get("cancer_type") or "").strip() == cancer_type]
    rows_source = docs_by_cancer if docs_by_cancer else docs_by_language
    strategy = "cancer_type_fallback" if docs_by_cancer else "default_sources_fallback"

    rows: list[dict[str, Any]] = []
    for index, doc in enumerate(rows_source, start=1):
        source_id = normalize_source_set_id(str(doc.get("source_set") or ""))
        rows.append(
            {
                "route_id": f"fallback:{source_id}:{doc['doc_id']}:{doc['doc_version']}",
                "language": language,
                "icd10_prefix": "*",
                "keyword": "*",
                "disease_id": fallback_disease_id or "unknown_disease",
                "cancer_type": str(doc.get("cancer_type") or cancer_type or "unknown"),
                "source_id": source_id,
                "doc_id": str(doc.get("doc_id") or "").strip(),
                "priority": 100 + index,
                "active": True,
                "updated_at": str(doc.get("uploaded_at") or ""),
            }
        )
    return rows, strategy


def _build_keyword_haystack(case_payload: dict[str, Any]) -> str:
    diagnosis = case_payload.get("diagnosis") if isinstance(case_payload.get("diagnosis"), dict) else {}
    parts = [
        str(case_payload.get("notes") or ""),
        str(diagnosis.get("histology") or ""),
        str(diagnosis.get("disease_id") or ""),
        str(diagnosis.get("icd10") or ""),
    ]
    return "\n".join(parts).strip().lower()


def _is_guideline_doc(
    *,
    cancer_type: str,
    metadata: dict[str, Any] | None,
) -> bool:
    if str(cancer_type or "").strip().lower() == "reference_icd10":
        return False
    if isinstance(metadata, dict):
        doc_kind = str(metadata.get("doc_kind") or "guideline").strip().lower()
        if doc_kind != "guideline":
            return False
    return True


def _pair_release_ready_for_routing(
    *,
    store: SQLiteStore,
    source_set: str,
    docs: list[dict[str, Any]],
) -> bool:
    normalized_source = normalize_source_set_id(source_set)
    for doc in docs:
        doc_id = str(doc.get("doc_id") or "").strip()
        doc_version = str(doc.get("doc_version") or "").strip()
        if not doc_id or not doc_version:
            continue
        version = store.get_guideline_version_by_doc(doc_id=doc_id, doc_version=doc_version)
        metadata = version.get("metadata") if isinstance(version, dict) else {}
        metadata = metadata if isinstance(metadata, dict) else {}
        cancer_type = str(doc.get("cancer_type") or "")
        if not _is_guideline_doc(cancer_type=cancer_type, metadata=metadata):
            continue

        if normalized_source in OFFICIAL_SOURCE_RULES:
            source_url = resolve_primary_source_url(
                source_url=str(metadata.get("source_url") or ""),
                source_page_url=str(metadata.get("source_page_url") or ""),
                source_pdf_url=str(metadata.get("source_pdf_url") or ""),
            )
            validity = evaluate_release_validity(
                source_set=normalized_source,
                source_url=source_url,
                status=str((version or {}).get("status") or ""),
                doc_id=doc_id,
                nosology_mapped=is_nosology_mapped(cancer_type),
            )
            if bool(validity.get("is_valid")):
                return True
            continue

        # Keep non-official corpora available in local/dev/test contours.
        return True
    return False


def _build_route_doc_eligibility(
    *,
    store: SQLiteStore,
    language: str,
) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    docs = [
        doc
        for doc in store.list_docs()
        if str(doc.get("language") or "").strip().lower() == language
    ]
    docs_by_pair: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for doc in docs:
        pair = (
            normalize_source_set_id(str(doc.get("source_set") or "")),
            str(doc.get("doc_id") or "").strip(),
        )
        if not pair[0] or not pair[1]:
            continue
        docs_by_pair.setdefault(pair, []).append(doc)

    known_pairs = set(docs_by_pair.keys())
    eligible_pairs: set[tuple[str, str]] = set()
    for pair, entries in docs_by_pair.items():
        if _pair_release_ready_for_routing(store=store, source_set=pair[0], docs=entries):
            eligible_pairs.add(pair)
    return known_pairs, eligible_pairs


def _filter_routes_by_release_eligibility(
    routes: list[dict[str, Any]],
    *,
    known_pairs: set[tuple[str, str]],
    eligible_pairs: set[tuple[str, str]],
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for row in routes:
        pair = (
            normalize_source_set_id(str(row.get("source_id") or "")),
            str(row.get("doc_id") or "").strip(),
        )
        if not pair[0] or not pair[1]:
            continue
        if pair not in known_pairs:
            # Do not trust orphan official routes that bypass docs/status registry.
            if pair[0] in OFFICIAL_SOURCE_RULES:
                continue
            # Preserve legacy non-official route-only rows in local/dev contours.
            filtered.append(row)
            continue
        if pair in eligible_pairs:
            filtered.append(row)
    return filtered


def _build_global_support_rows(
    *,
    store: SQLiteStore,
    language: str,
    fallback_disease_id: str,
    eligible_pairs: set[tuple[str, str]],
    requested_sources: list[str],
) -> list[dict[str, Any]]:
    requested = set(normalize_source_set_ids([str(item).strip() for item in requested_sources if str(item).strip()]))
    rows: list[dict[str, Any]] = []
    for doc in store.list_docs():
        doc_language = str(doc.get("language") or "").strip().lower()
        if doc_language != language:
            continue
        source_id = normalize_source_set_id(str(doc.get("source_set") or ""))
        doc_id = str(doc.get("doc_id") or "").strip()
        pair = (source_id, doc_id)
        if pair not in eligible_pairs:
            continue
        if requested and source_id not in requested:
            continue
        cancer_type = str(doc.get("cancer_type") or "").strip().lower()
        if cancer_type not in {"supportive_care", "general_oncology"}:
            continue
        rows.append(
            {
                "route_id": f"support:{source_id}:{doc_id}:{doc['doc_version']}",
                "language": language,
                "icd10_prefix": "*",
                "keyword": "*",
                "disease_id": fallback_disease_id or "unknown_disease",
                "cancer_type": cancer_type,
                "source_id": source_id,
                "doc_id": doc_id,
                "priority": 150,
                "active": True,
                "updated_at": str(doc.get("uploaded_at") or ""),
            }
        )
    max_per_source = _max_support_docs_per_source()
    if max_per_source <= 0:
        return rows
    per_source_counts: dict[str, int] = {}
    capped_rows: list[dict[str, Any]] = []
    for row in rows:
        source_id = normalize_source_set_id(str(row.get("source_id") or ""))
        if not source_id:
            continue
        current_count = int(per_source_counts.get(source_id, 0))
        if current_count >= max_per_source:
            continue
        per_source_counts[source_id] = current_count + 1
        capped_rows.append(row)
    return capped_rows


def resolve_nosology_route(
    *,
    store: SQLiteStore,
    case_payload: dict[str, Any],
    language: str,
    requested_source_ids: list[str],
) -> NosologyRouteDecision:
    normalized_language = _normalize_language(language)
    diagnosis = case_payload.get("diagnosis") if isinstance(case_payload.get("diagnosis"), dict) else {}
    icd10_code = _extract_icd10_code(case_payload)
    icd10_prefix = _icd10_prefix(icd10_code)
    fallback_disease_id = str(diagnosis.get("disease_id") or "").strip() or "unknown_disease"
    fallback_cancer_type = _normalize_cancer_type(case_payload.get("cancer_type"), icd10_code, icd10_prefix)

    if _is_ambiguous_brain_request(case_payload, icd10_code):
        return NosologyRouteDecision(
            resolved_disease_id=fallback_disease_id,
            resolved_cancer_type="unknown",
            match_strategy="ambiguous_brain_scope",
            source_ids=[],
            doc_ids=[],
            route_pairs=[],
        )

    routes = store.list_nosology_routes(language=normalized_language, active_only=True)
    known_pairs, eligible_pairs = _build_route_doc_eligibility(store=store, language=normalized_language)
    routes = _filter_routes_by_release_eligibility(
        routes,
        known_pairs=known_pairs,
        eligible_pairs=eligible_pairs,
    )

    matched_routes = _match_icd10_routes(routes, icd10_code, icd10_prefix)
    match_strategy = "icd10_prefix"
    if matched_routes:
        matched_routes = _cap_routes_per_source(
            matched_routes,
            max_docs_per_source=_max_icd10_docs_per_source(),
        )
    if not matched_routes:
        matched_routes = _match_keyword_routes(routes, _build_keyword_haystack(case_payload))
        match_strategy = "keyword"

    if not matched_routes:
        matched_routes, match_strategy = _fallback_rows_from_docs(
            store=store,
            language=normalized_language,
            cancer_type=fallback_cancer_type,
            fallback_disease_id=fallback_disease_id,
            eligible_pairs=eligible_pairs,
        )

    requested = _unique(normalize_source_set_ids([str(source).strip() for source in requested_source_ids]))
    if requested:
        filtered = [row for row in matched_routes if str(row.get("source_id") or "").strip().lower() in requested]
        if filtered:
            matched_routes = filtered
        else:
            fallback_rows = []
            docs = store.list_docs()
            for doc in docs:
                source_id = normalize_source_set_id(str(doc.get("source_set") or ""))
                doc_id = str(doc.get("doc_id") or "").strip()
                pair = (source_id, doc_id)
                if source_id not in requested:
                    continue
                if pair not in eligible_pairs:
                    continue
                if str(doc.get("language") or "").strip().lower() != normalized_language:
                    continue
                fallback_rows.append(
                    {
                        "route_id": f"manual:{source_id}:{doc_id}:{doc['doc_version']}",
                        "language": normalized_language,
                        "icd10_prefix": "*",
                        "keyword": "*",
                        "disease_id": fallback_disease_id,
                        "cancer_type": str(doc.get("cancer_type") or fallback_cancer_type),
                        "source_id": source_id,
                        "doc_id": doc_id,
                        "priority": 1,
                        "active": True,
                        "updated_at": str(doc.get("uploaded_at") or ""),
                    }
                )
            if fallback_rows:
                matched_routes = fallback_rows
        match_strategy = "manual_source_override"

    support_rows = _build_global_support_rows(
        store=store,
        language=normalized_language,
        fallback_disease_id=fallback_disease_id,
        eligible_pairs=eligible_pairs,
        requested_sources=requested,
    )
    if support_rows:
        existing_pairs = {
            (normalize_source_set_id(str(row.get("source_id") or "")), str(row.get("doc_id") or "").strip())
            for row in matched_routes
            if isinstance(row, dict)
        }
        for row in support_rows:
            pair = (normalize_source_set_id(str(row.get("source_id") or "")), str(row.get("doc_id") or "").strip())
            if pair in existing_pairs:
                continue
            existing_pairs.add(pair)
            matched_routes.append(row)

    return _route_rows_to_decision(
        rows=matched_routes,
        fallback_disease_id=fallback_disease_id,
        fallback_cancer_type=fallback_cancer_type,
        match_strategy=match_strategy,
    )
