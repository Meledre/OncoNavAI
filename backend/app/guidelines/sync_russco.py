from __future__ import annotations

import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

from backend.app.guidelines.nosology_mapper import infer_cancer_type_for_guideline

RUSSCO_2025_INDEX_URL = "https://rosoncoweb.ru/standarts/RUSSCO/2025/"


@dataclass(frozen=True)
class RusscoDocument:
    url: str
    filename: str
    doc_id: str
    doc_version: str
    source_set: str = "russco"
    cancer_type: str = "gastric_cancer"
    language: str = "ru"


def _default_fetch_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=15) as response:
        return response.read().decode("utf-8", errors="ignore")


def _default_fetch_bytes(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read()


def parse_russco_index_html(index_html: str, base_url: str = RUSSCO_2025_INDEX_URL) -> list[str]:
    hrefs = re.findall(r'href=["\']([^"\']+\.pdf)["\']', index_html, flags=re.IGNORECASE)
    urls = []
    seen: set[str] = set()
    for href in hrefs:
        absolute = urllib.parse.urljoin(base_url, href)
        if absolute in seen:
            continue
        seen.add(absolute)
        urls.append(absolute)
    return urls


def _infer_russco_cancer_type(*, filename: str, url: str) -> str:
    normalized = str(filename or "").strip().lower()
    explicit_map = {
        "2025-1-1-13.pdf": "gastric_cancer",
        "2025-1-1-12.pdf": "esophagogastric_junction_cancer",
        "2025-1-1-19.pdf": "gist",
    }
    if normalized in explicit_map:
        return explicit_map[normalized]
    if normalized.startswith("2025-2-"):
        return "supportive_care"
    if normalized.startswith("2025-0-"):
        return "general_oncology"
    return infer_cancer_type_for_guideline(
        doc_id=normalized.replace(".pdf", ""),
        source_url=url,
        title=filename,
        fallback="unknown",
    )


def discover_russco_2025_documents(fetch_text: Callable[[str], str] | None = None) -> list[RusscoDocument]:
    fetch = fetch_text or _default_fetch_text
    html = fetch(RUSSCO_2025_INDEX_URL)
    urls = parse_russco_index_html(html, base_url=RUSSCO_2025_INDEX_URL)
    documents: list[RusscoDocument] = []
    for url in urls:
        filename = url.rsplit("/", 1)[-1]
        doc_id = filename.replace(".pdf", "").replace("-", "_")
        documents.append(
            RusscoDocument(
                url=url,
                filename=filename,
                doc_id=f"russco_{doc_id}",
                doc_version="2025",
                cancer_type=_infer_russco_cancer_type(filename=filename, url=url),
            )
        )
    return documents


def download_russco_pdf(url: str, fetch_bytes: Callable[[str], bytes] | None = None) -> bytes:
    fetch = fetch_bytes or _default_fetch_bytes
    return fetch(url)
