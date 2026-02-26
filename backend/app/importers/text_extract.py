from __future__ import annotations

import hashlib
import io
import zipfile
import xml.etree.ElementTree as ET
from typing import Any

from backend.app.exceptions import ValidationError

_PDF_MIME_TYPES = {"application/pdf"}
_DOCX_MIME_TYPES = {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
_TEXT_MIME_TYPES = {"text/plain", "text/markdown"}
_WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _sha256_prefixed(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _normalize_text(value: str) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _single_page_map(text: str) -> tuple[int, dict[str, list[int]]]:
    return 1, {"1": [0, len(text)]}


def _decode_text_bytes(payload: bytes) -> str:
    for encoding in ("utf-8", "latin-1"):
        try:
            return _normalize_text(payload.decode(encoding))
        except UnicodeDecodeError:
            continue
    return _normalize_text(payload.decode("utf-8", errors="ignore"))


def _extract_pdf_text(payload: bytes) -> tuple[str, int, dict[str, list[int]]]:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise ValidationError(f"PDF extraction unavailable: {exc}") from exc

    try:
        reader = PdfReader(io.BytesIO(payload))
    except Exception as exc:  # noqa: BLE001
        raise ValidationError(f"Failed to read PDF: {exc}") from exc

    page_count = len(reader.pages)
    page_map: dict[str, list[int]] = {}
    page_texts: list[str] = []
    cursor = 0
    for page_index, page in enumerate(reader.pages, start=1):
        try:
            raw_text = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            raw_text = ""
        normalized = _normalize_text(raw_text)
        if page_texts:
            cursor += 1  # newline delimiter
        start = cursor
        page_texts.append(normalized)
        cursor += len(normalized)
        page_map[str(page_index)] = [start, cursor]

    text = "\n".join(page_texts).strip()
    if not text:
        text = "No extractable text found in PDF."
        page_count, page_map = _single_page_map(text)
    return text, max(1, page_count), page_map


def _extract_docx_text(payload: bytes) -> tuple[str, int, dict[str, list[int]]]:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            xml_payload = archive.read("word/document.xml")
    except Exception as exc:  # noqa: BLE001
        raise ValidationError(f"Failed to read DOCX: {exc}") from exc

    try:
        root = ET.fromstring(xml_payload)
    except ET.ParseError as exc:
        raise ValidationError(f"Failed to parse DOCX XML: {exc}") from exc

    body = root.find(f"{_WORD_NS}body")
    if body is None:
        raise ValidationError("Failed to parse DOCX: word/document.xml has no body")

    parts: list[str] = []
    for paragraph in body.iter(f"{_WORD_NS}p"):
        text_chunks: list[str] = []
        for node in paragraph.iter():
            if node.tag == f"{_WORD_NS}t" and node.text:
                text_chunks.append(node.text)
            elif node.tag == f"{_WORD_NS}tab":
                text_chunks.append("\t")
            elif node.tag in {f"{_WORD_NS}br", f"{_WORD_NS}cr"}:
                text_chunks.append("\n")
        line = _normalize_text("".join(text_chunks))
        if not line:
            continue
        # Preserve list semantics for better downstream extraction.
        if paragraph.find(f".//{_WORD_NS}numPr") is not None and not line.startswith(("•", "-", "*")):
            line = f"• {line}"
        parts.append(line)

    text = "\n".join(parts).strip()
    if not text:
        text = "No extractable text found in DOCX."
    pages_count, page_map = _single_page_map(text)
    return text, pages_count, page_map


def _build_extraction_warnings(*, kind: str, text: str, pages_count: int, payload_size: int) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    normalized_text = str(text or "").strip()
    text_len = len(normalized_text)
    is_placeholder = normalized_text.lower().startswith("no extractable text found")

    if not is_placeholder and text_len < 120:
        warnings.append(
            {
                "code": "LOW_TEXT_VOLUME",
                "message": f"{kind.upper()} text is short; extraction confidence reduced.",
            }
        )

    if kind == "docx":
        size_kb = float(payload_size) / 1024.0
        if (size_kb >= 12.0 and text_len < 260) or (size_kb >= 20.0 and text_len < 450):
            warnings.append(
                {
                    "code": "DOCX_POSSIBLE_TABLE_LOSS",
                    "message": "DOCX extraction produced unexpectedly short text; verify table content was parsed.",
                }
            )
    elif kind == "pdf" and pages_count <= 1 and text_len < 180 and not is_placeholder:
        warnings.append(
            {
                "code": "LOW_TEXT_VOLUME",
                "message": "PDF text is short on a single page; extraction confidence reduced.",
            }
        )

    dedup: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in warnings:
        code = str(item.get("code") or "").strip()
        message = str(item.get("message") or "").strip()
        if not code or not message:
            continue
        key = (code, message)
        if key in seen:
            continue
        seen.add(key)
        dedup.append({"code": code, "message": message})
    return dedup


def _detect_file_kind(filename: str, mime: str) -> str:
    name = str(filename or "").strip().lower()
    mime_normalized = str(mime or "").strip().lower()
    if name.endswith(".pdf") or mime_normalized in _PDF_MIME_TYPES:
        return "pdf"
    if name.endswith(".docx") or mime_normalized in _DOCX_MIME_TYPES:
        return "docx"
    if name.endswith(".txt") or name.endswith(".md") or mime_normalized in _TEXT_MIME_TYPES:
        return "text"
    return "unsupported"


def extract_text(file_bytes: bytes, filename: str, mime: str) -> dict[str, Any]:
    kind = _detect_file_kind(filename=filename, mime=mime)
    if kind == "unsupported":
        raise ValidationError(f"Unsupported file type: {filename or mime}")

    if kind == "pdf":
        try:
            text, pages_count, page_map = _extract_pdf_text(file_bytes)
        except ValidationError:
            text = _decode_text_bytes(file_bytes[:20000]) or "No extractable text found in PDF."
            pages_count, page_map = _single_page_map(text)
    elif kind == "docx":
        text, pages_count, page_map = _extract_docx_text(file_bytes)
    else:
        text = _decode_text_bytes(file_bytes)
        pages_count, page_map = _single_page_map(text)

    if not text:
        text = "No extractable text found."
        pages_count, page_map = _single_page_map(text)

    warnings = _build_extraction_warnings(
        kind=kind,
        text=text,
        pages_count=pages_count,
        payload_size=len(file_bytes),
    )

    return {
        "text": text,
        "pages_count": pages_count,
        "page_map": page_map,
        "sha256": _sha256_prefixed(file_bytes),
        "file_kind": kind,
        "warnings": warnings,
    }
