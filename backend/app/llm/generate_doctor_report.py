from __future__ import annotations

import json
import re
import uuid
from typing import Any

from backend.app.llm.provider_router import LLMProviderRouter
from backend.app.llm.prompt_registry import PromptRegistry
from backend.app.llm.prompt_schema_guard import guard_and_normalize_system_prompt
from backend.app.llm.schemas_strict import DoctorReportLLMStrict
from backend.app.rules.diff_engine import DiffIssue


DOCTOR_REPORT_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "minLength": 1},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "issue_id": {"type": "string", "minLength": 1},
                    "severity": {"type": "string", "enum": ["critical", "important", "note"]},
                    "category": {"type": "string", "minLength": 1},
                    "title": {"type": "string", "minLength": 1},
                    "description": {"type": "string", "minLength": 1},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "chunk_ids": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string", "minLength": 1},
                    },
                },
                "required": ["issue_id", "severity", "category", "title", "description", "confidence", "chunk_ids"],
                "additionalProperties": False,
            },
        },
        "missing_data": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string", "minLength": 1},
                    "reason": {"type": "string", "minLength": 1},
                },
                "required": ["field", "reason"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string", "minLength": 1},
    },
    "required": ["summary", "issues", "missing_data", "notes"],
    "additionalProperties": False,
}


def _text_char_profile(value: str) -> tuple[int, int]:
    text = str(value or "")
    cyrillic = len(re.findall(r"[А-Яа-яЁё]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    return cyrillic, latin


def _is_ru_text_compatible(value: str, *, max_latin_without_cyr: int = 8) -> bool:
    cyrillic, latin = _text_char_profile(value)
    if cyrillic >= 2:
        return True
    return latin <= max_latin_without_cyr


def _issue_to_strict(issue: DiffIssue, idx: int, chunk_ids: list[str]) -> dict[str, Any]:
    return {
        "issue_id": f"ISS-{idx}",
        "severity": issue.severity,
        "category": issue.category,
        "title": issue.title,
        "description": issue.description,
        "confidence": 0.72 if issue.severity != "note" else 0.55,
        "chunk_ids": chunk_ids[:1],
    }


def build_doctor_report_llm_strict(
    kb_version: str,
    diff_issues: list[DiffIssue],
    retrieved_chunks: list[dict[str, Any]],
) -> DoctorReportLLMStrict:
    top_chunk_ids = [chunk["chunk_id"] for chunk in retrieved_chunks[:3]]
    strict_issues = [_issue_to_strict(issue, idx + 1, top_chunk_ids) for idx, issue in enumerate(diff_issues)]

    if not strict_issues and retrieved_chunks:
        strict_issues.append(
            {
                "issue_id": "ISS-0",
                "severity": "note",
                "category": "other",
                "title": "Критических расхождений не выявлено",
                "description": "Текущий план в целом согласуется с доступными фрагментами клинических рекомендаций.",
                "confidence": 0.51,
                "chunk_ids": [retrieved_chunks[0]["chunk_id"]],
            }
        )

    return {
        "schema_version": "0.1",
        "report_id": f"rep-{uuid.uuid4()}",
        "kb_version": kb_version,
        "summary": f"Выявлено {len(strict_issues)} потенциальных замечаний при проверке плана лечения по индексированным рекомендациям.",
        "issues": strict_issues,
        "missing_data": [{"field": "performance_status", "reason": "Нужно уточнить функциональный статус для повышения уверенности в проверке."}],
        "notes": "Отчёт является поддержкой принятия решений и должен быть проверен лечащим врачом.",
    }


def _build_prompt(
    kb_version: str,
    diff_issues: list[DiffIssue],
    retrieved_chunks: list[dict[str, Any]],
    *,
    compact: bool = False,
) -> str:
    chunk_limit = 3 if compact else 6
    chunk_text_limit = 180 if compact else 400
    diff_limit = 4 if compact else 8
    routed_sources = sorted(
        {
            str(chunk.get("source_set") or "").strip()
            for chunk in retrieved_chunks
            if str(chunk.get("source_set") or "").strip()
        }
    )
    routed_docs = sorted(
        {
            str(chunk.get("doc_id") or "").strip()
            for chunk in retrieved_chunks
            if str(chunk.get("doc_id") or "").strip()
        }
    )
    context_chunks = [
        {
            "chunk_id": chunk.get("chunk_id"),
            "doc_id": chunk.get("doc_id"),
            "doc_version": chunk.get("doc_version"),
            "section_title": chunk.get("section_title"),
            "text": str(chunk.get("text", ""))[:chunk_text_limit],
        }
        for chunk in retrieved_chunks[:chunk_limit]
    ]
    diff_payload = [
        {
            "severity": item.severity,
            "category": item.category,
            "title": item.title,
            "description": item.description,
        }
        for item in diff_issues[:diff_limit]
    ]
    return (
        "You are generating a STRICT JSON doctor report for clinical decision support.\n"
        "Return JSON object only. No markdown.\n"
        "Schema keys: summary, issues, missing_data, notes.\n"
        "Each issue must include: severity, category, title, description, confidence (0..1), chunk_ids (array).\n"
        f"kb_version={kb_version}\n"
        f"routed_sources={json.dumps(routed_sources, ensure_ascii=False)}\n"
        f"routed_docs={json.dumps(routed_docs, ensure_ascii=False)}\n"
        f"diff_issues={json.dumps(diff_payload, ensure_ascii=False)}\n"
        f"retrieved_chunks={json.dumps(context_chunks, ensure_ascii=False)}\n"
    )


def _coerce_issue(
    raw: dict[str, Any],
    idx: int,
    allowed_chunk_ids: list[str],
) -> dict[str, Any] | None:
    severity = str(raw.get("severity", "")).strip().lower()
    if severity not in {"critical", "important", "note"}:
        category_hint = str(raw.get("category", "")).strip().lower()
        title_hint = str(raw.get("title", "")).strip().lower()
        summary_hint = str(raw.get("summary", "")).strip().lower()
        merged_hint = " ".join(item for item in (category_hint, title_hint, summary_hint) if item).strip()
        if any(token in merged_hint for token in ("critical", "contra", "urgent", "опас")):
            severity = "critical"
        elif any(token in merged_hint for token in ("warn", "important", "missing", "непол", "дефиц")):
            severity = "important"
        else:
            severity = "note"
    category = str(raw.get("category", "other")).strip() or "other"
    title = str(raw.get("title") or raw.get("summary") or raw.get("issue") or "").strip()
    description = str(
        raw.get("description")
        or raw.get("details")
        or raw.get("detail")
        or raw.get("message")
        or ""
    ).strip()
    if not description and title:
        description = title
    if not title and description:
        title = description[:120]
    if not title:
        title = "Клиническое замечание"
    if not description:
        description = "Требуется уточнение клинического шага."

    if not _is_ru_text_compatible(title, max_latin_without_cyr=10):
        title = "Клиническое замечание"
    if not _is_ru_text_compatible(description, max_latin_without_cyr=14):
        description = "Требуется уточнение клинического шага."

    raw_confidence = raw.get("confidence")
    confidence = float(raw_confidence) if isinstance(raw_confidence, (int, float)) else (0.7 if severity != "note" else 0.55)
    confidence = max(0.0, min(1.0, confidence))

    raw_chunk_ids = raw.get("chunk_ids")
    if isinstance(raw_chunk_ids, list):
        candidate_ids = raw_chunk_ids
    elif isinstance(raw_chunk_ids, str):
        candidate_ids = [raw_chunk_ids]
    else:
        candidate_ids = []
    chunk_ids = [str(chunk_id) for chunk_id in candidate_ids if str(chunk_id) in allowed_chunk_ids]
    if not chunk_ids and allowed_chunk_ids:
        chunk_ids = [allowed_chunk_ids[0]]
    if not chunk_ids:
        return None

    return {
        "issue_id": str(raw.get("issue_id") or f"ISS-{idx}"),
        "severity": severity,
        "category": category,
        "title": title,
        "description": description,
        "confidence": confidence,
        "chunk_ids": chunk_ids[:3],
    }


def _coerce_llm_report(
    payload: dict[str, Any] | None,
    *,
    kb_version: str,
    fallback: DoctorReportLLMStrict,
    allowed_chunk_ids: list[str],
) -> DoctorReportLLMStrict | None:
    if not isinstance(payload, dict):
        return None
    raw_text = str(payload.get("_raw_text") or "").strip()
    if raw_text and len(raw_text) >= 24:
        cleaned_lines = [line.strip(" -\t") for line in raw_text.splitlines() if line.strip()]
        def _is_human_summary_line(line: str) -> bool:
            candidate = line.strip()
            if len(candidate) < 24:
                return False
            if candidate[0] in {'{', '[', '"', "'", "}"}:
                return False
            lowered = candidate.lower()
            if lowered.startswith(("schema_version", "summary", "issues", "missing_data", "notes")):
                return False
            return True

        summary_from_raw = next((line for line in cleaned_lines if _is_human_summary_line(line)), "")
        if summary_from_raw and not _is_ru_text_compatible(summary_from_raw, max_latin_without_cyr=8):
            summary_from_raw = ""
        issue_line = next(
            (
                line
                for line in cleaned_lines
                if any(token in line.lower() for token in ("несоответ", "риск", "проблем", "ошиб", "треб", "необходимо"))
            ),
            "",
        )
        if issue_line and not _is_ru_text_compatible(issue_line, max_latin_without_cyr=12):
            issue_line = ""
        synthesized_payload: dict[str, Any] = {
            "summary": summary_from_raw or fallback["summary"],
            "issues": (
                [
                    {
                        "severity": "important",
                        "category": "other",
                        "title": issue_line[:140] or "Требуется клиническая проверка сформированного ответа.",
                        "description": issue_line[:400] or raw_text[:400],
                        "chunk_ids": [allowed_chunk_ids[0]] if allowed_chunk_ids else [],
                    }
                ]
                if issue_line and allowed_chunk_ids
                else fallback["issues"]
            ),
            "missing_data": fallback["missing_data"],
            "notes": raw_text[:500],
        }
        payload = synthesized_payload

    raw_issues = payload.get("issues")
    if isinstance(raw_issues, dict):
        raw_issues = [raw_issues]
    if not isinstance(raw_issues, list):
        return None

    issues: list[dict[str, Any]] = []
    for idx, item in enumerate(raw_issues, start=1):
        if isinstance(item, dict):
            issue = _coerce_issue(item, idx=idx, allowed_chunk_ids=allowed_chunk_ids)
        elif isinstance(item, str):
            issue = _coerce_issue(
                {
                    "title": item.strip() or "Клиническое замечание",
                    "description": item.strip() or "Требуется уточнение клинического шага.",
                    "severity": "note",
                    "category": "other",
                },
                idx=idx,
                allowed_chunk_ids=allowed_chunk_ids,
            )
        else:
            issue = None
        if issue:
            issues.append(issue)

    if not issues and fallback["issues"]:
        issues = fallback["issues"]

    summary = str(payload.get("summary", "")).strip() or fallback["summary"]
    if not _is_ru_text_compatible(summary, max_latin_without_cyr=8):
        summary = fallback["summary"]
    raw_notes = payload.get("notes")
    if isinstance(raw_notes, list):
        notes = "\n".join(str(item).strip() for item in raw_notes if str(item).strip()).strip()
    else:
        notes = str(raw_notes or "").strip()
    notes = notes or fallback["notes"]
    if not _is_ru_text_compatible(notes, max_latin_without_cyr=28):
        notes = fallback["notes"]

    raw_missing = payload.get("missing_data")
    missing_data: list[dict[str, str]] = []
    if isinstance(raw_missing, list):
        for item in raw_missing:
            if not isinstance(item, dict):
                continue
            field = str(item.get("field") or item.get("field_name") or item.get("name") or "").strip()
            reason = str(item.get("reason", "")).strip()
            if field and reason:
                missing_data.append({"field": field, "reason": reason})
    if not missing_data:
        missing_data = fallback["missing_data"]

    return {
        "schema_version": "0.2",
        "report_id": str(payload.get("report_id") or f"rep-{uuid.uuid4()}"),
        "kb_version": kb_version,
        "summary": summary,
        "issues": issues,
        "missing_data": missing_data,
        "notes": notes,
    }


def _validate_issue_llm_strict(
    raw: dict[str, Any],
    *,
    allowed_chunk_ids: list[str],
) -> dict[str, Any] | None:
    issue_id = str(raw.get("issue_id") or "").strip()
    severity = str(raw.get("severity") or "").strip().lower()
    category = str(raw.get("category") or "").strip()
    title = str(raw.get("title") or "").strip()
    description = str(raw.get("description") or "").strip()
    confidence = raw.get("confidence")
    raw_chunk_ids = raw.get("chunk_ids")

    if not issue_id:
        return None
    if severity not in {"critical", "important", "note"}:
        return None
    if not category or not title or not description:
        return None
    if not isinstance(confidence, (int, float)):
        return None
    confidence_value = float(confidence)
    if confidence_value < 0.0 or confidence_value > 1.0:
        return None
    if not isinstance(raw_chunk_ids, list):
        return None
    chunk_ids = [str(item).strip() for item in raw_chunk_ids if str(item).strip()]
    if not chunk_ids:
        return None
    if allowed_chunk_ids:
        allowed = set(allowed_chunk_ids)
        if any(chunk_id not in allowed for chunk_id in chunk_ids):
            return None

    return {
        "issue_id": issue_id,
        "severity": severity,
        "category": category,
        "title": title,
        "description": description,
        "confidence": confidence_value,
        "chunk_ids": chunk_ids[:3],
    }


def _validate_missing_data_llm_strict(raw_missing: Any) -> list[dict[str, str]] | None:
    if not isinstance(raw_missing, list):
        return None
    normalized: list[dict[str, str]] = []
    for item in raw_missing:
        if not isinstance(item, dict):
            return None
        field = str(item.get("field") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if not field or not reason:
            return None
        normalized.append({"field": field, "reason": reason})
    return normalized


def _validate_llm_report_without_coercion(
    payload: dict[str, Any] | None,
    *,
    kb_version: str,
    allowed_chunk_ids: list[str],
) -> DoctorReportLLMStrict | None:
    if not isinstance(payload, dict):
        return None
    summary = str(payload.get("summary") or "").strip()
    notes = str(payload.get("notes") or "").strip()
    raw_issues = payload.get("issues")
    if not summary or not notes:
        return None
    if not isinstance(raw_issues, list):
        return None

    issues: list[dict[str, Any]] = []
    for item in raw_issues:
        if not isinstance(item, dict):
            return None
        normalized_issue = _validate_issue_llm_strict(item, allowed_chunk_ids=allowed_chunk_ids)
        if normalized_issue is None:
            return None
        issues.append(normalized_issue)

    missing_data = _validate_missing_data_llm_strict(payload.get("missing_data"))
    if missing_data is None:
        return None

    return {
        "schema_version": "0.2",
        "report_id": str(payload.get("report_id") or f"rep-{uuid.uuid4()}"),
        "kb_version": kb_version,
        "summary": summary,
        "issues": issues,
        "missing_data": missing_data,
        "notes": notes,
    }


def _resolve_system_prompt(
    *,
    prompt_registry: PromptRegistry | None,
    prompt_schema_strict: bool,
) -> str | None:
    if prompt_registry is None:
        return None
    prompt_key = "doctor_report_v1_1_system_prompt"
    if prompt_schema_strict:
        prompt_text = prompt_registry.load(prompt_key)
    else:
        prompt_text = prompt_registry.load_optional(prompt_key)
        if not prompt_text:
            return None
    return guard_and_normalize_system_prompt(
        prompt_key=prompt_key,
        prompt_text=prompt_text,
        output_schema=DOCTOR_REPORT_OUTPUT_SCHEMA,
        strict_mode=prompt_schema_strict,
    )


def _is_ollama_fallback_only_router(llm_router: LLMProviderRouter) -> bool:
    fallback_url = str(getattr(llm_router.fallback, "url", "") or "").lower()
    return (
        llm_router.primary is None
        and llm_router.fallback is not None
        and ("ollama" in fallback_url or ":11434" in fallback_url)
    )


def _build_local_rescue_prompt(
    *,
    kb_version: str,
    diff_issues: list[DiffIssue],
    retrieved_chunks: list[dict[str, Any]],
) -> str:
    diff_payload = [
        {
            "severity": item.severity,
            "category": item.category,
            "title": item.title,
            "description": item.description,
        }
        for item in diff_issues[:3]
    ]
    chunk_payload = [
        {
            "chunk_id": chunk.get("chunk_id"),
            "doc_id": chunk.get("doc_id"),
            "section_title": chunk.get("section_title"),
            "text": str(chunk.get("text", ""))[:120],
        }
        for chunk in retrieved_chunks[:2]
    ]
    return (
        "Верни только JSON-объект без markdown.\n"
        "Ключи: summary, issues, missing_data, notes.\n"
        "issues: массив объектов c полями severity, category, title, description, confidence, chunk_ids.\n"
        "severity только: critical|important|note.\n"
        "summary и notes на русском.\n"
        f"kb_version={kb_version}\n"
        f"diff_issues={json.dumps(diff_payload, ensure_ascii=False)}\n"
        f"retrieved_chunks={json.dumps(chunk_payload, ensure_ascii=False)}\n"
    )


def build_doctor_report_with_fallback(
    kb_version: str,
    diff_issues: list[DiffIssue],
    retrieved_chunks: list[dict[str, Any]],
    llm_router: LLMProviderRouter,
    prompt_registry: PromptRegistry | None = None,
    prompt_schema_strict: bool = False,
    *,
    fail_closed: bool = False,
    strict_llm_only: bool = False,
) -> tuple[DoctorReportLLMStrict, str, str | None]:
    fallback = build_doctor_report_llm_strict(
        kb_version=kb_version,
        diff_issues=diff_issues,
        retrieved_chunks=retrieved_chunks,
    )

    if not (llm_router.primary or llm_router.fallback):
        if fail_closed:
            raise RuntimeError("strict_full requires configured LLM provider")
        if strict_llm_only:
            raise RuntimeError("llm_rag_only requires configured primary LLM provider")
        return fallback, "deterministic", "llm_not_configured"

    effective_router = llm_router
    if fail_closed:
        if llm_router.primary is None:
            raise RuntimeError("strict_full requires primary LLM provider")
        if isinstance(llm_router, LLMProviderRouter):
            effective_router = LLMProviderRouter(primary=llm_router.primary, fallback=None)
    elif strict_llm_only:
        if llm_router.primary is None:
            raise RuntimeError("llm_rag_only requires primary LLM provider")
        if isinstance(llm_router, LLMProviderRouter):
            effective_router = LLMProviderRouter(primary=llm_router.primary, fallback=None)

    is_ollama_fallback_only = _is_ollama_fallback_only_router(effective_router)
    system_prompt = _resolve_system_prompt(
        prompt_registry=prompt_registry,
        prompt_schema_strict=prompt_schema_strict,
    )
    if is_ollama_fallback_only and system_prompt and len(system_prompt) > 1800:
        # Local fallback models can time out on very long system prompts.
        system_prompt = system_prompt[:1800]

    try:
        prompt = _build_prompt(
            kb_version=kb_version,
            diff_issues=diff_issues,
            retrieved_chunks=retrieved_chunks,
            compact=is_ollama_fallback_only,
        )
        if system_prompt:
            try:
                payload, path = effective_router.generate_json(
                    prompt=prompt,
                    output_schema=DOCTOR_REPORT_OUTPUT_SCHEMA,
                    schema_name="doctor_report_v2",
                    system_prompt=system_prompt,
                )
            except TypeError:
                payload, path = effective_router.generate_json(
                    prompt=prompt,
                    output_schema=DOCTOR_REPORT_OUTPUT_SCHEMA,
                    schema_name="doctor_report_v2",
                )
        else:
            payload, path = effective_router.generate_json(
                prompt=prompt,
                output_schema=DOCTOR_REPORT_OUTPUT_SCHEMA,
                schema_name="doctor_report_v2",
            )
        if payload is None and path == "deterministic" and is_ollama_fallback_only:
            rescue_prompt = _build_local_rescue_prompt(
                kb_version=kb_version,
                diff_issues=diff_issues,
                retrieved_chunks=retrieved_chunks,
            )
            payload, path = effective_router.generate_json(
                prompt=rescue_prompt,
                output_schema=DOCTOR_REPORT_OUTPUT_SCHEMA,
                schema_name="doctor_report_v2",
            )
    except Exception:  # noqa: BLE001
        if fail_closed:
            raise RuntimeError("LLM doctor report generation failed in fail-closed mode")
        if strict_llm_only:
            raise RuntimeError("LLM doctor report generation failed in strict llm_rag_only mode")
        return fallback, "deterministic", "llm_error"

    allowed_chunk_ids = [str(chunk["chunk_id"]) for chunk in retrieved_chunks]
    if strict_llm_only:
        strict = _validate_llm_report_without_coercion(
            payload,
            kb_version=kb_version,
            allowed_chunk_ids=allowed_chunk_ids,
        )
    else:
        strict = _coerce_llm_report(
            payload,
            kb_version=kb_version,
            fallback=fallback,
            allowed_chunk_ids=allowed_chunk_ids,
        )
    if strict is None:
        if fail_closed:
            raise RuntimeError("LLM doctor report returned invalid response in fail-closed mode")
        if strict_llm_only:
            raise RuntimeError("LLM doctor report returned invalid response in strict llm_rag_only mode")
        if path == "fallback":
            return fallback, "llm_fallback", "llm_invalid_response"
        reason = "llm_no_valid_response" if path == "deterministic" else "llm_invalid_response"
        return fallback, "deterministic", reason

    if fail_closed and path != "primary":
        raise RuntimeError("strict_full forbids fallback/deterministic doctor report generation path")
    if strict_llm_only and path != "primary":
        raise RuntimeError("llm_rag_only forbids fallback/deterministic doctor report generation path")

    if path == "primary":
        return strict, "llm_primary", None
    if path == "fallback":
        return strict, "llm_fallback", None
    return strict, "deterministic", "llm_no_valid_response"


def map_strict_to_public_report(
    strict_report: DoctorReportLLMStrict,
    chunks_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    issues = []
    for strict_issue in strict_report["issues"]:
        evidence = []
        for chunk_id in strict_issue["chunk_ids"]:
            chunk = chunks_by_id.get(chunk_id)
            if not chunk:
                continue
            evidence.append(
                {
                    "doc_id": chunk["doc_id"],
                    "doc_version": chunk["doc_version"],
                    "source_set": chunk["source_set"],
                    "cancer_type": chunk["cancer_type"],
                    "language": chunk["language"],
                    "section_title": chunk.get("section_title", "Guideline fragment"),
                    "pdf_page_index": chunk["pdf_page_index"],
                    "page_label": chunk.get("page_label", str(chunk["pdf_page_index"] + 1)),
                    "chunk_id": chunk_id,
                    "quote": chunk.get("text", "")[:220],
                }
            )

        issues.append(
            {
                "issue_id": strict_issue["issue_id"],
                "severity": strict_issue["severity"],
                "category": strict_issue["category"],
                "title": strict_issue["title"],
                "description": strict_issue["description"],
                "confidence": strict_issue["confidence"],
                "evidence": evidence,
            }
        )

    return {
        "schema_version": "0.1",
        "report_id": strict_report["report_id"],
        "kb_version": strict_report["kb_version"],
        "summary": strict_report["summary"],
        "issues": issues,
        "missing_data": strict_report["missing_data"],
        "notes": strict_report["notes"],
    }
