from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.config import Settings
from backend.app.exceptions import NotFoundError, ValidationError
from backend.app.guidelines.sync_russco import RusscoDocument
from backend.app.service import OncoService


def make_settings(
    root: Path,
    *,
    structural_chunker_enabled: bool = True,
) -> Settings:
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
        oncoai_structural_chunker_enabled=structural_chunker_enabled,
    )


def test_reindex_job_and_status(tmp_path):
    service = OncoService(make_settings(tmp_path))
    service.admin_upload(
        role="admin",
        filename="guide.pdf",
        content=b"synthetic guideline",
        metadata={
            "doc_id": "g1",
            "doc_version": "v1",
            "source_set": "s1",
            "cancer_type": "nsclc_egfr",
            "language": "ru",
        },
    )

    result = service.admin_reindex(role="admin")
    assert result["status"] == "done"
    assert isinstance(result.get("ingestion_run_id"), str)
    assert result["ingestion_run_id"]

    status = service.admin_reindex_status(role="admin", job_id=result["job_id"])
    assert status["status"] == "done"
    assert status["kb_version"].startswith("kb_")
    assert status["processed_docs"] == 1
    assert status["total_docs"] == 1
    assert status["last_error_code"] is None
    assert status.get("ingestion_run_id") == result["ingestion_run_id"]
    assert isinstance(status.get("ingestion_run"), dict)
    assert status["ingestion_run"]["status"] == "done"
    assert status["ingestion_run"]["processed_docs"] == 1
    assert status["ingestion_run"]["total_docs"] == 1


def test_reindex_requires_uploaded_docs(tmp_path):
    service = OncoService(make_settings(tmp_path))
    with pytest.raises(ValidationError):
        service.admin_reindex(role="admin")


def test_admin_doc_pdf_stream_returns_binary_content(tmp_path):
    service = OncoService(make_settings(tmp_path))
    uploaded = service.admin_upload(
        role="admin",
        filename="guide.pdf",
        content=b"%PDF-1.4 synthetic test file",
        metadata={
            "doc_id": "g1",
            "doc_version": "v1",
            "source_set": "s1",
            "cancer_type": "nsclc_egfr",
            "language": "ru",
        },
    )
    assert uploaded["status"] == "uploaded"

    payload, filename = service.admin_doc_pdf(role="clinician", doc_id="g1", doc_version="v1")
    assert payload.startswith(b"%PDF-1.4")
    assert filename.endswith(".pdf")


def test_admin_doc_pdf_stream_raises_when_document_missing(tmp_path):
    service = OncoService(make_settings(tmp_path))
    with pytest.raises(NotFoundError):
        service.admin_doc_pdf(role="admin", doc_id="missing", doc_version="v0")


def test_admin_doc_index_requires_approval_status(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    service.admin_upload(
        role="admin",
        filename="guide.pdf",
        content=b"%PDF-1.4 approval gating",
        metadata={
            "doc_id": "g2",
            "doc_version": "v2",
            "source_set": "s1",
            "cancer_type": "gastric_cancer",
            "language": "ru",
        },
    )
    rechunked = service.admin_doc_rechunk(role="admin", doc_id="g2", doc_version="v2")
    assert rechunked["status"] == "PENDING_APPROVAL"
    assert rechunked.get("intermediate_status") == "CHUNKED"

    version_after_rechunk = service.store.get_guideline_version_by_doc("g2", "v2")
    assert isinstance(version_after_rechunk, dict)
    metadata = version_after_rechunk.get("metadata") if isinstance(version_after_rechunk, dict) else {}
    history = metadata.get("status_history") if isinstance(metadata, dict) else []
    assert isinstance(history, list)
    assert history == ["NEW", "CHUNKED", "PENDING_APPROVAL"]

    with pytest.raises(ValidationError, match="INDEX_REQUIRES_APPROVAL"):
        service.admin_doc_index(role="admin", doc_id="g2", doc_version="v2")

    service.admin_doc_approve(role="admin", doc_id="g2", doc_version="v2")
    indexed = service.admin_doc_index(role="admin", doc_id="g2", doc_version="v2")
    assert indexed["status"] == "INDEXED"
    assert int(indexed["chunk_count"]) >= 1


def test_admin_doc_approve_requires_rechunk_status(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    service.admin_upload(
        role="admin",
        filename="guide.pdf",
        content=b"%PDF-1.4 approve gating",
        metadata={
            "doc_id": "g2-approve",
            "doc_version": "v1",
            "source_set": "s1",
            "cancer_type": "gastric_cancer",
            "language": "ru",
        },
    )

    with pytest.raises(ValidationError, match="APPROVE_REQUIRES_RECHUNK"):
        service.admin_doc_approve(role="admin", doc_id="g2-approve", doc_version="v1")

    service.admin_doc_rechunk(role="admin", doc_id="g2-approve", doc_version="v1")
    approved = service.admin_doc_approve(role="admin", doc_id="g2-approve", doc_version="v1")
    assert approved["status"] == "APPROVED"
    assert approved.get("previous_status") == "PENDING_APPROVAL"


def test_admin_sync_russco_creates_pending_approval_docs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = OncoService(make_settings(tmp_path))

    fake_doc = RusscoDocument(
        url="https://rosoncoweb.ru/standarts/RUSSCO/2025/2025-1-1-13.pdf",
        filename="2025-1-1-13.pdf",
        doc_id="russco_2025_1_1_13",
        doc_version="2025",
    )
    monkeypatch.setattr("backend.app.service.discover_russco_2025_documents", lambda: [fake_doc])
    monkeypatch.setattr("backend.app.service.download_russco_pdf", lambda _url: b"%PDF-1.4 russco")

    payload = service.admin_sync_russco(role="admin")
    assert payload["source"] == "russco"
    assert payload["count"] == 1
    assert payload["synced"][0]["status"] == "PENDING_APPROVAL"
    assert payload["errors"] == []

    docs_payload = service.admin_docs(role="admin")
    matched = [doc for doc in docs_payload["docs"] if doc["doc_id"] == "russco_2025_1_1_13"]
    assert len(matched) == 1
    assert matched[0]["status"] == "PENDING_APPROVAL"
    assert str(matched[0]["source_url"]).endswith("2025-1-1-13.pdf")

    version = service.store.get_guideline_version_by_doc("russco_2025_1_1_13", "2025")
    assert isinstance(version, dict)
    metadata = version.get("metadata") if isinstance(version, dict) else {}
    history = metadata.get("status_history") if isinstance(metadata, dict) else []
    assert isinstance(history, list)
    assert history == ["NEW", "CHUNKED", "PENDING_APPROVAL"]
    routes = [item for item in service.store.list_nosology_routes(active_only=False) if item.get("doc_id") == "russco_2025_1_1_13"]
    assert routes
    assert any(str(item.get("icd10_prefix") or "") == "C16" for item in routes)


def test_admin_sync_minzdrav_writes_page_and_pdf_urls_without_manual_placeholder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = OncoService(make_settings(tmp_path))

    monkeypatch.setattr(
        "backend.app.service.download_minzdrav_pdf_with_url",
        lambda _item, **_kwargs: (b"%PDF-1.4 minzdrav", "https://cr.minzdrav.gov.ru/upload/iblock/test.pdf"),
    )

    payload = service.admin_sync_minzdrav(role="admin")
    assert payload["source"] == "minzdrav"
    assert int(payload["count"]) >= 1
    assert "manual_fallback" not in payload

    docs_payload = service.admin_docs(role="admin")
    manual = [doc for doc in docs_payload["docs"] if doc["doc_id"] == "minzdrav_manual_url_required"]
    assert manual == []
    synced_ids = {str(item.get("doc_id") or "") for item in payload.get("synced", [])}
    assert "minzdrav_237_6" in synced_ids
    synced = next(item for item in payload["synced"] if item["doc_id"] == "minzdrav_237_6")
    assert str(synced.get("source_page_url") or "").startswith("https://cr.minzdrav.gov.ru/preview-cr/")
    assert str(synced.get("source_pdf_url") or "").endswith(".pdf")
    routes = [item for item in service.store.list_nosology_routes(active_only=False) if str(item.get("doc_id") or "") == "minzdrav_237_6"]
    assert routes
    assert any(str(item.get("icd10_prefix") or "") == "C16" for item in routes)


def test_admin_sync_minzdrav_reports_non_pdf_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = OncoService(make_settings(tmp_path))

    def _raise_non_pdf(_item: object) -> bytes:
        raise ValueError("MINZDRAV_NON_PDF_CONTENT:https://cr.minzdrav.gov.ru/preview-cr/237_6")

    monkeypatch.setattr("backend.app.service.download_minzdrav_pdf_with_url", lambda _item, **_kwargs: _raise_non_pdf(_item))
    payload = service.admin_sync_minzdrav(role="admin")

    assert payload["source"] == "minzdrav"
    assert payload["status"] == "partial"
    assert payload["errors"]
    assert all(item.get("error_code") == "MINZDRAV_NON_PDF_CONTENT" for item in payload["errors"])


def test_admin_doc_actions_are_written_to_admin_audit(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    service.admin_upload(
        role="admin",
        filename="guide.pdf",
        content=b"%PDF-1.4 audit",
        metadata={
            "doc_id": "g3",
            "doc_version": "v3",
            "source_set": "s1",
            "cancer_type": "gastric_cancer",
            "language": "ru",
        },
    )
    service.admin_doc_rechunk(role="admin", doc_id="g3", doc_version="v3")
    service.admin_doc_approve(role="admin", doc_id="g3", doc_version="v3")
    service.admin_doc_index(role="admin", doc_id="g3", doc_version="v3")

    events = service.store.list_admin_audit_events(limit=20)
    actions = {str(item.get("action") or "").lower() for item in events}
    assert {"upload", "rechunk", "approve", "index"}.issubset(actions)


def test_admin_reindex_respects_structural_chunker_feature_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = OncoService(make_settings(tmp_path, structural_chunker_enabled=False))
    service.admin_upload(
        role="admin",
        filename="guide.pdf",
        content=b"%PDF-1.4 structural flag check",
        metadata={
            "doc_id": "g-flag",
            "doc_version": "v1",
            "source_set": "s1",
            "cancer_type": "nsclc_egfr",
            "language": "ru",
        },
    )

    from backend.app.rag.ingest_pdf import extract_pdf_chunks as real_extract_pdf_chunks

    observed_flags: list[bool] = []

    def fake_extract_pdf_chunks(path: Path, metadata: dict[str, str], *, structural_chunker_enabled: bool = True):
        observed_flags.append(bool(structural_chunker_enabled))
        return real_extract_pdf_chunks(path, metadata, structural_chunker_enabled=structural_chunker_enabled)

    monkeypatch.setattr("backend.app.service.extract_pdf_chunks", fake_extract_pdf_chunks)

    result = service.admin_reindex(role="admin")
    assert result["status"] == "done"
    assert observed_flags
    assert all(flag is False for flag in observed_flags)
