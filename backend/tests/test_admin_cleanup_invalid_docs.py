from __future__ import annotations

from pathlib import Path

from backend.app.config import Settings
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
    source_set: str,
    source_url: str,
) -> None:
    service.admin_upload(
        role="admin",
        filename=f"{doc_id}.pdf",
        content=f"%PDF-1.4 cleanup test {doc_id}".encode("utf-8"),
        metadata={
            "doc_id": doc_id,
            "doc_version": "v1",
            "source_set": source_set,
            "cancer_type": "gastric_cancer",
            "language": "ru",
            "source_url": source_url,
        },
    )


def test_admin_cleanup_invalid_docs_dry_run_and_apply(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    _upload_doc(
        service,
        doc_id="valid_russco",
        source_set="russco",
        source_url="https://rosoncoweb.ru/standarts/RUSSCO/2025/2025-1-1-12.pdf",
    )
    service.admin_doc_rechunk(role="admin", doc_id="valid_russco", doc_version="v1")
    service.admin_doc_approve(role="admin", doc_id="valid_russco", doc_version="v1")

    _upload_doc(
        service,
        doc_id="demo_invalid",
        source_set="russco",
        source_url="https://example.local/demo.pdf",
    )
    service.admin_doc_rechunk(role="admin", doc_id="demo_invalid", doc_version="v1")
    assert service.store.count_doc_chunks("demo_invalid", "v1") >= 1

    dry_run = service.admin_docs_cleanup_invalid(role="admin", dry_run=True, apply=False)
    candidates = dry_run.get("candidates") if isinstance(dry_run, dict) else []
    assert isinstance(candidates, list)
    assert any(item.get("doc_id") == "demo_invalid" for item in candidates)
    assert dry_run.get("deleted_count") == 0

    applied = service.admin_docs_cleanup_invalid(role="admin", dry_run=False, apply=True)
    assert int(applied.get("deleted_count") or 0) >= 1

    all_docs_after = service.admin_docs(role="admin", valid_only=False)
    assert all(item.get("doc_id") != "demo_invalid" for item in all_docs_after.get("docs", []))
    assert any(item.get("doc_id") == "valid_russco" for item in all_docs_after.get("docs", []))

    events = service.store.list_admin_audit_events(limit=20)
    actions = {str(item.get("action") or "") for item in events}
    assert "cleanup_invalid_dry_run" in actions
    assert "cleanup_invalid_apply" in actions


def test_admin_cleanup_invalid_docs_safe_defaults_keep_manual_review_reasons(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    _upload_doc(
        service,
        doc_id="official_pending",
        source_set="russco",
        source_url="https://rosoncoweb.ru/standarts/RUSSCO/2025/2025-1-1-13.pdf",
    )
    service.admin_doc_rechunk(role="admin", doc_id="official_pending", doc_version="v1")

    _upload_doc(
        service,
        doc_id="non_official_invalid",
        source_set="russco",
        source_url="https://example.local/demo.pdf",
    )
    service.admin_doc_rechunk(role="admin", doc_id="non_official_invalid", doc_version="v1")

    safe_apply = service.admin_docs_cleanup_invalid(role="admin", dry_run=False, apply=True)
    deleted_ids = {str(item.get("doc_id") or "") for item in safe_apply.get("deleted", [])}
    assert "non_official_invalid" in deleted_ids
    assert "official_pending" not in deleted_ids

    docs_after_safe = service.admin_docs(role="admin", valid_only=False, kind="all")
    assert any(item.get("doc_id") == "official_pending" for item in docs_after_safe.get("docs", []))

    allowlisted_apply = service.admin_docs_cleanup_invalid(
        role="admin",
        dry_run=False,
        apply=True,
        reason_allowlist=["status_not_release_ready"],
    )
    allowlisted_deleted = {str(item.get("doc_id") or "") for item in allowlisted_apply.get("deleted", [])}
    assert "official_pending" in allowlisted_deleted
