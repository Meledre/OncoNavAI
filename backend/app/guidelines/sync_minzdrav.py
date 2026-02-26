from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
import re
import urllib.request
from urllib.parse import urljoin


@dataclass(frozen=True)
class MinzdravDocument:
    doc_id: str
    doc_version: str
    source_page_url: str
    filename: str
    source_pdf_url: str = ""
    source_set: str = "minzdrav"
    cancer_type: str = "gastric_cancer"
    language: str = "ru"

    @property
    def source_url(self) -> str:
        return str(self.source_page_url or self.source_pdf_url).strip()


KNOWN_MINZDRAV_PDFS: list[MinzdravDocument] = [
    MinzdravDocument(
        doc_id="minzdrav_237_6",
        doc_version="237.6",
        source_page_url="https://cr.minzdrav.gov.ru/preview-cr/237_6",
        filename="КР237_6.pdf",
        cancer_type="gastric_cancer",
    ),
    MinzdravDocument(
        doc_id="minzdrav_574_rak_zheludka",
        doc_version="574",
        source_page_url="https://cr.minzdrav.gov.ru/preview-cr/574_1",
        source_pdf_url="https://static.edu.rosminzdrav.ru/fc0001/fdpo/decanat/NMO_MZ/onco_project/cr574-rak_zheludka.pdf",
        filename="cr574-rak_zheludka.pdf",
        cancer_type="gastric_cancer",
    ),
    MinzdravDocument(
        doc_id="minzdrav_rak_pishevoda_i_kardii_2024",
        doc_version="2024",
        source_page_url="https://cr.minzdrav.gov.ru/preview-cr/675_2",
        filename="cr_rak_pishevoda_i_kardii_2024.pdf",
        cancer_type="esophagogastric_junction_cancer",
    ),
]


def _default_fetch_bytes(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read()


def _default_fetch_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def is_pdf_payload(payload: bytes) -> bool:
    if not payload:
        return False
    stripped = payload.lstrip()
    return stripped.startswith(b"%PDF-")


def _looks_like_pdf_url(url: str) -> bool:
    token = str(url or "").strip().lower()
    return ".pdf" in token


def fetch_page_html(
    page_url: str,
    fetch_text: Callable[[str], str] | None = None,
) -> str:
    fetch = fetch_text or _default_fetch_text
    return fetch(page_url)


def extract_download_url_from_html(*, html: str, base_url: str) -> str:
    if not str(html or "").strip():
        return ""

    candidates: list[str] = []
    attribute_pattern = re.compile(
        r"""(?:href|data-download-url|data-url|data-href)\s*=\s*["']([^"']+)["']""",
        re.IGNORECASE,
    )
    onclick_pattern = re.compile(
        r"""onclick\s*=\s*["'][^"']*(?:location(?:\.href)?|window\.open)\s*\(?\s*['"]([^'"]+)['"]""",
        re.IGNORECASE,
    )
    absolute_pdf_pattern = re.compile(r"""https?://[^\s"'<>]+\.pdf(?:\?[^\s"'<>]*)?""", re.IGNORECASE)
    relative_pdf_pattern = re.compile(r"""/[^\s"'<>]+\.pdf(?:\?[^\s"'<>]*)?""", re.IGNORECASE)

    for match in attribute_pattern.finditer(html):
        candidates.append(str(match.group(1) or "").strip())
    for match in onclick_pattern.finditer(html):
        candidates.append(str(match.group(1) or "").strip())
    candidates.extend(str(item).strip() for item in absolute_pdf_pattern.findall(html))
    candidates.extend(str(item).strip() for item in relative_pdf_pattern.findall(html))

    seen: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        resolved = urljoin(base_url, candidate)
        if not resolved or resolved in seen:
            continue
        seen.add(resolved)
        if _looks_like_pdf_url(resolved):
            return resolved
    return ""


def resolve_minzdrav_pdf_from_page(
    document: MinzdravDocument,
    fetch_text: Callable[[str], str] | None = None,
) -> str:
    explicit_pdf_url = str(document.source_pdf_url or "").strip()
    if _looks_like_pdf_url(explicit_pdf_url):
        return explicit_pdf_url
    page_url = str(document.source_page_url or "").strip()
    if _looks_like_pdf_url(page_url):
        return page_url
    if not page_url:
        return explicit_pdf_url
    try:
        html = fetch_page_html(page_url, fetch_text=fetch_text)
    except Exception:  # noqa: BLE001
        return explicit_pdf_url
    extracted = extract_download_url_from_html(html=html, base_url=page_url)
    if extracted:
        return extracted
    return explicit_pdf_url


def download_minzdrav_pdf_with_url(
    document: MinzdravDocument,
    fetch_bytes: Callable[[str], bytes] | None = None,
    fetch_text: Callable[[str], str] | None = None,
) -> tuple[bytes, str]:
    fetch = fetch_bytes or _default_fetch_bytes
    resolved_pdf_url = resolve_minzdrav_pdf_from_page(document, fetch_text=fetch_text)
    candidates = [
        resolved_pdf_url,
        str(document.source_pdf_url or "").strip(),
        str(document.source_page_url or "").strip(),
    ]
    seen: set[str] = set()
    last_error: Exception | None = None

    for url in candidates:
        if not url or url in seen:
            continue
        seen.add(url)
        try:
            payload = fetch(url)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue
        if is_pdf_payload(payload):
            return payload, url
        last_error = ValueError(f"MINZDRAV_NON_PDF_CONTENT:{url}")

    if last_error:
        raise last_error
    raise ValueError("MINZDRAV_DOWNLOAD_FAILED:missing_source_url")


def download_minzdrav_pdf(
    document: MinzdravDocument,
    fetch_bytes: Callable[[str], bytes] | None = None,
    fetch_text: Callable[[str], str] | None = None,
) -> bytes:
    payload, _resolved_url = download_minzdrav_pdf_with_url(
        document,
        fetch_bytes=fetch_bytes,
        fetch_text=fetch_text,
    )
    return payload
