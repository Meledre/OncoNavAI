from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from backend.app.routing.nosology_router import resolve_nosology_route
from backend.app.storage import DocRecord, SQLiteStore


def _store(tmp_path: Path) -> SQLiteStore:
    db_path = tmp_path / "data" / "oncoai.sqlite3"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return SQLiteStore(db_path)


def _seed_release_doc(
    store: SQLiteStore,
    tmp_path: Path,
    *,
    doc_id: str,
    doc_version: str,
    source_set: str,
    cancer_type: str,
) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    path = docs_dir / f"{doc_id}_{doc_version}.pdf"
    path.write_bytes(b"%PDF-1.4 seeded")
    store.upsert_doc(
        DocRecord(
            doc_id=doc_id,
            doc_version=doc_version,
            source_set=source_set,
            cancer_type=cancer_type,
            language="ru",
            file_path=str(path),
            sha256=f"sha256:{doc_id}:{doc_version}",
            uploaded_at="2026-02-20T09:59:00Z",
        )
    )
    source_url = (
        f"https://cr.minzdrav.gov.ru/preview-cr/{doc_id}"
        if source_set == "minzdrav"
        else f"https://rosoncoweb.ru/standarts/RUSSCO/2025/{doc_id}.pdf"
    )
    store.update_guideline_version_status(
        doc_id=doc_id,
        doc_version=doc_version,
        status="INDEXED",
        updated_at=datetime.now(timezone.utc).isoformat(),
        metadata_patch={"source_url": source_url, "doc_kind": "guideline"},
    )


def test_router_uses_icd10_prefix_match_first(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _seed_release_doc(
        store,
        tmp_path,
        doc_id="minzdrav_574_1",
        doc_version="2020",
        source_set="minzdrav",
        cancer_type="gastric_cancer",
    )
    _seed_release_doc(
        store,
        tmp_path,
        doc_id="russco_2023_22",
        doc_version="2025",
        source_set="russco",
        cancer_type="gastric_cancer",
    )
    store.upsert_nosology_route(
        {
            "route_id": "route-c16-minzdrav",
            "language": "ru",
            "icd10_prefix": "C16",
            "keyword": "*",
            "disease_id": "disease-gastric",
            "cancer_type": "gastric_cancer",
            "source_id": "minzdrav",
            "doc_id": "minzdrav_574_1",
            "priority": 10,
            "active": 1,
            "updated_at": "2026-02-20T10:00:00Z",
        }
    )
    store.upsert_nosology_route(
        {
            "route_id": "route-c16-russco",
            "language": "ru",
            "icd10_prefix": "C16",
            "keyword": "*",
            "disease_id": "disease-gastric",
            "cancer_type": "gastric_cancer",
            "source_id": "russco",
            "doc_id": "russco_2023_22",
            "priority": 20,
            "active": 1,
            "updated_at": "2026-02-20T10:00:01Z",
        }
    )

    decision = resolve_nosology_route(
        store=store,
        case_payload={
            "cancer_type": "unknown",
            "diagnosis": {"icd10": "C16.9"},
            "notes": "Аденокарцинома желудка, 1 линия mFOLFOX6",
        },
        language="ru",
        requested_source_ids=[],
    )

    assert decision.match_strategy == "icd10_prefix"
    assert decision.resolved_disease_id == "disease-gastric"
    assert decision.resolved_cancer_type == "gastric_cancer"
    assert decision.source_ids == ["minzdrav", "russco"]
    assert decision.doc_ids == ["minzdrav_574_1", "russco_2023_22"]


def test_router_uses_keyword_when_icd10_is_missing(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _seed_release_doc(
        store,
        tmp_path,
        doc_id="lung_doc",
        doc_version="2025",
        source_set="minzdrav",
        cancer_type="nsclc_egfr",
    )
    store.upsert_nosology_route(
        {
            "route_id": "route-keyword",
            "language": "ru",
            "icd10_prefix": "*",
            "keyword": "рак легкого",
            "disease_id": "disease-lung",
            "cancer_type": "nsclc_egfr",
            "source_id": "minzdrav",
            "doc_id": "lung_doc",
            "priority": 5,
            "active": 1,
            "updated_at": "2026-02-20T10:00:00Z",
        }
    )

    decision = resolve_nosology_route(
        store=store,
        case_payload={
            "cancer_type": "unknown",
            "diagnosis": {"icd10": ""},
            "notes": "Подтвержден немелкоклеточный рак легкого, требуется план лечения",
        },
        language="ru",
        requested_source_ids=[],
    )

    assert decision.match_strategy == "keyword"
    assert decision.resolved_disease_id == "disease-lung"
    assert decision.resolved_cancer_type == "nsclc_egfr"
    assert decision.source_ids == ["minzdrav"]
    assert decision.doc_ids == ["lung_doc"]


def test_router_manual_source_override_has_priority(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _seed_release_doc(
        store,
        tmp_path,
        doc_id="breast_mz",
        doc_version="2025",
        source_set="minzdrav",
        cancer_type="breast_hr+/her2-",
    )
    _seed_release_doc(
        store,
        tmp_path,
        doc_id="breast_rs",
        doc_version="2025",
        source_set="russco",
        cancer_type="breast_hr+/her2-",
    )
    store.upsert_nosology_route(
        {
            "route_id": "route-c50-minzdrav",
            "language": "ru",
            "icd10_prefix": "C50",
            "keyword": "*",
            "disease_id": "disease-breast",
            "cancer_type": "breast_hr+/her2-",
            "source_id": "minzdrav",
            "doc_id": "breast_mz",
            "priority": 10,
            "active": 1,
            "updated_at": "2026-02-20T10:00:00Z",
        }
    )
    store.upsert_nosology_route(
        {
            "route_id": "route-c50-russco",
            "language": "ru",
            "icd10_prefix": "C50",
            "keyword": "*",
            "disease_id": "disease-breast",
            "cancer_type": "breast_hr+/her2-",
            "source_id": "russco",
            "doc_id": "breast_rs",
            "priority": 20,
            "active": 1,
            "updated_at": "2026-02-20T10:00:01Z",
        }
    )

    decision = resolve_nosology_route(
        store=store,
        case_payload={
            "cancer_type": "breast_hr+/her2-",
            "diagnosis": {"icd10": "C50.9"},
            "notes": "HR+ HER2-",
        },
        language="ru",
        requested_source_ids=["russco"],
    )

    assert decision.match_strategy == "manual_source_override"
    assert decision.source_ids == ["russco"]
    assert decision.doc_ids == ["breast_rs"]


def test_router_falls_back_to_cancer_type_docs(tmp_path: Path) -> None:
    store = _store(tmp_path)
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    doc_path = docs_dir / "nsclc.pdf"
    doc_path.write_bytes(b"%PDF-1.4 nsclc guideline")
    store.upsert_doc(
        DocRecord(
            doc_id="guideline_nsclc",
            doc_version="2025-11",
            source_set="minzdrav",
            cancer_type="nsclc_egfr",
            language="ru",
            file_path=str(doc_path),
            sha256="sha256:test",
            uploaded_at="2026-02-20T10:00:00Z",
        )
    )
    store.update_guideline_version_status(
        doc_id="guideline_nsclc",
        doc_version="2025-11",
        status="INDEXED",
        updated_at=datetime.now(timezone.utc).isoformat(),
        metadata_patch={
            "source_url": "https://cr.minzdrav.gov.ru/preview-cr/574_1",
            "doc_kind": "guideline",
        },
    )

    decision = resolve_nosology_route(
        store=store,
        case_payload={
            "cancer_type": "nsclc_egfr",
            "diagnosis": {"icd10": ""},
            "notes": "Синтетический кейс без ICD",
        },
        language="ru",
        requested_source_ids=[],
    )

    assert decision.match_strategy == "cancer_type_fallback"
    assert decision.resolved_cancer_type == "nsclc_egfr"
    assert decision.source_ids == ["minzdrav"]
    assert decision.doc_ids == ["guideline_nsclc"]


def test_router_excludes_official_pending_docs_from_routes(tmp_path: Path) -> None:
    store = _store(tmp_path)
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    doc_path = docs_dir / "gastric.pdf"
    doc_path.write_bytes(b"%PDF-1.4 gastric guideline")
    store.upsert_doc(
        DocRecord(
            doc_id="russco_2025_1_1_13",
            doc_version="2025",
            source_set="russco",
            cancer_type="gastric_cancer",
            language="ru",
            file_path=str(doc_path),
            sha256="sha256:test-russco",
            uploaded_at="2026-02-20T10:00:00Z",
        )
    )
    store.update_guideline_version_status(
        doc_id="russco_2025_1_1_13",
        doc_version="2025",
        status="PENDING_APPROVAL",
        updated_at=datetime.now(timezone.utc).isoformat(),
        metadata_patch={
            "source_url": "https://rosoncoweb.ru/standarts/RUSSCO/2025/2025-1-1-13.pdf",
            "doc_kind": "guideline",
        },
    )
    store.upsert_nosology_route(
        {
            "route_id": "route-c16-russco-pending",
            "language": "ru",
            "icd10_prefix": "C16",
            "keyword": "*",
            "disease_id": "disease-gastric",
            "cancer_type": "gastric_cancer",
            "source_id": "russco",
            "doc_id": "russco_2025_1_1_13",
            "priority": 10,
            "active": 1,
            "updated_at": "2026-02-20T10:00:01Z",
        }
    )

    decision = resolve_nosology_route(
        store=store,
        case_payload={
            "cancer_type": "unknown",
            "diagnosis": {"icd10": "C16.0"},
            "notes": "Аденокарцинома желудка, требуется подбор следующей линии",
        },
        language="ru",
        requested_source_ids=["russco"],
    )

    assert decision.doc_ids == []
    assert decision.source_ids == []


def test_router_derives_generic_cancer_type_for_other_c_prefixes(tmp_path: Path) -> None:
    store = _store(tmp_path)
    decision = resolve_nosology_route(
        store=store,
        case_payload={
            "cancer_type": "unknown",
            "diagnosis": {"icd10": "C18.9"},
            "notes": "Синтетический CRC кейс без загруженных роутов",
        },
        language="ru",
        requested_source_ids=[],
    )
    assert decision.resolved_cancer_type == "oncology_c18"


def test_router_appends_supportive_and_general_docs_to_nosology_route(tmp_path: Path) -> None:
    store = _store(tmp_path)
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    gastric_path = docs_dir / "gastric.pdf"
    supportive_path = docs_dir / "supportive.pdf"
    gastric_path.write_bytes(b"%PDF-1.4 gastric")
    supportive_path.write_bytes(b"%PDF-1.4 supportive")

    store.upsert_doc(
        DocRecord(
            doc_id="minzdrav_574_1",
            doc_version="2020",
            source_set="minzdrav",
            cancer_type="gastric_cancer",
            language="ru",
            file_path=str(gastric_path),
            sha256="sha256:g",
            uploaded_at="2026-02-20T10:00:00Z",
        )
    )
    store.upsert_doc(
        DocRecord(
            doc_id="minzdrav_supportive_1",
            doc_version="2025",
            source_set="minzdrav",
            cancer_type="supportive_care",
            language="ru",
            file_path=str(supportive_path),
            sha256="sha256:s",
            uploaded_at="2026-02-20T10:00:01Z",
        )
    )
    now = datetime.now(timezone.utc).isoformat()
    store.update_guideline_version_status(
        doc_id="minzdrav_574_1",
        doc_version="2020",
        status="INDEXED",
        updated_at=now,
        metadata_patch={"source_url": "https://cr.minzdrav.gov.ru/preview-cr/574_1", "doc_kind": "guideline"},
    )
    store.update_guideline_version_status(
        doc_id="minzdrav_supportive_1",
        doc_version="2025",
        status="INDEXED",
        updated_at=now,
        metadata_patch={"source_url": "https://cr.minzdrav.gov.ru/preview-cr/supportive_1", "doc_kind": "guideline"},
    )
    store.upsert_nosology_route(
        {
            "route_id": "route-c16-main",
            "language": "ru",
            "icd10_prefix": "C16",
            "keyword": "*",
            "disease_id": "disease-gastric",
            "cancer_type": "gastric_cancer",
            "source_id": "minzdrav",
            "doc_id": "minzdrav_574_1",
            "priority": 10,
            "active": 1,
            "updated_at": "2026-02-20T10:00:02Z",
        }
    )

    decision = resolve_nosology_route(
        store=store,
        case_payload={
            "cancer_type": "unknown",
            "diagnosis": {"icd10": "C16.9"},
            "notes": "рак желудка",
        },
        language="ru",
        requested_source_ids=["minzdrav"],
    )
    assert "minzdrav_574_1" in decision.doc_ids
    assert "minzdrav_supportive_1" in decision.doc_ids


def test_router_drops_official_route_rows_without_doc_registry_pair(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert_nosology_route(
        {
            "route_id": "route-c16-russco-legacy-only",
            "language": "ru",
            "icd10_prefix": "C16",
            "keyword": "*",
            "disease_id": "disease-gastric",
            "cancer_type": "gastric_cancer",
            "source_id": "russco",
            "doc_id": "russco_orphan_route",
            "priority": 10,
            "active": 1,
            "updated_at": "2026-02-20T10:00:02Z",
        }
    )

    decision = resolve_nosology_route(
        store=store,
        case_payload={
            "cancer_type": "unknown",
            "diagnosis": {"icd10": "C16.9"},
            "notes": "рак желудка",
        },
        language="ru",
        requested_source_ids=["russco"],
    )
    assert decision.doc_ids == []
    assert decision.source_ids == []


def test_router_unknown_case_falls_back_to_general_oncology(tmp_path: Path) -> None:
    store = _store(tmp_path)
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    generic_path = docs_dir / "general.pdf"
    generic_path.write_bytes(b"%PDF-1.4 general oncology")
    store.upsert_doc(
        DocRecord(
            doc_id="minzdrav_general_1",
            doc_version="2026",
            source_set="minzdrav",
            cancer_type="general_oncology",
            language="ru",
            file_path=str(generic_path),
            sha256="sha256:general",
            uploaded_at="2026-02-20T10:00:00Z",
        )
    )
    store.update_guideline_version_status(
        doc_id="minzdrav_general_1",
        doc_version="2026",
        status="INDEXED",
        updated_at=datetime.now(timezone.utc).isoformat(),
        metadata_patch={"source_url": "https://cr.minzdrav.gov.ru/preview-cr/general_1", "doc_kind": "guideline"},
    )

    decision = resolve_nosology_route(
        store=store,
        case_payload={
            "cancer_type": "unknown",
            "diagnosis": {"icd10": ""},
            "notes": "Кейс без явной нозологии",
        },
        language="ru",
        requested_source_ids=[],
    )
    assert decision.resolved_cancer_type == "general_oncology"
    assert decision.doc_ids == ["minzdrav_general_1"]


def test_router_normalizes_pdq_alias_in_requested_sources(tmp_path: Path) -> None:
    store = _store(tmp_path)
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    pdq_path = docs_dir / "pdq.pdf"
    pdq_path.write_bytes(b"%PDF-1.4 pdq")
    store.upsert_doc(
        DocRecord(
            doc_id="nci_pdq_gastric_2026",
            doc_version="2026",
            source_set="nci_pdq",
            cancer_type="general_oncology",
            language="ru",
            file_path=str(pdq_path),
            sha256="sha256:pdq",
            uploaded_at="2026-02-20T10:00:00Z",
        )
    )
    store.update_guideline_version_status(
        doc_id="nci_pdq_gastric_2026",
        doc_version="2026",
        status="INDEXED",
        updated_at=datetime.now(timezone.utc).isoformat(),
        metadata_patch={"source_url": "https://www.cancer.gov/publications/pdq", "doc_kind": "guideline"},
    )

    decision = resolve_nosology_route(
        store=store,
        case_payload={
            "cancer_type": "unknown",
            "diagnosis": {"icd10": ""},
            "notes": "generic",
        },
        language="ru",
        requested_source_ids=["pdq"],
    )
    assert decision.source_ids == ["nci_pdq"]
    assert decision.doc_ids == ["nci_pdq_gastric_2026"]


def test_router_resolves_c79_3_to_cns_metastases_scope(tmp_path: Path) -> None:
    store = _store(tmp_path)
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    cns_path = docs_dir / "cns_mets.pdf"
    cns_path.write_bytes(b"%PDF-1.4 cns mets")
    store.upsert_doc(
        DocRecord(
            doc_id="minzdrav_c79_3_1",
            doc_version="2026",
            source_set="minzdrav",
            cancer_type="cns_metastases_c79_3",
            language="ru",
            file_path=str(cns_path),
            sha256="sha256:c79.3",
            uploaded_at="2026-02-20T10:00:00Z",
        )
    )
    store.update_guideline_version_status(
        doc_id="minzdrav_c79_3_1",
        doc_version="2026",
        status="INDEXED",
        updated_at=datetime.now(timezone.utc).isoformat(),
        metadata_patch={"source_url": "https://cr.minzdrav.gov.ru/preview-cr/c79_3_1", "doc_kind": "guideline"},
    )
    store.upsert_nosology_route(
        {
            "route_id": "route-c79-3-main",
            "language": "ru",
            "icd10_prefix": "C79.3",
            "keyword": "*",
            "disease_id": "disease-c79-3",
            "cancer_type": "cns_metastases_c79_3",
            "source_id": "minzdrav",
            "doc_id": "minzdrav_c79_3_1",
            "priority": 10,
            "active": 1,
            "updated_at": "2026-02-20T10:00:00Z",
        }
    )

    decision = resolve_nosology_route(
        store=store,
        case_payload={
            "cancer_type": "unknown",
            "diagnosis": {"icd10": "C79.3"},
            "notes": "метастазы в головной мозг",
        },
        language="ru",
        requested_source_ids=[],
    )
    assert decision.match_strategy == "icd10_prefix"
    assert decision.resolved_cancer_type == "cns_metastases_c79_3"
    assert decision.doc_ids == ["minzdrav_c79_3_1"]


def test_router_legacy_brain_without_icd10_returns_ambiguous_scope(tmp_path: Path) -> None:
    store = _store(tmp_path)
    decision = resolve_nosology_route(
        store=store,
        case_payload={
            "cancer_type": "brain",
            "diagnosis": {"icd10": ""},
            "notes": "опухоль головного мозга без уточнения C71/C79.3",
        },
        language="ru",
        requested_source_ids=[],
    )
    assert decision.match_strategy == "ambiguous_brain_scope"
    assert decision.doc_ids == []
    assert decision.source_ids == []


def test_router_caps_icd10_docs_per_source_via_env(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    _seed_release_doc(
        store,
        tmp_path,
        doc_id="minzdrav_574_1",
        doc_version="2020",
        source_set="minzdrav",
        cancer_type="gastric_cancer",
    )
    _seed_release_doc(
        store,
        tmp_path,
        doc_id="minzdrav_237_6",
        doc_version="2025",
        source_set="minzdrav",
        cancer_type="gastric_cancer",
    )
    _seed_release_doc(
        store,
        tmp_path,
        doc_id="russco_2023_22",
        doc_version="2025",
        source_set="russco",
        cancer_type="gastric_cancer",
    )

    store.upsert_nosology_route(
        {
            "route_id": "route-c16-mz-1",
            "language": "ru",
            "icd10_prefix": "C16",
            "keyword": "*",
            "disease_id": "disease-gastric",
            "cancer_type": "gastric_cancer",
            "source_id": "minzdrav",
            "doc_id": "minzdrav_574_1",
            "priority": 10,
            "active": 1,
            "updated_at": "2026-02-20T10:00:00Z",
        }
    )
    store.upsert_nosology_route(
        {
            "route_id": "route-c16-mz-2",
            "language": "ru",
            "icd10_prefix": "C16",
            "keyword": "*",
            "disease_id": "disease-gastric",
            "cancer_type": "gastric_cancer",
            "source_id": "minzdrav",
            "doc_id": "minzdrav_237_6",
            "priority": 20,
            "active": 1,
            "updated_at": "2026-02-20T10:00:01Z",
        }
    )
    store.upsert_nosology_route(
        {
            "route_id": "route-c16-rs-1",
            "language": "ru",
            "icd10_prefix": "C16",
            "keyword": "*",
            "disease_id": "disease-gastric",
            "cancer_type": "gastric_cancer",
            "source_id": "russco",
            "doc_id": "russco_2023_22",
            "priority": 30,
            "active": 1,
            "updated_at": "2026-02-20T10:00:02Z",
        }
    )

    monkeypatch.setenv("ONCOAI_ROUTER_MAX_ICD10_DOCS_PER_SOURCE", "1")
    decision = resolve_nosology_route(
        store=store,
        case_payload={
            "cancer_type": "unknown",
            "diagnosis": {"icd10": "C16.9"},
            "notes": "рак желудка",
        },
        language="ru",
        requested_source_ids=[],
    )

    assert decision.match_strategy == "icd10_prefix"
    assert decision.source_ids == ["minzdrav", "russco"]
    assert decision.doc_ids == ["minzdrav_574_1", "russco_2023_22"]


def test_router_caps_support_docs_per_source_via_env(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    main_path = docs_dir / "main.pdf"
    support1_path = docs_dir / "support1.pdf"
    support2_path = docs_dir / "support2.pdf"
    main_path.write_bytes(b"%PDF-1.4 main")
    support1_path.write_bytes(b"%PDF-1.4 support1")
    support2_path.write_bytes(b"%PDF-1.4 support2")

    store.upsert_doc(
        DocRecord(
            doc_id="minzdrav_574_1",
            doc_version="2020",
            source_set="minzdrav",
            cancer_type="gastric_cancer",
            language="ru",
            file_path=str(main_path),
            sha256="sha256:main",
            uploaded_at="2026-02-20T10:00:00Z",
        )
    )
    store.upsert_doc(
        DocRecord(
            doc_id="minzdrav_supportive_1",
            doc_version="2025",
            source_set="minzdrav",
            cancer_type="supportive_care",
            language="ru",
            file_path=str(support1_path),
            sha256="sha256:s1",
            uploaded_at="2026-02-20T10:00:01Z",
        )
    )
    store.upsert_doc(
        DocRecord(
            doc_id="minzdrav_supportive_2",
            doc_version="2026",
            source_set="minzdrav",
            cancer_type="general_oncology",
            language="ru",
            file_path=str(support2_path),
            sha256="sha256:s2",
            uploaded_at="2026-02-20T10:00:02Z",
        )
    )
    now = datetime.now(timezone.utc).isoformat()
    store.update_guideline_version_status(
        doc_id="minzdrav_574_1",
        doc_version="2020",
        status="INDEXED",
        updated_at=now,
        metadata_patch={"source_url": "https://cr.minzdrav.gov.ru/preview-cr/574_1", "doc_kind": "guideline"},
    )
    store.update_guideline_version_status(
        doc_id="minzdrav_supportive_1",
        doc_version="2025",
        status="INDEXED",
        updated_at=now,
        metadata_patch={"source_url": "https://cr.minzdrav.gov.ru/preview-cr/supportive_1", "doc_kind": "guideline"},
    )
    store.update_guideline_version_status(
        doc_id="minzdrav_supportive_2",
        doc_version="2026",
        status="INDEXED",
        updated_at=now,
        metadata_patch={"source_url": "https://cr.minzdrav.gov.ru/preview-cr/supportive_2", "doc_kind": "guideline"},
    )
    store.upsert_nosology_route(
        {
            "route_id": "route-c16-main",
            "language": "ru",
            "icd10_prefix": "C16",
            "keyword": "*",
            "disease_id": "disease-gastric",
            "cancer_type": "gastric_cancer",
            "source_id": "minzdrav",
            "doc_id": "minzdrav_574_1",
            "priority": 10,
            "active": 1,
            "updated_at": "2026-02-20T10:00:00Z",
        }
    )

    monkeypatch.setenv("ONCOAI_ROUTER_MAX_SUPPORT_DOCS_PER_SOURCE", "1")
    decision = resolve_nosology_route(
        store=store,
        case_payload={
            "cancer_type": "unknown",
            "diagnosis": {"icd10": "C16.9"},
            "notes": "рак желудка",
        },
        language="ru",
        requested_source_ids=["minzdrav"],
    )

    support_ids = [doc_id for doc_id in decision.doc_ids if "supportive" in doc_id]
    assert "minzdrav_574_1" in decision.doc_ids
    assert len(support_ids) == 1
