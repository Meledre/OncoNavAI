from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


_NAMESPACE = uuid.UUID("4c7ca46f-509e-4703-99bb-9ac42f245e06")


@dataclass(frozen=True)
class DocRecord:
    doc_id: str
    doc_version: str
    source_set: str
    cancer_type: str
    language: str
    file_path: str
    sha256: str
    uploaded_at: str


class SQLiteStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS docs (
                    doc_id TEXT NOT NULL,
                    doc_version TEXT NOT NULL,
                    source_set TEXT NOT NULL,
                    cancer_type TEXT NOT NULL,
                    language TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    uploaded_at TEXT NOT NULL,
                    PRIMARY KEY (doc_id, doc_version)
                );

                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL,
                    doc_version TEXT NOT NULL,
                    source_set TEXT NOT NULL,
                    cancer_type TEXT NOT NULL,
                    language TEXT NOT NULL,
                    pdf_page_index INTEGER NOT NULL,
                    page_label TEXT,
                    section_title TEXT,
                    section_path_json TEXT NOT NULL DEFAULT '[]',
                    page_start INTEGER NOT NULL DEFAULT 1,
                    page_end INTEGER NOT NULL DEFAULT 1,
                    token_count INTEGER NOT NULL DEFAULT 0,
                    source_url TEXT NOT NULL DEFAULT '',
                    content_hash TEXT NOT NULL DEFAULT '',
                    text TEXT NOT NULL,
                    vector_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reindex_jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    processed_docs INTEGER NOT NULL DEFAULT 0,
                    total_docs INTEGER NOT NULL DEFAULT 0,
                    finished_at TEXT,
                    error_message TEXT,
                    last_error_code TEXT,
                    ingestion_run_id TEXT
                );

                CREATE TABLE IF NOT EXISTS reports (
                    report_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS guideline_sources (
                    source_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    license_class TEXT NOT NULL,
                    default_enabled INTEGER NOT NULL DEFAULT 1,
                    metadata_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS guideline_documents (
                    document_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    doc_id TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    language TEXT,
                    cancer_type TEXT,
                    file_uri TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    metadata_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS guideline_versions (
                    version_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    doc_id TEXT NOT NULL,
                    doc_version TEXT NOT NULL,
                    file_hash TEXT,
                    status TEXT NOT NULL,
                    effective_from TEXT,
                    effective_to TEXT,
                    metadata_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(doc_id, doc_version)
                );

                CREATE TABLE IF NOT EXISTS disease_registry (
                    disease_id TEXT PRIMARY KEY,
                    disease_name_ru TEXT,
                    disease_name_en TEXT,
                    icd10_codes_json TEXT NOT NULL,
                    common_synonyms_json TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    metadata_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS nosology_routes (
                    route_id TEXT PRIMARY KEY,
                    language TEXT NOT NULL,
                    icd10_prefix TEXT NOT NULL,
                    keyword TEXT NOT NULL,
                    disease_id TEXT NOT NULL,
                    cancer_type TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    doc_id TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 100,
                    active INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_nosology_routes_lang_icd10_active_priority
                    ON nosology_routes (language, icd10_prefix, active, priority);
                CREATE INDEX IF NOT EXISTS idx_nosology_routes_lang_keyword_active_priority
                    ON nosology_routes (language, keyword, active, priority);
                CREATE INDEX IF NOT EXISTS idx_nosology_routes_source_doc_active
                    ON nosology_routes (source_id, doc_id, active);

                CREATE TABLE IF NOT EXISTS ingestion_runs (
                    run_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    processed_docs INTEGER NOT NULL DEFAULT 0,
                    total_docs INTEGER NOT NULL DEFAULT 0,
                    finished_at TEXT,
                    error_message TEXT,
                    last_error_code TEXT,
                    kb_version TEXT,
                    metadata_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS cases (
                    case_id TEXT PRIMARY KEY,
                    schema_version TEXT NOT NULL,
                    import_profile TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS case_import_runs (
                    import_run_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    import_profile TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    confidence REAL,
                    missing_required_fields_json TEXT NOT NULL,
                    warnings_json TEXT NOT NULL,
                    errors_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS session_revocations (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    role TEXT,
                    revoked_at TEXT NOT NULL,
                    expires_at INTEGER,
                    reason TEXT
                );

                CREATE TABLE IF NOT EXISTS session_forced_logout (
                    user_id TEXT PRIMARY KEY,
                    forced_after_epoch INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    actor_user_id TEXT,
                    reason TEXT
                );

                CREATE TABLE IF NOT EXISTS session_audit_events (
                    event_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    event TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    role TEXT,
                    user_id TEXT,
                    session_id TEXT,
                    actor_user_id TEXT,
                    reason TEXT,
                    reason_group TEXT,
                    path TEXT,
                    correlation_id TEXT
                );

                CREATE TABLE IF NOT EXISTS admin_audit_events (
                    event_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    role TEXT NOT NULL,
                    action TEXT NOT NULL,
                    doc_id TEXT,
                    doc_version TEXT,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_admin_audit_created_at
                    ON admin_audit_events (created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_admin_audit_action_created
                    ON admin_audit_events (action, created_at DESC);

                CREATE TABLE IF NOT EXISTS idp_token_replay (
                    jti_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    first_seen_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS icd10_reference (
                    code TEXT PRIMARY KEY,
                    title_ru TEXT NOT NULL,
                    source_doc_id TEXT NOT NULL,
                    source_doc_version TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_icd10_reference_source
                    ON icd10_reference (source_doc_id, source_doc_version);

                CREATE TABLE IF NOT EXISTS drug_dictionary_entries (
                    inn TEXT PRIMARY KEY,
                    ru_names_json TEXT NOT NULL,
                    en_names_json TEXT NOT NULL,
                    group_name TEXT NOT NULL,
                    source_version TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_drug_dictionary_group
                    ON drug_dictionary_entries (group_name);
                CREATE INDEX IF NOT EXISTS idx_drug_dictionary_source_version
                    ON drug_dictionary_entries (source_version);

                CREATE TABLE IF NOT EXISTS drug_regimen_aliases (
                    regimen TEXT PRIMARY KEY,
                    aliases_ru_json TEXT NOT NULL,
                    components_inn_json TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    source_version TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_drug_regimen_source_version
                    ON drug_regimen_aliases (source_version);

                CREATE TABLE IF NOT EXISTS drug_dictionary_versions (
                    version_id TEXT PRIMARY KEY,
                    sha256 TEXT NOT NULL,
                    loaded_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_drug_dictionary_versions_loaded
                    ON drug_dictionary_versions (loaded_at DESC);

                CREATE TABLE IF NOT EXISTS drug_safety_cache (
                    inn TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    contraindications_json TEXT NOT NULL,
                    warnings_json TEXT NOT NULL,
                    interactions_json TEXT NOT NULL,
                    adverse_reactions_json TEXT NOT NULL,
                    source_updated_at TEXT,
                    fetched_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    raw_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error_code TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_drug_safety_cache_expires
                    ON drug_safety_cache (expires_at);
                CREATE INDEX IF NOT EXISTS idx_drug_safety_cache_status
                    ON drug_safety_cache (status);
                """
            )
            self._ensure_reindex_jobs_columns(conn)
            self._ensure_chunks_columns(conn)
            self._ensure_session_audit_events_columns(conn)
            self._ensure_session_audit_events_indexes(conn)
            self._ensure_icd10_reference_table(conn)
            self._ensure_drug_safety_tables(conn)
            conn.commit()

    @staticmethod
    def _ensure_chunks_columns(conn: sqlite3.Connection) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(chunks)").fetchall()}
        if "section_path_json" not in columns:
            conn.execute("ALTER TABLE chunks ADD COLUMN section_path_json TEXT NOT NULL DEFAULT '[]'")
        if "page_start" not in columns:
            conn.execute("ALTER TABLE chunks ADD COLUMN page_start INTEGER NOT NULL DEFAULT 1")
        if "page_end" not in columns:
            conn.execute("ALTER TABLE chunks ADD COLUMN page_end INTEGER NOT NULL DEFAULT 1")
        if "token_count" not in columns:
            conn.execute("ALTER TABLE chunks ADD COLUMN token_count INTEGER NOT NULL DEFAULT 0")
        if "source_url" not in columns:
            conn.execute("ALTER TABLE chunks ADD COLUMN source_url TEXT NOT NULL DEFAULT ''")
        if "content_hash" not in columns:
            conn.execute("ALTER TABLE chunks ADD COLUMN content_hash TEXT NOT NULL DEFAULT ''")

    @staticmethod
    def _ensure_reindex_jobs_columns(conn: sqlite3.Connection) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(reindex_jobs)").fetchall()}
        if "processed_docs" not in columns:
            conn.execute("ALTER TABLE reindex_jobs ADD COLUMN processed_docs INTEGER NOT NULL DEFAULT 0")
        if "total_docs" not in columns:
            conn.execute("ALTER TABLE reindex_jobs ADD COLUMN total_docs INTEGER NOT NULL DEFAULT 0")
        if "last_error_code" not in columns:
            conn.execute("ALTER TABLE reindex_jobs ADD COLUMN last_error_code TEXT")
        if "ingestion_run_id" not in columns:
            conn.execute("ALTER TABLE reindex_jobs ADD COLUMN ingestion_run_id TEXT")

    @staticmethod
    def _ensure_session_audit_events_columns(conn: sqlite3.Connection) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(session_audit_events)").fetchall()}
        if "correlation_id" not in columns:
            conn.execute("ALTER TABLE session_audit_events ADD COLUMN correlation_id TEXT")
        if "reason_group" not in columns:
            conn.execute("ALTER TABLE session_audit_events ADD COLUMN reason_group TEXT")

    @staticmethod
    def _ensure_session_audit_events_indexes(conn: sqlite3.Connection) -> None:
        # Pagination ordering index.
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_session_audit_created_event
            ON session_audit_events (created_at DESC, event_id DESC)
            """
        )
        # Frequent admin filters.
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_session_audit_outcome_created
            ON session_audit_events (outcome, created_at DESC, event_id DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_session_audit_user_created
            ON session_audit_events (user_id, created_at DESC, event_id DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_session_audit_correlation
            ON session_audit_events (correlation_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_session_audit_reason_group_created
            ON session_audit_events (reason_group, created_at DESC, event_id DESC)
            """
        )

    @staticmethod
    def _ensure_icd10_reference_table(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS icd10_reference (
                code TEXT PRIMARY KEY,
                title_ru TEXT NOT NULL,
                source_doc_id TEXT NOT NULL,
                source_doc_version TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_icd10_reference_source
            ON icd10_reference (source_doc_id, source_doc_version)
            """
        )

    @staticmethod
    def _ensure_drug_safety_tables(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS drug_dictionary_entries (
                inn TEXT PRIMARY KEY,
                ru_names_json TEXT NOT NULL,
                en_names_json TEXT NOT NULL,
                group_name TEXT NOT NULL,
                source_version TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_drug_dictionary_group
            ON drug_dictionary_entries (group_name)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_drug_dictionary_source_version
            ON drug_dictionary_entries (source_version)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS drug_regimen_aliases (
                regimen TEXT PRIMARY KEY,
                aliases_ru_json TEXT NOT NULL,
                components_inn_json TEXT NOT NULL,
                notes TEXT NOT NULL,
                source_version TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_drug_regimen_source_version
            ON drug_regimen_aliases (source_version)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS drug_dictionary_versions (
                version_id TEXT PRIMARY KEY,
                sha256 TEXT NOT NULL,
                loaded_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_drug_dictionary_versions_loaded
            ON drug_dictionary_versions (loaded_at DESC)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS drug_safety_cache (
                inn TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                contraindications_json TEXT NOT NULL,
                warnings_json TEXT NOT NULL,
                interactions_json TEXT NOT NULL,
                adverse_reactions_json TEXT NOT NULL,
                source_updated_at TEXT,
                fetched_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                raw_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                error_code TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_drug_safety_cache_expires
            ON drug_safety_cache (expires_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_drug_safety_cache_status
            ON drug_safety_cache (status)
            """
        )

    @staticmethod
    def _stable_uuid(seed: str) -> str:
        return str(uuid.uuid5(_NAMESPACE, seed))

    def upsert_guideline_source(self, source: dict[str, Any], *, updated_at: str | None = None) -> None:
        source_id = str(source.get("source_id") or "").strip().lower()
        if not source_id:
            return
        name = str(source.get("name") or source_id)
        license_class = str(source.get("license_flag") or source.get("license_class") or "PUBLIC")
        default_enabled = bool(source.get("default_enabled", True))
        ts = str(updated_at or source.get("updated_at") or source.get("created_at") or "")
        if not ts:
            ts = "1970-01-01T00:00:00Z"

        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO guideline_sources (source_id, name, license_class, default_enabled, metadata_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    name=excluded.name,
                    license_class=excluded.license_class,
                    default_enabled=excluded.default_enabled,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    source_id,
                    name,
                    license_class,
                    1 if default_enabled else 0,
                    json.dumps(source, ensure_ascii=False),
                    ts,
                ),
            )
            conn.commit()

    def list_guideline_sources(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT source_id, name, license_class, default_enabled, metadata_json, updated_at
                FROM guideline_sources
                ORDER BY source_id ASC
                """
            ).fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                item["default_enabled"] = bool(item["default_enabled"])
                item["metadata"] = json.loads(item.pop("metadata_json"))
                result.append(item)
            return result

    def upsert_disease_registry_entry(self, entry: dict[str, Any]) -> None:
        disease_id = str(entry.get("disease_id") or "").strip()
        if not disease_id:
            return
        updated_at = str(entry.get("updated_at") or entry.get("created_at") or "1970-01-01T00:00:00Z")
        icd10_codes = entry.get("icd10_codes") if isinstance(entry.get("icd10_codes"), list) else []
        synonyms = entry.get("common_synonyms") if isinstance(entry.get("common_synonyms"), list) else []
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO disease_registry (
                    disease_id, disease_name_ru, disease_name_en,
                    icd10_codes_json, common_synonyms_json,
                    active, metadata_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(disease_id) DO UPDATE SET
                    disease_name_ru=excluded.disease_name_ru,
                    disease_name_en=excluded.disease_name_en,
                    icd10_codes_json=excluded.icd10_codes_json,
                    common_synonyms_json=excluded.common_synonyms_json,
                    active=excluded.active,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    disease_id,
                    str(entry.get("disease_name_ru") or ""),
                    str(entry.get("disease_name_en") or ""),
                    json.dumps(icd10_codes, ensure_ascii=False),
                    json.dumps(synonyms, ensure_ascii=False),
                    1 if bool(entry.get("active", True)) else 0,
                    json.dumps(entry, ensure_ascii=False),
                    updated_at,
                ),
            )
            conn.commit()

    def list_disease_registry(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT disease_id, disease_name_ru, disease_name_en,
                       icd10_codes_json, common_synonyms_json,
                       active, metadata_json, updated_at
                FROM disease_registry
                ORDER BY disease_name_ru ASC
                """
            ).fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                item["active"] = bool(item["active"])
                item["icd10_codes"] = json.loads(item.pop("icd10_codes_json"))
                item["common_synonyms"] = json.loads(item.pop("common_synonyms_json"))
                item["metadata"] = json.loads(item.pop("metadata_json"))
                result.append(item)
            return result

    def upsert_nosology_route(self, route: dict[str, Any]) -> None:
        source_id = str(route.get("source_id") or "").strip().lower()
        doc_id = str(route.get("doc_id") or "").strip()
        language = str(route.get("language") or "ru").strip().lower() or "ru"
        icd10_prefix = str(route.get("icd10_prefix") or "*").strip().upper() or "*"
        keyword = str(route.get("keyword") or "*").strip().lower() or "*"
        disease_id = str(route.get("disease_id") or "unknown_disease").strip() or "unknown_disease"
        cancer_type = str(route.get("cancer_type") or "unknown").strip() or "unknown"
        if not source_id or not doc_id:
            return

        route_id = str(route.get("route_id") or "").strip()
        if not route_id:
            route_id = self._stable_uuid(
                f"nosology_route:{language}:{icd10_prefix}:{keyword}:{disease_id}:{cancer_type}:{source_id}:{doc_id}"
            )
        try:
            priority = int(route.get("priority", 100))
        except (TypeError, ValueError):
            priority = 100
        active = 1 if bool(route.get("active", True)) else 0
        updated_at = str(route.get("updated_at") or "1970-01-01T00:00:00Z")

        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO nosology_routes (
                    route_id, language, icd10_prefix, keyword,
                    disease_id, cancer_type, source_id, doc_id,
                    priority, active, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(route_id) DO UPDATE SET
                    language=excluded.language,
                    icd10_prefix=excluded.icd10_prefix,
                    keyword=excluded.keyword,
                    disease_id=excluded.disease_id,
                    cancer_type=excluded.cancer_type,
                    source_id=excluded.source_id,
                    doc_id=excluded.doc_id,
                    priority=excluded.priority,
                    active=excluded.active,
                    updated_at=excluded.updated_at
                """,
                (
                    route_id,
                    language,
                    icd10_prefix,
                    keyword,
                    disease_id,
                    cancer_type,
                    source_id,
                    doc_id,
                    priority,
                    active,
                    updated_at,
                ),
            )
            conn.commit()

    def list_nosology_routes(
        self,
        *,
        language: str | None = None,
        active_only: bool = True,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if language:
            clauses.append("language = ?")
            params.append(str(language).strip().lower())
        if active_only:
            clauses.append("active = 1")
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT route_id, language, icd10_prefix, keyword,
                       disease_id, cancer_type, source_id, doc_id,
                       priority, active, updated_at
                FROM nosology_routes
                {where_sql}
                ORDER BY priority ASC, route_id ASC
                """,
                params,
            ).fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                item["active"] = bool(item["active"])
                result.append(item)
            return result

    def sync_nosology_routes_active_docs(self, *, active_pairs: set[tuple[str, str]]) -> dict[str, int]:
        normalized_pairs = {(str(source).strip().lower(), str(doc).strip()) for source, doc in active_pairs if str(source).strip() and str(doc).strip()}
        with self.connect() as conn:
            rows = conn.execute("SELECT route_id, source_id, doc_id, active FROM nosology_routes").fetchall()
            deactivated = 0
            reactivated = 0
            active = 0
            for row in rows:
                route_id = str(row["route_id"])
                source_id = str(row["source_id"]).strip().lower()
                doc_id = str(row["doc_id"]).strip()
                is_currently_active = bool(row["active"])
                should_be_active = (source_id, doc_id) in normalized_pairs
                if should_be_active:
                    active += 1
                if is_currently_active and not should_be_active:
                    conn.execute("UPDATE nosology_routes SET active = 0 WHERE route_id = ?", (route_id,))
                    deactivated += 1
                elif (not is_currently_active) and should_be_active:
                    conn.execute("UPDATE nosology_routes SET active = 1 WHERE route_id = ?", (route_id,))
                    reactivated += 1
            conn.commit()

        return {
            "total": len(rows),
            "active": active,
            "deactivated": deactivated,
            "reactivated": reactivated,
        }

    def upsert_guideline_document(self, document: dict[str, Any]) -> None:
        document_id = str(document.get("document_id") or "").strip()
        doc_id = str(document.get("doc_id") or "").strip()
        source_id = str(document.get("source_id") or "").strip().lower()
        if not (document_id and doc_id and source_id):
            return
        updated_at = str(document.get("updated_at") or "1970-01-01T00:00:00Z")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO guideline_documents (
                    document_id, source_id, doc_id, title,
                    language, cancer_type, file_uri, is_active,
                    metadata_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    source_id=excluded.source_id,
                    doc_id=excluded.doc_id,
                    title=excluded.title,
                    language=excluded.language,
                    cancer_type=excluded.cancer_type,
                    file_uri=excluded.file_uri,
                    is_active=excluded.is_active,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    document_id,
                    source_id,
                    doc_id,
                    str(document.get("title") or doc_id),
                    str(document.get("language") or ""),
                    str(document.get("cancer_type") or ""),
                    str(document.get("file_uri") or ""),
                    1 if bool(document.get("is_active", True)) else 0,
                    json.dumps(document, ensure_ascii=False),
                    updated_at,
                ),
            )
            conn.commit()

    def list_guideline_documents(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT document_id, source_id, doc_id, title,
                       language, cancer_type, file_uri, is_active,
                       metadata_json, updated_at
                FROM guideline_documents
                ORDER BY updated_at DESC
                """
            ).fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                item["is_active"] = bool(item["is_active"])
                item["metadata"] = json.loads(item.pop("metadata_json"))
                result.append(item)
            return result

    def upsert_guideline_version(self, version: dict[str, Any]) -> None:
        version_id = str(version.get("version_id") or "").strip()
        document_id = str(version.get("document_id") or "").strip()
        doc_id = str(version.get("doc_id") or "").strip()
        doc_version = str(version.get("doc_version") or "").strip()
        if not (version_id and document_id and doc_id and doc_version):
            return
        updated_at = str(version.get("updated_at") or "1970-01-01T00:00:00Z")

        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO guideline_versions (
                    version_id, document_id, doc_id, doc_version,
                    file_hash, status, effective_from, effective_to,
                    metadata_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(doc_id, doc_version) DO UPDATE SET
                    version_id=excluded.version_id,
                    document_id=excluded.document_id,
                    file_hash=excluded.file_hash,
                    status=excluded.status,
                    effective_from=excluded.effective_from,
                    effective_to=excluded.effective_to,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    version_id,
                    document_id,
                    doc_id,
                    doc_version,
                    str(version.get("file_hash") or ""),
                    str(version.get("status") or "active"),
                    str(version.get("effective_from") or ""),
                    str(version.get("effective_to") or ""),
                    json.dumps(version, ensure_ascii=False),
                    updated_at,
                ),
            )
            conn.commit()

    def list_guideline_versions(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT version_id, document_id, doc_id, doc_version,
                       file_hash, status, effective_from, effective_to,
                       metadata_json, updated_at
                FROM guideline_versions
                ORDER BY updated_at DESC
                """
            ).fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                item["metadata"] = json.loads(item.pop("metadata_json"))
                result.append(item)
            return result

    def _sync_governance_for_doc(self, conn: sqlite3.Connection, record: DocRecord) -> None:
        source_id = str(record.source_set).strip().lower()
        document_id = self._stable_uuid(f"document:{record.doc_id}")
        version_id = self._stable_uuid(f"version:{record.doc_id}:{record.doc_version}")

        conn.execute(
            """
            INSERT INTO guideline_sources (source_id, name, license_class, default_enabled, metadata_json, updated_at)
            VALUES (?, ?, 'PUBLIC', 1, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
                name=excluded.name,
                updated_at=excluded.updated_at
            """,
            (
                source_id,
                record.source_set,
                json.dumps({"source_id": source_id, "name": record.source_set}, ensure_ascii=False),
                record.uploaded_at,
            ),
        )

        conn.execute(
            """
            INSERT INTO guideline_documents (
                document_id, source_id, doc_id, title,
                language, cancer_type, file_uri, is_active,
                metadata_json, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(document_id) DO UPDATE SET
                source_id=excluded.source_id,
                doc_id=excluded.doc_id,
                title=excluded.title,
                language=excluded.language,
                cancer_type=excluded.cancer_type,
                file_uri=excluded.file_uri,
                updated_at=excluded.updated_at,
                metadata_json=excluded.metadata_json
            """,
            (
                document_id,
                source_id,
                record.doc_id,
                record.doc_id,
                record.language,
                record.cancer_type,
                record.file_path,
                json.dumps(
                    {
                        "document_id": document_id,
                        "source_id": source_id,
                        "doc_id": record.doc_id,
                        "title": record.doc_id,
                        "language": record.language,
                        "cancer_type": record.cancer_type,
                        "file_uri": record.file_path,
                    },
                    ensure_ascii=False,
                ),
                record.uploaded_at,
            ),
        )

        conn.execute(
            """
            INSERT INTO guideline_versions (
                version_id, document_id, doc_id, doc_version,
                file_hash, status, effective_from, effective_to,
                metadata_json, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 'NEW', '', '', ?, ?)
            ON CONFLICT(doc_id, doc_version) DO UPDATE SET
                version_id=excluded.version_id,
                document_id=excluded.document_id,
                file_hash=excluded.file_hash,
                status=excluded.status,
                metadata_json=excluded.metadata_json,
                updated_at=excluded.updated_at
            """,
            (
                version_id,
                document_id,
                record.doc_id,
                record.doc_version,
                record.sha256,
                json.dumps(
                    {
                        "version_id": version_id,
                        "document_id": document_id,
                        "doc_id": record.doc_id,
                        "doc_version": record.doc_version,
                        "file_hash": record.sha256,
                        "status": "NEW",
                    },
                    ensure_ascii=False,
                ),
                record.uploaded_at,
            ),
        )

    def upsert_doc(self, record: DocRecord) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO docs (doc_id, doc_version, source_set, cancer_type, language, file_path, sha256, uploaded_at)
                VALUES (:doc_id, :doc_version, :source_set, :cancer_type, :language, :file_path, :sha256, :uploaded_at)
                ON CONFLICT(doc_id, doc_version) DO UPDATE SET
                    source_set=excluded.source_set,
                    cancer_type=excluded.cancer_type,
                    language=excluded.language,
                    file_path=excluded.file_path,
                    sha256=excluded.sha256,
                    uploaded_at=excluded.uploaded_at
                """,
                record.__dict__,
            )
            self._sync_governance_for_doc(conn, record)
            conn.commit()

    def list_docs(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT doc_id, doc_version, source_set, cancer_type, language, file_path, sha256, uploaded_at
                FROM docs
                ORDER BY uploaded_at DESC
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def get_doc(self, doc_id: str, doc_version: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT doc_id, doc_version, source_set, cancer_type, language, file_path, sha256, uploaded_at
                FROM docs
                WHERE doc_id = ? AND doc_version = ?
                """,
                (doc_id, doc_version),
            ).fetchone()
            return dict(row) if row else None

    def count_doc_chunks(self, doc_id: str, doc_version: str) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM chunks WHERE doc_id = ? AND doc_version = ?",
                (doc_id, doc_version),
            ).fetchone()
            return int(row["c"]) if row else 0

    def delete_doc_bundle(self, doc_id: str, doc_version: str) -> dict[str, int]:
        with self.connect() as conn:
            chunks_deleted = conn.execute(
                "DELETE FROM chunks WHERE doc_id = ? AND doc_version = ?",
                (doc_id, doc_version),
            ).rowcount
            docs_deleted = conn.execute(
                "DELETE FROM docs WHERE doc_id = ? AND doc_version = ?",
                (doc_id, doc_version),
            ).rowcount
            versions_deleted = conn.execute(
                "DELETE FROM guideline_versions WHERE doc_id = ? AND doc_version = ?",
                (doc_id, doc_version),
            ).rowcount

            remaining_versions_row = conn.execute(
                "SELECT COUNT(*) AS c FROM guideline_versions WHERE doc_id = ?",
                (doc_id,),
            ).fetchone()
            remaining_versions = int(remaining_versions_row["c"]) if remaining_versions_row else 0
            documents_deleted = 0
            routes_deleted = 0
            if remaining_versions == 0:
                documents_deleted = conn.execute(
                    "DELETE FROM guideline_documents WHERE doc_id = ?",
                    (doc_id,),
                ).rowcount
                routes_deleted = conn.execute(
                    "DELETE FROM nosology_routes WHERE doc_id = ?",
                    (doc_id,),
                ).rowcount

            conn.commit()
            return {
                "docs_deleted": int(docs_deleted or 0),
                "chunks_deleted": int(chunks_deleted or 0),
                "versions_deleted": int(versions_deleted or 0),
                "documents_deleted": int(documents_deleted or 0),
                "routes_deleted": int(routes_deleted or 0),
            }

    def get_guideline_version_by_doc(self, doc_id: str, doc_version: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT version_id, document_id, doc_id, doc_version, file_hash, status,
                       effective_from, effective_to, metadata_json, updated_at
                FROM guideline_versions
                WHERE doc_id = ? AND doc_version = ?
                """,
                (doc_id, doc_version),
            ).fetchone()
            if not row:
                return None
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json"))
            return item

    def update_guideline_version_status(
        self,
        *,
        doc_id: str,
        doc_version: str,
        status: str,
        updated_at: str,
        metadata_patch: dict[str, Any] | None = None,
    ) -> None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT metadata_json FROM guideline_versions WHERE doc_id = ? AND doc_version = ?",
                (doc_id, doc_version),
            ).fetchone()
            if not row:
                return
            metadata = json.loads(str(row["metadata_json"]) or "{}")
            metadata["status"] = status
            if metadata_patch:
                metadata.update(metadata_patch)
            conn.execute(
                """
                UPDATE guideline_versions
                SET status = ?, metadata_json = ?, updated_at = ?
                WHERE doc_id = ? AND doc_version = ?
                """,
                (
                    status,
                    json.dumps(metadata, ensure_ascii=False),
                    updated_at,
                    doc_id,
                    doc_version,
                ),
            )
            conn.commit()

    def replace_doc_chunks(self, doc_id: str, doc_version: str, chunks: list[dict[str, Any]]) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM chunks WHERE doc_id = ? AND doc_version = ?", (doc_id, doc_version))
            for chunk in chunks:
                prepared = dict(chunk)
                section_path = prepared.get("section_path")
                if isinstance(section_path, list):
                    prepared["section_path_json"] = json.dumps([str(item) for item in section_path], ensure_ascii=False)
                elif isinstance(section_path, str) and section_path.strip():
                    prepared["section_path_json"] = json.dumps([section_path.strip()], ensure_ascii=False)
                else:
                    prepared["section_path_json"] = "[]"
                text = str(prepared.get("text") or "")
                page_start = int(prepared.get("page_start") or int(prepared.get("pdf_page_index", 0) or 0) + 1)
                page_end = int(prepared.get("page_end") or page_start)
                prepared["page_start"] = page_start
                prepared["page_end"] = page_end
                prepared["token_count"] = int(prepared.get("token_count") or len([item for item in text.split() if item]))
                prepared["source_url"] = str(prepared.get("source_url") or "")
                prepared["content_hash"] = str(prepared.get("content_hash") or hashlib.sha256(text.encode("utf-8")).hexdigest())
                conn.execute(
                    """
                    INSERT INTO chunks (
                        chunk_id, doc_id, doc_version, source_set, cancer_type, language,
                        pdf_page_index, page_label, section_title, section_path_json,
                        page_start, page_end, token_count, source_url, content_hash,
                        text, vector_json, updated_at
                    ) VALUES (
                        :chunk_id, :doc_id, :doc_version, :source_set, :cancer_type, :language,
                        :pdf_page_index, :page_label, :section_title, :section_path_json,
                        :page_start, :page_end, :token_count, :source_url, :content_hash,
                        :text, :vector_json, :updated_at
                    )
                    """,
                    prepared,
                )
            conn.commit()

    def list_chunks(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        clauses = []
        values: list[Any] = []
        for key in ("cancer_type", "language", "source_set", "doc_version", "doc_id"):
            if filters and filters.get(key):
                clauses.append(f"{key} = ?")
                values.append(filters[key])

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = (
            "SELECT chunk_id, doc_id, doc_version, source_set, cancer_type, language, pdf_page_index, "
            "page_label, section_title, section_path_json, page_start, page_end, token_count, source_url, content_hash, "
            "text, vector_json, updated_at FROM chunks "
            f"{where_sql}"
        )

        with self.connect() as conn:
            rows = conn.execute(query, values).fetchall()
            parsed = []
            for row in rows:
                item = dict(row)
                item["vector"] = json.loads(item.pop("vector_json"))
                item["section_path"] = json.loads(item.pop("section_path_json") or "[]")
                parsed.append(item)
            return parsed

    def replace_icd10_reference_entries(
        self,
        *,
        source_doc_id: str,
        source_doc_version: str,
        rows: list[dict[str, Any]],
        updated_at: str,
    ) -> int:
        normalized_source_doc_id = str(source_doc_id or "").strip()
        normalized_source_doc_version = str(source_doc_version or "").strip()
        if not normalized_source_doc_id or not normalized_source_doc_version:
            return 0

        normalized_rows: list[tuple[str, str]] = []
        seen_codes: set[str] = set()
        for item in rows:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code") or "").strip().upper()
            title_ru = str(item.get("title_ru") or "").strip()
            if not code or not title_ru:
                continue
            if code in seen_codes:
                continue
            seen_codes.add(code)
            normalized_rows.append((code, title_ru))

        with self.connect() as conn:
            conn.execute(
                "DELETE FROM icd10_reference WHERE source_doc_id = ? AND source_doc_version = ?",
                (normalized_source_doc_id, normalized_source_doc_version),
            )
            for code, title_ru in normalized_rows:
                conn.execute(
                    """
                    INSERT INTO icd10_reference (code, title_ru, source_doc_id, source_doc_version, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(code) DO UPDATE SET
                        title_ru=excluded.title_ru,
                        source_doc_id=excluded.source_doc_id,
                        source_doc_version=excluded.source_doc_version,
                        updated_at=excluded.updated_at
                    """,
                    (code, title_ru, normalized_source_doc_id, normalized_source_doc_version, updated_at),
                )
            conn.commit()
        return len(normalized_rows)

    def list_icd10_reference(
        self,
        *,
        source_doc_id: str | None = None,
        source_doc_version: str | None = None,
        code_prefix: str | None = None,
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if source_doc_id:
            clauses.append("source_doc_id = ?")
            params.append(str(source_doc_id).strip())
        if source_doc_version:
            clauses.append("source_doc_version = ?")
            params.append(str(source_doc_version).strip())
        if code_prefix:
            clauses.append("code LIKE ?")
            params.append(f"{str(code_prefix).strip().upper()}%")
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        safe_limit = max(1, min(int(limit), 20000))

        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT code, title_ru, source_doc_id, source_doc_version, updated_at
                FROM icd10_reference
                {where_sql}
                ORDER BY code ASC
                LIMIT ?
                """,
                (*params, safe_limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def save_drug_dictionary_version(
        self,
        *,
        version_id: str,
        sha256: str,
        loaded_at: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        normalized_version = str(version_id or "").strip()
        normalized_sha256 = str(sha256 or "").strip().lower()
        if not normalized_version or not normalized_sha256:
            return
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO drug_dictionary_versions (version_id, sha256, loaded_at, metadata_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(version_id) DO UPDATE SET
                    sha256=excluded.sha256,
                    loaded_at=excluded.loaded_at,
                    metadata_json=excluded.metadata_json
                """,
                (
                    normalized_version,
                    normalized_sha256,
                    loaded_at,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
            conn.commit()

    def list_drug_dictionary_versions(self, *, limit: int = 20) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 200))
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT version_id, sha256, loaded_at, metadata_json
                FROM drug_dictionary_versions
                ORDER BY loaded_at DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
            out: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                item["metadata"] = json.loads(str(item.pop("metadata_json") or "{}"))
                out.append(item)
            return out

    def replace_drug_dictionary(
        self,
        *,
        source_version: str,
        entries: list[dict[str, Any]],
        regimens: list[dict[str, Any]],
        updated_at: str,
    ) -> dict[str, int]:
        normalized_source_version = str(source_version or "").strip()
        if not normalized_source_version:
            return {"entries": 0, "regimens": 0}

        normalized_entries: list[dict[str, str]] = []
        seen_inn: set[str] = set()
        for item in entries:
            if not isinstance(item, dict):
                continue
            inn = str(item.get("inn") or "").strip().lower()
            if not inn or inn in seen_inn:
                continue
            seen_inn.add(inn)
            ru_names = [str(name).strip() for name in (item.get("ru_names") if isinstance(item.get("ru_names"), list) else []) if str(name).strip()]
            en_names = [str(name).strip() for name in (item.get("en_names") if isinstance(item.get("en_names"), list) else []) if str(name).strip()]
            group_name = str(item.get("group") or "").strip().lower() or "other"
            normalized_entries.append(
                {
                    "inn": inn,
                    "ru_names_json": json.dumps(sorted(set(ru_names)), ensure_ascii=False),
                    "en_names_json": json.dumps(sorted(set(en_names)), ensure_ascii=False),
                    "group_name": group_name,
                    "source_version": normalized_source_version,
                    "updated_at": updated_at,
                }
            )

        normalized_regimens: list[dict[str, str]] = []
        seen_regimens: set[str] = set()
        for item in regimens:
            if not isinstance(item, dict):
                continue
            regimen = str(item.get("regimen") or "").strip().upper()
            if not regimen or regimen in seen_regimens:
                continue
            seen_regimens.add(regimen)
            aliases = [str(alias).strip() for alias in (item.get("aliases_ru") if isinstance(item.get("aliases_ru"), list) else []) if str(alias).strip()]
            components = [str(inn).strip().lower() for inn in (item.get("components_inn") if isinstance(item.get("components_inn"), list) else []) if str(inn).strip()]
            notes = str(item.get("notes") or "").strip()
            normalized_regimens.append(
                {
                    "regimen": regimen,
                    "aliases_ru_json": json.dumps(sorted(set(aliases)), ensure_ascii=False),
                    "components_inn_json": json.dumps(sorted(set(components)), ensure_ascii=False),
                    "notes": notes,
                    "source_version": normalized_source_version,
                    "updated_at": updated_at,
                }
            )

        with self.connect() as conn:
            conn.execute("DELETE FROM drug_dictionary_entries WHERE source_version = ?", (normalized_source_version,))
            conn.execute("DELETE FROM drug_regimen_aliases WHERE source_version = ?", (normalized_source_version,))
            for item in normalized_entries:
                conn.execute(
                    """
                    INSERT INTO drug_dictionary_entries (inn, ru_names_json, en_names_json, group_name, source_version, updated_at)
                    VALUES (:inn, :ru_names_json, :en_names_json, :group_name, :source_version, :updated_at)
                    ON CONFLICT(inn) DO UPDATE SET
                        ru_names_json=excluded.ru_names_json,
                        en_names_json=excluded.en_names_json,
                        group_name=excluded.group_name,
                        source_version=excluded.source_version,
                        updated_at=excluded.updated_at
                    """,
                    item,
                )
            for item in normalized_regimens:
                conn.execute(
                    """
                    INSERT INTO drug_regimen_aliases (regimen, aliases_ru_json, components_inn_json, notes, source_version, updated_at)
                    VALUES (:regimen, :aliases_ru_json, :components_inn_json, :notes, :source_version, :updated_at)
                    ON CONFLICT(regimen) DO UPDATE SET
                        aliases_ru_json=excluded.aliases_ru_json,
                        components_inn_json=excluded.components_inn_json,
                        notes=excluded.notes,
                        source_version=excluded.source_version,
                        updated_at=excluded.updated_at
                    """,
                    item,
                )
            conn.commit()
        return {"entries": len(normalized_entries), "regimens": len(normalized_regimens)}

    def list_drug_dictionary_entries(self, *, source_version: str | None = None, limit: int = 5000) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if source_version:
            clauses.append("source_version = ?")
            params.append(str(source_version).strip())
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        safe_limit = max(1, min(int(limit), 50000))
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT inn, ru_names_json, en_names_json, group_name, source_version, updated_at
                FROM drug_dictionary_entries
                {where_sql}
                ORDER BY inn ASC
                LIMIT ?
                """,
                (*params, safe_limit),
            ).fetchall()
            out: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                item["ru_names"] = json.loads(str(item.pop("ru_names_json") or "[]"))
                item["en_names"] = json.loads(str(item.pop("en_names_json") or "[]"))
                out.append(item)
            return out

    def list_drug_regimen_aliases(self, *, source_version: str | None = None, limit: int = 5000) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if source_version:
            clauses.append("source_version = ?")
            params.append(str(source_version).strip())
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        safe_limit = max(1, min(int(limit), 50000))
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT regimen, aliases_ru_json, components_inn_json, notes, source_version, updated_at
                FROM drug_regimen_aliases
                {where_sql}
                ORDER BY regimen ASC
                LIMIT ?
                """,
                (*params, safe_limit),
            ).fetchall()
            out: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                item["aliases_ru"] = json.loads(str(item.pop("aliases_ru_json") or "[]"))
                item["components_inn"] = json.loads(str(item.pop("components_inn_json") or "[]"))
                out.append(item)
            return out

    def get_drug_safety_cache(self, inn: str) -> dict[str, Any] | None:
        normalized_inn = str(inn or "").strip().lower()
        if not normalized_inn:
            return None
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT inn, source, contraindications_json, warnings_json, interactions_json, adverse_reactions_json,
                       source_updated_at, fetched_at, expires_at, raw_hash, status, error_code
                FROM drug_safety_cache
                WHERE inn = ?
                """,
                (normalized_inn,),
            ).fetchone()
            if not row:
                return None
            item = dict(row)
            item["contraindications"] = json.loads(str(item.pop("contraindications_json") or "[]"))
            item["warnings"] = json.loads(str(item.pop("warnings_json") or "[]"))
            item["interactions"] = json.loads(str(item.pop("interactions_json") or "[]"))
            item["adverse_reactions"] = json.loads(str(item.pop("adverse_reactions_json") or "[]"))
            return item

    def upsert_drug_safety_cache(self, payload: dict[str, Any]) -> None:
        inn = str(payload.get("inn") or "").strip().lower()
        if not inn:
            return
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO drug_safety_cache (
                    inn, source, contraindications_json, warnings_json, interactions_json, adverse_reactions_json,
                    source_updated_at, fetched_at, expires_at, raw_hash, status, error_code
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(inn) DO UPDATE SET
                    source=excluded.source,
                    contraindications_json=excluded.contraindications_json,
                    warnings_json=excluded.warnings_json,
                    interactions_json=excluded.interactions_json,
                    adverse_reactions_json=excluded.adverse_reactions_json,
                    source_updated_at=excluded.source_updated_at,
                    fetched_at=excluded.fetched_at,
                    expires_at=excluded.expires_at,
                    raw_hash=excluded.raw_hash,
                    status=excluded.status,
                    error_code=excluded.error_code
                """,
                (
                    inn,
                    str(payload.get("source") or ""),
                    json.dumps(payload.get("contraindications") if isinstance(payload.get("contraindications"), list) else [], ensure_ascii=False),
                    json.dumps(payload.get("warnings") if isinstance(payload.get("warnings"), list) else [], ensure_ascii=False),
                    json.dumps(payload.get("interactions") if isinstance(payload.get("interactions"), list) else [], ensure_ascii=False),
                    json.dumps(payload.get("adverse_reactions") if isinstance(payload.get("adverse_reactions"), list) else [], ensure_ascii=False),
                    str(payload.get("source_updated_at") or ""),
                    str(payload.get("fetched_at") or ""),
                    str(payload.get("expires_at") or ""),
                    str(payload.get("raw_hash") or ""),
                    str(payload.get("status") or ""),
                    str(payload.get("error_code") or ""),
                ),
            )
            conn.commit()

    def list_drug_safety_cache(self, *, limit: int = 500) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 5000))
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT inn, source, contraindications_json, warnings_json, interactions_json, adverse_reactions_json,
                       source_updated_at, fetched_at, expires_at, raw_hash, status, error_code
                FROM drug_safety_cache
                ORDER BY fetched_at DESC, inn ASC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
            out: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                item["contraindications"] = json.loads(str(item.pop("contraindications_json") or "[]"))
                item["warnings"] = json.loads(str(item.pop("warnings_json") or "[]"))
                item["interactions"] = json.loads(str(item.pop("interactions_json") or "[]"))
                item["adverse_reactions"] = json.loads(str(item.pop("adverse_reactions_json") or "[]"))
                out.append(item)
            return out

    def create_ingestion_run(self, started_at: str, total_docs: int = 0, metadata: dict[str, Any] | None = None) -> str:
        run_id = str(uuid.uuid4())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO ingestion_runs (run_id, status, started_at, processed_docs, total_docs, metadata_json)
                VALUES (?, 'running', ?, 0, ?, ?)
                """,
                (run_id, started_at, total_docs, json.dumps(metadata or {}, ensure_ascii=False)),
            )
            conn.commit()
        return run_id

    def update_ingestion_run_progress(self, run_id: str, processed_docs: int, total_docs: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE ingestion_runs SET processed_docs = ?, total_docs = ? WHERE run_id = ?",
                (processed_docs, total_docs, run_id),
            )
            conn.commit()

    def finish_ingestion_run(
        self,
        run_id: str,
        finished_at: str,
        *,
        kb_version: str | None = None,
        error_message: str | None = None,
        error_code: str | None = None,
        processed_docs: int | None = None,
        total_docs: int | None = None,
    ) -> None:
        status = "failed" if error_message else "done"
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE ingestion_runs
                SET status = ?, finished_at = ?, kb_version = ?,
                    error_message = ?, last_error_code = ?,
                    processed_docs = COALESCE(?, processed_docs),
                    total_docs = COALESCE(?, total_docs)
                WHERE run_id = ?
                """,
                (status, finished_at, kb_version, error_message, error_code, processed_docs, total_docs, run_id),
            )
            conn.commit()

    def get_ingestion_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT run_id, status, started_at, processed_docs, total_docs,
                       finished_at, error_message, last_error_code, kb_version, metadata_json
                FROM ingestion_runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if not row:
                return None
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json"))
            return item

    def list_ingestion_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 200))
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT run_id, status, started_at, processed_docs, total_docs,
                       finished_at, error_message, last_error_code, kb_version, metadata_json
                FROM ingestion_runs
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                item["metadata"] = json.loads(item.pop("metadata_json"))
                result.append(item)
            return result

    def create_reindex_job(self, started_at: str, total_docs: int = 0) -> str:
        job_id = str(uuid.uuid4())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO reindex_jobs (job_id, status, started_at, processed_docs, total_docs, last_error_code, ingestion_run_id)
                VALUES (?, 'running', ?, 0, ?, NULL, NULL)
                """,
                (job_id, started_at, total_docs),
            )
            conn.commit()
        return job_id

    def attach_ingestion_run_to_reindex(self, job_id: str, run_id: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE reindex_jobs SET ingestion_run_id = ? WHERE job_id = ?", (run_id, job_id))
            conn.commit()

    def update_reindex_job_progress(self, job_id: str, processed_docs: int, total_docs: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE reindex_jobs SET processed_docs = ?, total_docs = ? WHERE job_id = ?",
                (processed_docs, total_docs, job_id),
            )
            conn.commit()

    def finish_reindex_job(
        self,
        job_id: str,
        finished_at: str,
        error_message: str | None = None,
        error_code: str | None = None,
        processed_docs: int | None = None,
        total_docs: int | None = None,
    ) -> None:
        status = "failed" if error_message else "done"
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE reindex_jobs
                SET status = ?, finished_at = ?, error_message = ?, last_error_code = ?,
                    processed_docs = COALESCE(?, processed_docs),
                    total_docs = COALESCE(?, total_docs)
                WHERE job_id = ?
                """,
                (status, finished_at, error_message, error_code, processed_docs, total_docs, job_id),
            )
            conn.commit()

    def get_reindex_job(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    job_id, status, started_at, processed_docs, total_docs,
                    finished_at, error_message, last_error_code, ingestion_run_id
                FROM reindex_jobs
                WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
            return dict(row) if row else None

    def save_report(self, report_id: str, payload: dict[str, Any], created_at: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO reports (report_id, payload_json, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(report_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    created_at = excluded.created_at
                """,
                (report_id, json.dumps(payload, ensure_ascii=False), created_at),
            )
            conn.commit()

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM reports WHERE report_id = ?",
                (report_id,),
            ).fetchone()
            if not row:
                return None
            return json.loads(row["payload_json"])

    def upsert_case(self, case_payload: dict[str, Any]) -> str:
        case_id = str(case_payload.get("case_id") or "").strip()
        if not case_id:
            case_id = str(uuid.uuid4())
            case_payload = {**case_payload, "case_id": case_id}

        schema_version = str(case_payload.get("schema_version") or "1.0")
        import_profile = str(case_payload.get("import_profile") or "FREE_TEXT")
        created_at = str(case_payload.get("created_at") or case_payload.get("updated_at") or "1970-01-01T00:00:00Z")
        updated_at = str(case_payload.get("updated_at") or created_at)

        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO cases (case_id, schema_version, import_profile, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(case_id) DO UPDATE SET
                    schema_version=excluded.schema_version,
                    import_profile=excluded.import_profile,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (
                    case_id,
                    schema_version,
                    import_profile,
                    json.dumps(case_payload, ensure_ascii=False),
                    created_at,
                    updated_at,
                ),
            )
            conn.commit()
        return case_id

    def get_case(self, case_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM cases WHERE case_id = ?",
                (case_id,),
            ).fetchone()
            if not row:
                return None
            return json.loads(row["payload_json"])

    def save_case_import_run(self, run_payload: dict[str, Any]) -> None:
        import_run_id = str(run_payload.get("import_run_id") or "").strip()
        if not import_run_id:
            return
        missing_required_fields = run_payload.get("missing_required_fields")
        warnings = run_payload.get("warnings")
        errors = run_payload.get("errors")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO case_import_runs (
                    import_run_id, case_id, import_profile, started_at, finished_at,
                    status, confidence, missing_required_fields_json, warnings_json, errors_json, payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(import_run_id) DO UPDATE SET
                    case_id=excluded.case_id,
                    import_profile=excluded.import_profile,
                    started_at=excluded.started_at,
                    finished_at=excluded.finished_at,
                    status=excluded.status,
                    confidence=excluded.confidence,
                    missing_required_fields_json=excluded.missing_required_fields_json,
                    warnings_json=excluded.warnings_json,
                    errors_json=excluded.errors_json,
                    payload_json=excluded.payload_json
                """,
                (
                    import_run_id,
                    str(run_payload.get("case_id") or ""),
                    str(run_payload.get("import_profile") or ""),
                    str(run_payload.get("started_at") or ""),
                    str(run_payload.get("finished_at") or ""),
                    str(run_payload.get("status") or "FAILED"),
                    float(run_payload.get("confidence", 0.0)),
                    json.dumps(missing_required_fields if isinstance(missing_required_fields, list) else [], ensure_ascii=False),
                    json.dumps(warnings if isinstance(warnings, list) else [], ensure_ascii=False),
                    json.dumps(errors if isinstance(errors, list) else [], ensure_ascii=False),
                    json.dumps(run_payload, ensure_ascii=False),
                ),
            )
            conn.commit()

    def get_case_import_run(self, import_run_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM case_import_runs WHERE import_run_id = ?",
                (import_run_id,),
            ).fetchone()
            if not row:
                return None
            return json.loads(row["payload_json"])

    def list_case_import_runs(self, *, limit: int = 20) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 100))
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT payload_json
                FROM case_import_runs
                ORDER BY started_at DESC, import_run_id DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
            return [json.loads(row["payload_json"]) for row in rows]

    def revoke_session(
        self,
        *,
        session_id: str,
        user_id: str,
        role: str | None = None,
        revoked_at: str,
        expires_at: int | None = None,
        reason: str | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO session_revocations (session_id, user_id, role, revoked_at, expires_at, reason)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    user_id=excluded.user_id,
                    role=excluded.role,
                    revoked_at=excluded.revoked_at,
                    expires_at=excluded.expires_at,
                    reason=excluded.reason
                """,
                (
                    session_id,
                    user_id,
                    role or "",
                    revoked_at,
                    expires_at,
                    reason or "",
                ),
            )
            conn.commit()

    def purge_expired_session_revocations(self, *, now_epoch_sec: int) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                DELETE FROM session_revocations
                WHERE expires_at IS NOT NULL AND expires_at > 0 AND expires_at <= ?
                """,
                (int(now_epoch_sec),),
            )
            conn.commit()
            return int(cursor.rowcount or 0)

    def is_session_revoked(self, session_id: str, *, now_epoch_sec: int) -> bool:
        self.purge_expired_session_revocations(now_epoch_sec=now_epoch_sec)
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM session_revocations WHERE session_id = ? LIMIT 1",
                (session_id,),
            ).fetchone()
            return bool(row)

    def list_revoked_session_ids(self, *, limit: int = 50, now_epoch_sec: int) -> list[str]:
        safe_limit = max(1, min(int(limit), 500))
        self.purge_expired_session_revocations(now_epoch_sec=now_epoch_sec)
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT session_id
                FROM session_revocations
                ORDER BY revoked_at DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
            return [str(row["session_id"]) for row in rows]

    def force_logout_user(
        self,
        *,
        user_id: str,
        forced_after_epoch: int,
        updated_at: str,
        actor_user_id: str | None = None,
        reason: str | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO session_forced_logout (user_id, forced_after_epoch, updated_at, actor_user_id, reason)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    forced_after_epoch=excluded.forced_after_epoch,
                    updated_at=excluded.updated_at,
                    actor_user_id=excluded.actor_user_id,
                    reason=excluded.reason
                """,
                (
                    user_id,
                    int(forced_after_epoch),
                    updated_at,
                    actor_user_id or "",
                    reason or "",
                ),
            )
            conn.commit()

    def get_forced_logout_after(self, user_id: str) -> int | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT forced_after_epoch FROM session_forced_logout WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if not row:
                return None
            value = row["forced_after_epoch"]
            return int(value) if value is not None else None

    def save_session_audit_event(self, payload: dict[str, Any], *, created_at: str) -> str:
        event_id = str(payload.get("event_id") or uuid.uuid4())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO session_audit_events (
                    event_id, created_at, event, outcome, role, user_id, session_id, actor_user_id, reason, reason_group, path, correlation_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    created_at=excluded.created_at,
                    event=excluded.event,
                    outcome=excluded.outcome,
                    role=excluded.role,
                    user_id=excluded.user_id,
                    session_id=excluded.session_id,
                    actor_user_id=excluded.actor_user_id,
                    reason=excluded.reason,
                    reason_group=excluded.reason_group,
                    path=excluded.path,
                    correlation_id=excluded.correlation_id
                """,
                (
                    event_id,
                    created_at,
                    str(payload.get("event") or "unknown"),
                    str(payload.get("outcome") or "info"),
                    str(payload.get("role") or ""),
                    str(payload.get("user_id") or ""),
                    str(payload.get("session_id") or ""),
                    str(payload.get("actor_user_id") or ""),
                    str(payload.get("reason") or ""),
                    str(payload.get("reason_group") or ""),
                    str(payload.get("path") or ""),
                    str(payload.get("correlation_id") or ""),
                ),
            )
            conn.commit()
        return event_id

    def list_session_audit_events(
        self,
        *,
        limit: int = 50,
        filters: dict[str, str] | None = None,
        cursor_created_at: str = "",
        cursor_event_id: str = "",
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 500))
        raw_filters = filters or {}
        clauses: list[str] = []
        params: list[Any] = []

        outcome = str(raw_filters.get("outcome") or "").strip().lower()
        if outcome in {"allow", "deny", "info", "error"}:
            clauses.append("outcome = ?")
            params.append(outcome)

        for key in ("event", "correlation_id", "user_id"):
            value = str(raw_filters.get(key) or "").strip()
            if not value:
                continue
            clauses.append(f"{key} = ?")
            params.append(value)

        reason = str(raw_filters.get("reason") or "").strip()
        if reason:
            clauses.append("reason LIKE ?")
            params.append(f"%{reason}%")
        reason_group = str(raw_filters.get("reason_group") or "").strip()
        if reason_group:
            clauses.append("reason_group = ?")
            params.append(reason_group)

        from_ts = str(raw_filters.get("from_ts") or "").strip()
        if from_ts:
            clauses.append("created_at >= ?")
            params.append(from_ts)

        to_ts = str(raw_filters.get("to_ts") or "").strip()
        if to_ts:
            clauses.append("created_at <= ?")
            params.append(to_ts)

        if cursor_created_at and cursor_event_id:
            clauses.append("(created_at < ? OR (created_at = ? AND event_id < ?))")
            params.extend([cursor_created_at, cursor_created_at, cursor_event_id])

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as conn:
            query = f"""
                SELECT event_id, created_at, event, outcome, role, user_id, session_id, actor_user_id, reason, reason_group, path, correlation_id
                FROM session_audit_events
                {where_sql}
                ORDER BY created_at DESC, event_id DESC
                LIMIT ?
            """
            rows = conn.execute(query, (*params, safe_limit)).fetchall()
            return [dict(row) for row in rows]

    def session_audit_summary(
        self,
        *,
        from_ts: str = "",
        to_ts: str = "",
        top_limit: int = 10,
    ) -> dict[str, Any]:
        safe_top = max(1, min(int(top_limit), 50))
        clauses: list[str] = []
        params: list[Any] = []
        if from_ts:
            clauses.append("created_at >= ?")
            params.append(str(from_ts))
        if to_ts:
            clauses.append("created_at <= ?")
            params.append(str(to_ts))
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        with self.connect() as conn:
            total_row = conn.execute(
                f"SELECT COUNT(*) AS c FROM session_audit_events {where_sql}",
                tuple(params),
            ).fetchone()
            total_events = int(total_row["c"] if total_row else 0)

            users_row = conn.execute(
                f"""
                SELECT COUNT(DISTINCT user_id) AS c
                FROM session_audit_events
                {where_sql if where_sql else "WHERE 1=1"} {"AND" if where_sql else ""} user_id <> ''
                """,
                tuple(params),
            ).fetchone()
            unique_users = int(users_row["c"] if users_row else 0)

            outcome_rows = conn.execute(
                f"""
                SELECT outcome, COUNT(*) AS c
                FROM session_audit_events
                {where_sql}
                GROUP BY outcome
                """,
                tuple(params),
            ).fetchall()
            outcome_counts = {str(row["outcome"] or ""): int(row["c"] or 0) for row in outcome_rows}

            reason_group_rows = conn.execute(
                f"""
                SELECT reason_group, COUNT(*) AS c
                FROM session_audit_events
                {where_sql}
                GROUP BY reason_group
                """,
                tuple(params),
            ).fetchall()
            reason_group_counts = {str(row["reason_group"] or ""): int(row["c"] or 0) for row in reason_group_rows}

            top_reason_rows = conn.execute(
                f"""
                SELECT reason, COUNT(*) AS c
                FROM session_audit_events
                {where_sql if where_sql else "WHERE 1=1"} {"AND" if where_sql else ""} reason <> ''
                GROUP BY reason
                ORDER BY c DESC, reason ASC
                LIMIT ?
                """,
                (*params, safe_top),
            ).fetchall()
            top_reasons = [{"reason": str(row["reason"] or ""), "count": int(row["c"] or 0)} for row in top_reason_rows]

            top_event_rows = conn.execute(
                f"""
                SELECT event, COUNT(*) AS c
                FROM session_audit_events
                {where_sql}
                GROUP BY event
                ORDER BY c DESC, event ASC
                LIMIT ?
                """,
                (*params, safe_top),
            ).fetchall()
            top_events = [{"event": str(row["event"] or ""), "count": int(row["c"] or 0)} for row in top_event_rows]

        return {
            "total_events": total_events,
            "unique_users": unique_users,
            "outcome_counts": outcome_counts,
            "reason_group_counts": reason_group_counts,
            "top_reasons": top_reasons,
            "top_events": top_events,
        }

    def session_audit_reason_counts(
        self,
        *,
        reasons: list[str],
        from_ts: str = "",
        to_ts: str = "",
    ) -> dict[str, int]:
        normalized_reasons = sorted({str(item or "").strip() for item in reasons if str(item or "").strip()})
        if not normalized_reasons:
            return {}

        clauses = [f"reason IN ({','.join('?' for _ in normalized_reasons)})"]
        params: list[Any] = list(normalized_reasons)
        if from_ts:
            clauses.append("created_at >= ?")
            params.append(str(from_ts))
        if to_ts:
            clauses.append("created_at <= ?")
            params.append(str(to_ts))
        where_sql = f"WHERE {' AND '.join(clauses)}"

        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT reason, COUNT(*) AS c
                FROM session_audit_events
                {where_sql}
                GROUP BY reason
                """,
                tuple(params),
            ).fetchall()
        return {str(row["reason"] or ""): int(row["c"] or 0) for row in rows}

    def purge_session_audit_before(self, *, created_before: str) -> int:
        cutoff = str(created_before or "").strip()
        if not cutoff:
            return 0
        with self.connect() as conn:
            cursor = conn.execute(
                """
                DELETE FROM session_audit_events
                WHERE created_at < ?
                """,
                (cutoff,),
            )
            conn.commit()
            return int(cursor.rowcount or 0)

    def save_admin_audit_event(self, payload: dict[str, Any], *, created_at: str) -> str:
        event_id = str(uuid.uuid4())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO admin_audit_events (
                    event_id, created_at, role, action, doc_id, doc_version, payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    created_at,
                    str(payload.get("role") or ""),
                    str(payload.get("action") or ""),
                    str(payload.get("doc_id") or "") or None,
                    str(payload.get("doc_version") or "") or None,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            conn.commit()
        return event_id

    def list_admin_audit_events(self, *, limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 1000))
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT event_id, created_at, role, action, doc_id, doc_version, payload_json
                FROM admin_audit_events
                ORDER BY created_at DESC, event_id DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
            events: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                item["payload"] = json.loads(item.pop("payload_json") or "{}")
                events.append(item)
            return events

    def purge_expired_idp_token_replay(self, *, now_epoch_sec: int | None = None) -> int:
        now = int(now_epoch_sec) if now_epoch_sec is not None else int(time.time())
        with self.connect() as conn:
            cursor = conn.execute(
                """
                DELETE FROM idp_token_replay
                WHERE expires_at <= ?
                """,
                (now,),
            )
            conn.commit()
            return int(cursor.rowcount or 0)

    def reserve_idp_token_jti(
        self,
        *,
        jti_hash: str,
        user_id: str,
        first_seen_epoch: int | None = None,
        expires_at: int,
        now_epoch_sec: int | None = None,
    ) -> bool:
        now = int(now_epoch_sec) if now_epoch_sec is not None else int(time.time())
        if int(expires_at) <= now:
            return False
        self.purge_expired_idp_token_replay(now_epoch_sec=now)
        first_seen = int(first_seen_epoch) if first_seen_epoch is not None else now
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO idp_token_replay (jti_hash, user_id, first_seen_at, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    jti_hash,
                    user_id,
                    first_seen,
                    int(expires_at),
                ),
            )
            conn.commit()
            return int(cursor.rowcount or 0) > 0
