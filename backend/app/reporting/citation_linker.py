from __future__ import annotations

import re
import uuid
from typing import Any, Callable


_CITATION_NAMESPACE = uuid.UUID("f84244dc-740f-4634-b56b-a643e8e6a04d")
_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9+./_-]{2,}")


def _tokenize(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(str(text or ""))}


def build_citations_from_chunks(
    *,
    reranked_chunks: list[dict[str, Any]],
    max_citations: int = 40,
    version_metadata_resolver: Callable[[str, str], dict[str, Any] | None] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    selected_chunks: list[dict[str, Any]] = []
    seen_chunk_ids: set[str] = set()
    seen_source: set[str] = set()

    for chunk in reranked_chunks:
        source = str(chunk.get("source_set") or "").strip().lower()
        chunk_id = str(chunk.get("chunk_id") or "").strip()
        if not source or not chunk_id or source in seen_source:
            continue
        seen_source.add(source)
        seen_chunk_ids.add(chunk_id)
        selected_chunks.append(chunk)

    for chunk in reranked_chunks:
        if len(selected_chunks) >= max_citations:
            break
        chunk_id = str(chunk.get("chunk_id") or "").strip()
        if not chunk_id or chunk_id in seen_chunk_ids:
            continue
        seen_chunk_ids.add(chunk_id)
        selected_chunks.append(chunk)

    citations: list[dict[str, Any]] = []
    chunk_to_citation: dict[str, str] = {}
    metadata_cache: dict[tuple[str, str], dict[str, Any]] = {}
    for chunk in selected_chunks:
        chunk_id = str(chunk.get("chunk_id") or "").strip()
        if not chunk_id:
            continue
        doc_id = str(chunk.get("doc_id") or "")
        doc_version = str(chunk.get("doc_version") or "")
        official_page_url = ""
        official_pdf_url = ""
        if version_metadata_resolver and doc_id and doc_version:
            cache_key = (doc_id, doc_version)
            if cache_key not in metadata_cache:
                metadata = version_metadata_resolver(doc_id, doc_version)
                metadata_cache[cache_key] = metadata if isinstance(metadata, dict) else {}
            metadata = metadata_cache.get(cache_key, {})
            if isinstance(metadata, dict):
                official_page_url = str(metadata.get("source_page_url") or "").strip()
                official_pdf_url = str(metadata.get("source_pdf_url") or "").strip()
                fallback_url = str(metadata.get("source_url") or "").strip()
                if fallback_url and not official_page_url and not official_pdf_url:
                    if ".pdf" in fallback_url.lower():
                        official_pdf_url = fallback_url
                    else:
                        official_page_url = fallback_url
        seed = f"{chunk.get('source_set')}|{chunk.get('doc_id')}|{chunk.get('doc_version')}|{chunk_id}"
        citation_id = str(uuid.uuid5(_CITATION_NAMESPACE, seed))
        chunk_to_citation[chunk_id] = citation_id
        page_start = int(chunk.get("page_start") or int(chunk.get("pdf_page_index", 0)) + 1)
        page_end = int(chunk.get("page_end") or page_start)
        citation_payload: dict[str, Any] = {
            "citation_id": citation_id,
            "source_id": str(chunk.get("source_set") or "unknown_source"),
            "document_id": str(uuid.uuid5(_CITATION_NAMESPACE, f"doc:{chunk.get('doc_id') or 'unknown'}")),
            "version_id": str(
                uuid.uuid5(_CITATION_NAMESPACE, f"version:{chunk.get('doc_id') or 'unknown'}:{chunk.get('doc_version') or 'unknown'}")
            ),
            "chunk_id": chunk_id,
            "page_start": max(1, page_start),
            "page_end": max(max(1, page_start), page_end),
            "section_path": str(chunk.get("section_title") or "Guideline fragment"),
            "quote": str(chunk.get("text") or "")[:800],
            "file_uri": f"/api/admin/docs/{chunk.get('doc_id')}/{chunk.get('doc_version')}/pdf",
            "score": float(chunk.get("score") or 0.0),
        }
        if official_page_url:
            citation_payload["official_page_url"] = official_page_url
        if official_pdf_url:
            citation_payload["official_pdf_url"] = official_pdf_url
        citations.append(citation_payload)
    return citations, chunk_to_citation


def _match_chunk_ids_by_text(
    *,
    text: str,
    reranked_chunks: list[dict[str, Any]],
    top_k: int = 2,
) -> list[str]:
    step_tokens = _tokenize(text)
    if not step_tokens:
        return []
    scored: list[tuple[float, str]] = []
    for chunk in reranked_chunks:
        chunk_id = str(chunk.get("chunk_id") or "").strip()
        if not chunk_id:
            continue
        chunk_tokens = _tokenize(str(chunk.get("text") or ""))
        if not chunk_tokens:
            continue
        overlap = step_tokens.intersection(chunk_tokens)
        if not overlap:
            continue
        score = len(overlap) / float(max(len(step_tokens), 1))
        scored.append((score, chunk_id))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [chunk_id for _score, chunk_id in scored[:top_k]]


def attach_plan_citations(
    *,
    plan_sections: list[dict[str, Any]],
    reranked_chunks: list[dict[str, Any]],
    chunk_to_citation: dict[str, str],
    fallback_citation_ids: list[str],
) -> list[dict[str, Any]]:
    updated_sections: list[dict[str, Any]] = []
    for section in plan_sections:
        if not isinstance(section, dict):
            continue
        next_section = dict(section)
        steps = section.get("steps")
        if not isinstance(steps, list):
            next_section["steps"] = []
            updated_sections.append(next_section)
            continue
        next_steps: list[dict[str, Any]] = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            step_copy = dict(step)
            text = str(step.get("text") or "")
            matched_chunk_ids = _match_chunk_ids_by_text(text=text, reranked_chunks=reranked_chunks, top_k=2)
            citation_ids = [chunk_to_citation[item] for item in matched_chunk_ids if item in chunk_to_citation]
            if not citation_ids:
                citation_ids = list(fallback_citation_ids)
            step_copy["citation_ids"] = list(dict.fromkeys(citation_ids))
            next_steps.append(step_copy)
        next_section["steps"] = next_steps
        updated_sections.append(next_section)
    return updated_sections


def attach_issue_citations(
    *,
    issues: list[dict[str, Any]],
    reranked_chunks: list[dict[str, Any]],
    chunk_to_citation: dict[str, str],
    fallback_citation_ids: list[str],
) -> list[dict[str, Any]]:
    updated: list[dict[str, Any]] = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        issue_copy = dict(issue)
        text = f"{issue_copy.get('summary') or ''}\n{issue_copy.get('details') or ''}"
        matched_chunk_ids = _match_chunk_ids_by_text(text=text, reranked_chunks=reranked_chunks, top_k=2)
        citation_ids = [chunk_to_citation[item] for item in matched_chunk_ids if item in chunk_to_citation]
        if not citation_ids:
            citation_ids = list(fallback_citation_ids)
        issue_copy["citation_ids"] = list(dict.fromkeys(citation_ids))
        updated.append(issue_copy)
    return updated
