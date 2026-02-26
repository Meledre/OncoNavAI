from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.config import Settings
from backend.app.exceptions import ValidationError
from backend.app.service import OncoService


def make_settings(root: Path) -> Settings:
    data = root / "data"
    return Settings(
        project_root=root,
        data_dir=data,
        docs_dir=data / "docs",
        reports_dir=data / "reports",
        db_path=data / "oncoai.sqlite3",
        local_core_base_url="http://localhost:8000",
        demo_token="demo-token",
        rate_limit_per_minute=100,
        llm_primary_url="",
        llm_primary_model="gpt-4o-mini",
        llm_primary_api_key="",
        llm_fallback_url="",
        llm_fallback_model="qwen2.5-7b-instruct",
        llm_fallback_api_key="",
    )


def _upload_doc(
    service: OncoService,
    *,
    doc_id: str,
    doc_version: str,
    source_set: str,
    source_url: str,
) -> None:
    service.admin_upload(
        role="admin",
        filename=f"{doc_id}.pdf",
        content=b"%PDF-1.4 validity test",
        metadata={
            "doc_id": doc_id,
            "doc_version": doc_version,
            "source_set": source_set,
            "cancer_type": "gastric_cancer",
            "language": "ru",
            "source_url": source_url,
        },
    )


def test_admin_docs_valid_only_filters_non_release_records(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    _upload_doc(
        service,
        doc_id="russco_valid",
        doc_version="2025",
        source_set="russco",
        source_url="https://rosoncoweb.ru/standarts/RUSSCO/2025/2025-1-1-13.pdf",
    )
    service.admin_doc_rechunk(role="admin", doc_id="russco_valid", doc_version="2025")
    service.admin_doc_approve(role="admin", doc_id="russco_valid", doc_version="2025")

    _upload_doc(
        service,
        doc_id="demo_doc",
        doc_version="v1",
        source_set="mvp_guidelines_ru_2025",
        source_url="https://example.local/demo.pdf",
    )

    all_docs = service.admin_docs(role="admin", valid_only=False)
    assert any(doc["doc_id"] == "demo_doc" for doc in all_docs["docs"])

    valid_docs = service.admin_docs(role="admin", valid_only=True)
    assert any(doc["doc_id"] == "russco_valid" for doc in valid_docs["docs"])
    assert all(doc["doc_id"] != "demo_doc" for doc in valid_docs["docs"])
    assert all("is_valid" in doc for doc in valid_docs["docs"])
    assert all("validity_reason" in doc for doc in valid_docs["docs"])
    assert all("official_source" in doc for doc in valid_docs["docs"])


def test_admin_upload_official_guideline_requires_source_page_or_pdf_url(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    with pytest.raises(ValidationError, match="OFFICIAL_SOURCE_URL_REQUIRED"):
        service.admin_upload(
            role="admin",
            filename="asco_gastric_2026.pdf",
            content=b"%PDF-1.4 missing source url",
            metadata={
                "doc_id": "asco_gastric_2026",
                "doc_version": "2026",
                "source_set": "asco",
                "cancer_type": "gastric_cancer",
                "language": "ru",
                "doc_kind": "guideline",
                "source_page_url": "",
                "source_pdf_url": "",
            },
        )


def test_admin_upload_accepts_official_guideline_with_source_page_url_only(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    payload = service.admin_upload(
        role="admin",
        filename="nccn_gastric_2026.pdf",
        content=b"%PDF-1.4 nccn upload",
        metadata={
            "doc_id": "nccn_gastric_2026",
            "doc_version": "2026.1",
            "source_set": "nccn",
            "cancer_type": "gastric_cancer",
            "language": "ru",
            "doc_kind": "guideline",
            "source_page_url": "https://www.nccn.org/guidelines/category_1",
            "source_pdf_url": "",
        },
    )
    assert payload["status"] == "uploaded"
    docs = service.admin_docs(role="admin", valid_only=False, kind="guideline")["docs"]
    uploaded = next(item for item in docs if item.get("doc_id") == "nccn_gastric_2026")
    assert uploaded.get("source_page_url") == "https://www.nccn.org/guidelines/category_1"
    assert uploaded.get("source_pdf_url") == ""


def test_admin_docs_kind_filter_splits_guideline_and_reference(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    _upload_doc(
        service,
        doc_id="russco_2025_1_1_13",
        doc_version="2025",
        source_set="russco",
        source_url="https://rosoncoweb.ru/standarts/RUSSCO/2025/2025-1-1-13.pdf",
    )
    service.admin_upload(
        role="admin",
        filename="2025-mkb10.pdf",
        content=b"%PDF-1.4 mkb10",
        metadata={
            "doc_id": "russco_2025_mkb10",
            "doc_version": "2025",
            "source_set": "russco",
            "cancer_type": "reference_icd10",
            "language": "ru",
            "source_url": "https://www.rosoncoweb.ru/standarts/RUSSCO/2025/2025-mkb10.pdf",
            "doc_kind": "reference",
        },
    )

    guideline_docs = service.admin_docs(role="admin", valid_only=False, kind="guideline")
    assert any(item.get("doc_id") == "russco_2025_1_1_13" for item in guideline_docs["docs"])
    assert all(str(item.get("doc_kind") or "") == "guideline" for item in guideline_docs["docs"])

    references = service.admin_docs(role="admin", valid_only=False, kind="reference")
    assert any(item.get("doc_id") == "russco_2025_mkb10" for item in references["docs"])
    assert all(str(item.get("doc_kind") or "") == "reference" for item in references["docs"])


def test_admin_docs_excludes_demo_decoy_even_if_official_and_approved(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    _upload_doc(
        service,
        doc_id="demo_c16_russco_decoy_2026",
        doc_version="2026.1",
        source_set="russco",
        source_url="https://rosoncoweb.ru/standarts/RUSSCO/2025/2025-1-1-13.pdf",
    )
    service.admin_doc_rechunk(role="admin", doc_id="demo_c16_russco_decoy_2026", doc_version="2026.1")
    service.admin_doc_approve(role="admin", doc_id="demo_c16_russco_decoy_2026", doc_version="2026.1")

    docs = service.admin_docs(role="admin", valid_only=False, kind="guideline")["docs"]
    flagged = next(item for item in docs if item.get("doc_id") == "demo_c16_russco_decoy_2026")
    assert flagged.get("is_valid") is False
    assert flagged.get("validity_reason") == "demo_document_excluded"

    valid_docs = service.admin_docs(role="admin", valid_only=True, kind="guideline")["docs"]
    assert all(item.get("doc_id") != "demo_c16_russco_decoy_2026" for item in valid_docs)
