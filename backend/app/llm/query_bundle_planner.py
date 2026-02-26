from __future__ import annotations

import json
from typing import Any

from backend.app.llm.provider_router import LLMProviderRouter


def _query_bundle_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "queries": {
                "type": "array",
                "items": {"type": "string"},
            }
        },
        "required": ["queries"],
        "additionalProperties": False,
    }


def build_query_bundle_with_llm(
    *,
    llm_router: LLMProviderRouter,
    base_query: str,
    query_type: str,
    cancer_type: str,
    case_payload: dict[str, Any],
    plan_sections: list[dict[str, Any]],
) -> list[str]:
    if llm_router.primary is None:
        raise RuntimeError("llm_rag_only requires primary LLM provider for query bundle planning")

    primary_only_router = LLMProviderRouter(primary=llm_router.primary, fallback=None)
    prompt = (
        "Ты формируешь query bundle для RAG-поиска в онкологии.\n"
        "Сформируй 2-6 поисковых запросов на русском (допустимы англ. биомаркеры и названия схем).\n"
        "Запросы должны покрывать: диагностику, стадию/линию, ключевые биомаркеры, текущую/следующую тактику.\n"
        "Верни строго JSON по схеме.\n"
        f"base_query={base_query}\n"
        f"query_type={query_type}\n"
        f"cancer_type={cancer_type}\n"
        f"case_payload={json.dumps(case_payload, ensure_ascii=False)}\n"
        f"plan_sections={json.dumps(plan_sections[:8], ensure_ascii=False)}\n"
    )
    payload, path = primary_only_router.generate_json(
        prompt=prompt,
        output_schema=_query_bundle_output_schema(),
        schema_name="rag_query_bundle_v1",
    )
    if str(path or "").strip().lower() != "primary":
        raise RuntimeError("llm_rag_only query bundle must use primary provider path")
    if not isinstance(payload, dict):
        raise RuntimeError("llm_rag_only query bundle returned empty payload")

    raw_queries = payload.get("queries") if isinstance(payload.get("queries"), list) else []
    queries: list[str] = []
    seen: set[str] = set()
    for item in raw_queries:
        text = str(item).strip()
        if not text:
            continue
        if text in seen:
            continue
        seen.add(text)
        queries.append(text)
        if len(queries) >= 6:
            break

    if not queries:
        raise RuntimeError("llm_rag_only query bundle returned no valid queries")
    if str(base_query or "").strip() and str(base_query).strip() not in seen:
        queries.insert(0, str(base_query).strip())
    return queries[:6]
