from __future__ import annotations

import json
from typing import Any

from backend.app.llm.provider_router import LLMProviderRouter
from backend.app.routing.nosology_router import NosologyRouteDecision


def _build_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "resolved_disease_id": {"type": "string"},
            "resolved_cancer_type": {"type": "string"},
            "match_strategy": {"type": "string"},
            "route_pairs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "source_id": {"type": "string"},
                        "doc_id": {"type": "string"},
                    },
                    "required": ["source_id", "doc_id"],
                    "additionalProperties": False,
                },
            },
            "source_ids": {"type": "array", "items": {"type": "string"}},
            "doc_ids": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["resolved_disease_id", "resolved_cancer_type", "match_strategy", "route_pairs", "source_ids", "doc_ids"],
        "additionalProperties": False,
    }


def plan_nosology_route_with_llm(
    *,
    llm_router: LLMProviderRouter,
    case_payload: dict[str, Any],
    language: str,
    requested_source_ids: list[str],
    available_routes: list[dict[str, Any]],
) -> NosologyRouteDecision:
    if llm_router.primary is None:
        raise RuntimeError("llm_rag_only requires primary LLM provider for route planning")

    primary_only_router = LLMProviderRouter(primary=llm_router.primary, fallback=None)
    route_candidates = [
        {
            "route_id": str(item.get("route_id") or ""),
            "disease_id": str(item.get("disease_id") or ""),
            "cancer_type": str(item.get("cancer_type") or ""),
            "source_id": str(item.get("source_id") or "").strip().lower(),
            "doc_id": str(item.get("doc_id") or "").strip(),
            "icd10_prefix": str(item.get("icd10_prefix") or "").strip().upper(),
            "keyword": str(item.get("keyword") or "").strip(),
            "priority": int(item.get("priority") or 100),
        }
        for item in available_routes
        if str(item.get("source_id") or "").strip() and str(item.get("doc_id") or "").strip()
    ][:400]
    if not route_candidates:
        raise RuntimeError("no active nosology routes available for llm_rag_only")

    prompt = (
        "Ты роутер нозологий в онкологическом контуре LLM+RAG.\n"
        "Выбери только релевантные source/doc пары из route_candidates.\n"
        "Запрещено выдумывать source_id/doc_id вне route_candidates.\n"
        "Верни строго JSON по схеме.\n"
        f"language={language}\n"
        f"requested_source_ids={json.dumps([str(item).strip().lower() for item in requested_source_ids if str(item).strip()], ensure_ascii=False)}\n"
        f"case_payload={json.dumps(case_payload, ensure_ascii=False)}\n"
        f"route_candidates={json.dumps(route_candidates, ensure_ascii=False)}\n"
    )
    payload, path = primary_only_router.generate_json(
        prompt=prompt,
        output_schema=_build_output_schema(),
        schema_name="nosology_route_plan_v1",
    )
    if str(path or "").strip().lower() != "primary":
        raise RuntimeError("llm_rag_only route planning must use primary provider path")
    if not isinstance(payload, dict):
        raise RuntimeError("llm_rag_only route planning returned empty payload")

    allowed_pairs = {
        (
            str(item.get("source_id") or "").strip().lower(),
            str(item.get("doc_id") or "").strip(),
        )
        for item in route_candidates
    }
    raw_route_pairs = payload.get("route_pairs") if isinstance(payload.get("route_pairs"), list) else []
    dedup_pairs: list[tuple[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for item in raw_route_pairs:
        if not isinstance(item, dict):
            continue
        pair = (
            str(item.get("source_id") or "").strip().lower(),
            str(item.get("doc_id") or "").strip(),
        )
        if not pair[0] or not pair[1] or pair in seen_pairs:
            continue
        if pair not in allowed_pairs:
            raise RuntimeError(f"llm_rag_only route planning produced unknown pair: {pair}")
        seen_pairs.add(pair)
        dedup_pairs.append(pair)

    if not dedup_pairs:
        raise RuntimeError("llm_rag_only route planning returned no valid route_pairs")

    source_ids = sorted({pair[0] for pair in dedup_pairs})
    doc_ids = sorted({pair[1] for pair in dedup_pairs})
    resolved_disease_id = str(payload.get("resolved_disease_id") or "").strip() or "unknown_disease"
    resolved_cancer_type = str(payload.get("resolved_cancer_type") or "").strip() or "unknown"
    match_strategy = str(payload.get("match_strategy") or "").strip() or "llm_route_planner"

    return NosologyRouteDecision(
        resolved_disease_id=resolved_disease_id,
        resolved_cancer_type=resolved_cancer_type,
        match_strategy=match_strategy,
        source_ids=source_ids,
        doc_ids=doc_ids,
        route_pairs=dedup_pairs,
    )
