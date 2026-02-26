from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _token_count(text: str) -> int:
    return len([item for item in re.split(r"\s+", text.strip()) if item])


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _deterministic_chunk_id(
    *,
    doc_id: str,
    doc_version: str,
    section_path: list[str],
    page_start: int,
    page_end: int,
    content_hash: str,
    ordinal: int,
) -> str:
    payload = "|".join(
        [
            doc_id,
            doc_version,
            "/".join(section_path),
            str(page_start),
            str(page_end),
            content_hash,
            str(max(0, int(ordinal))),
        ]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"{doc_id}_{doc_version}_{digest}"


def _chunk_text(text: str, max_tokens: int = 550) -> list[dict[str, Any]]:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        normalized = "No extractable text found in PDF. Placeholder chunk created for indexing."

    paragraphs = [item.strip() for item in normalized.split("\n") if item.strip()]
    if not paragraphs:
        paragraphs = [normalized]

    chunks: list[dict[str, Any]] = []
    current_section = "General"
    buffer: list[str] = []
    buffer_tokens = 0

    def flush() -> None:
        nonlocal buffer_tokens
        if not buffer:
            return
        content = " ".join(buffer).strip()
        if not content:
            return
        chunks.append(
            {
                "text": content,
                "section_path": [current_section],
                "section_title": current_section,
            }
        )
        buffer.clear()
        buffer_tokens = 0

    for paragraph in paragraphs:
        if re.match(r"^\d+(\.\d+)*\s+", paragraph):
            flush()
            current_section = paragraph[:120]
            continue

        paragraph_tokens = _token_count(paragraph)
        if buffer and buffer_tokens + paragraph_tokens > max_tokens:
            flush()
        buffer.append(paragraph)
        buffer_tokens += paragraph_tokens
    flush()
    return chunks


def _chunk_text_legacy_char(text: str, chunk_size_chars: int = 2200) -> list[dict[str, Any]]:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        normalized = "No extractable text found in PDF. Placeholder chunk created for indexing."

    chunks: list[dict[str, Any]] = []
    start = 0
    while start < len(normalized):
        end = min(len(normalized), start + max(200, chunk_size_chars))
        chunk_text = normalized[start:end].strip()
        if chunk_text:
            chunks.append(
                {
                    "text": chunk_text,
                    "section_path": ["Guideline fragment"],
                    "section_title": "Guideline fragment",
                }
            )
        if end >= len(normalized):
            break
        start = end
    if not chunks:
        chunks.append(
            {
                "text": normalized,
                "section_path": ["Guideline fragment"],
                "section_title": "Guideline fragment",
            }
        )
    return chunks


def _extract_pages_advanced(path: Path) -> list[dict[str, Any]] | None:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:  # noqa: BLE001
        return None

    try:
        reader = PdfReader(str(path))
    except Exception:  # noqa: BLE001
        return None

    pages: list[dict[str, Any]] = []
    for idx, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            text = ""
        pages.append({"page_index": idx, "page_label": str(idx + 1), "text": text})
    return pages or None


def _infer_section_title(chunk_text: str, fallback: str) -> str:
    cleaned = " ".join(chunk_text.split()).strip()
    if not cleaned:
        return fallback
    return cleaned[:80]


def extract_pdf_chunks(
    path: Path,
    metadata: dict[str, Any],
    *,
    structural_chunker_enabled: bool = True,
) -> list[dict[str, Any]]:
    now_iso = datetime.now(timezone.utc).isoformat()
    result = []
    source_url = str(metadata.get("source_url") or "")

    advanced_pages = _extract_pages_advanced(path)
    if advanced_pages:
        for page in advanced_pages:
            page_index = int(page.get("page_index", 0))
            page_label = str(page.get("page_label") or page_index + 1)
            page_start = max(1, page_index + 1)
            page_end = page_start
            page_text = str(page.get("text", ""))
            chunk_payloads = (
                _chunk_text(page_text)
                if structural_chunker_enabled
                else _chunk_text_legacy_char(page_text)
            )
            for ordinal, chunk_payload in enumerate(chunk_payloads, start=1):
                chunk_text = str(chunk_payload.get("text") or "")
                section_path = chunk_payload.get("section_path") if isinstance(chunk_payload.get("section_path"), list) else []
                section_path = [str(item) for item in section_path if str(item).strip()]
                if not section_path:
                    section_path = [str(chunk_payload.get("section_title") or "Guideline fragment")]
                content_hash = _content_hash(chunk_text)
                result.append(
                    {
                        "chunk_id": _deterministic_chunk_id(
                            doc_id=str(metadata["doc_id"]),
                            doc_version=str(metadata["doc_version"]),
                            section_path=section_path,
                            page_start=page_start,
                            page_end=page_end,
                            content_hash=content_hash,
                            ordinal=ordinal,
                        ),
                        "doc_id": metadata["doc_id"],
                        "doc_version": metadata["doc_version"],
                        "source_set": metadata["source_set"],
                        "cancer_type": metadata["cancer_type"],
                        "language": metadata["language"],
                        "pdf_page_index": page_index,
                        "page_label": page_label,
                        "section_title": str(chunk_payload.get("section_title") or _infer_section_title(chunk_text, "Guideline fragment")),
                        "section_path": section_path,
                        "page_start": page_start,
                        "page_end": page_end,
                        "token_count": _token_count(chunk_text),
                        "source_url": source_url,
                        "content_hash": content_hash,
                        "text": chunk_text,
                        "updated_at": now_iso,
                    }
                )
        return result

    raw = path.read_bytes()
    # Dependency-free deterministic fallback.
    text_guess = raw[:20000].decode("utf-8", errors="ignore")
    chunks = _chunk_text(text_guess) if structural_chunker_enabled else _chunk_text_legacy_char(text_guess)
    for idx, chunk_payload in enumerate(chunks):
        chunk_text = str(chunk_payload.get("text") or "")
        page_index = idx
        page_start = max(1, page_index + 1)
        page_end = page_start
        section_path = chunk_payload.get("section_path") if isinstance(chunk_payload.get("section_path"), list) else []
        section_path = [str(item) for item in section_path if str(item).strip()] or ["Guideline fragment"]
        content_hash = _content_hash(chunk_text)
        result.append(
            {
                "chunk_id": _deterministic_chunk_id(
                    doc_id=str(metadata["doc_id"]),
                    doc_version=str(metadata["doc_version"]),
                    section_path=section_path,
                    page_start=page_start,
                    page_end=page_end,
                    content_hash=content_hash,
                    ordinal=idx + 1,
                ),
                "doc_id": metadata["doc_id"],
                "doc_version": metadata["doc_version"],
                "source_set": metadata["source_set"],
                "cancer_type": metadata["cancer_type"],
                "language": metadata["language"],
                "pdf_page_index": page_index,
                "page_label": str(page_index + 1),
                "section_title": str(chunk_payload.get("section_title") or _infer_section_title(chunk_text, "Guideline fragment")),
                "section_path": section_path,
                "page_start": page_start,
                "page_end": page_end,
                "token_count": _token_count(chunk_text),
                "source_url": source_url,
                "content_hash": content_hash,
                "text": chunk_text,
                "updated_at": now_iso,
            }
        )
    return result
