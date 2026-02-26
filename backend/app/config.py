from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    project_root: Path
    data_dir: Path
    docs_dir: Path
    reports_dir: Path
    db_path: Path
    local_core_base_url: str
    demo_token: str
    rate_limit_per_minute: int
    llm_primary_url: str
    llm_primary_model: str
    llm_primary_api_key: str
    llm_fallback_url: str
    llm_fallback_model: str
    llm_fallback_api_key: str
    release_profile: str = "compat"
    reasoning_mode: str = "llm_rag_only"
    prompt_registry_dir: Path = Path("docs/prompts")
    vector_backend: str = "local"
    qdrant_url: str = ""
    qdrant_collection: str = "oncoai_chunks"
    retrieval_top_k: int = 12
    rerank_top_n: int = 6
    embedding_backend: str = "hash"
    embedding_url: str = ""
    embedding_model: str = ""
    embedding_api_key: str = ""
    reranker_backend: str = "lexical"
    rag_engine: str = "basic"
    llm_generation_enabled: bool = False
    llm_probe_enabled: bool = False
    session_audit_retention_days: int = 90
    session_audit_alert_min_events: int = 10
    session_audit_alert_deny_rate_warn: float = 0.35
    session_audit_alert_deny_rate_critical: float = 0.60
    session_audit_alert_error_count_warn: int = 5
    session_audit_alert_error_count_critical: int = 20
    session_audit_alert_replay_count_warn: int = 1
    session_audit_alert_replay_count_critical: int = 3
    session_audit_alert_config_error_count_warn: int = 1
    session_audit_alert_config_error_count_critical: int = 3
    case_import_allow_full_mode: bool = False
    case_import_full_require_ack: bool = True
    case_import_deid_redact_pii: bool = True
    oncoai_doctor_schema_v1_2_enabled: bool = True
    oncoai_structural_chunker_enabled: bool = True
    oncoai_guideline_sync_enabled: bool = True
    oncoai_casefacts_enabled: bool = True
    oncoai_prompt_schema_strict: bool = False
    oncoai_compat_v1_1_projection_enabled: bool = True
    oncoai_drug_safety_enabled: bool = True
    drug_safety_cache_ttl_hours: int = 24 * 14
    drug_safety_request_timeout_sec: int = 12
    drug_safety_openfda_base_url: str = "https://api.fda.gov"


_ALLOWED_RELEASE_PROFILES = {"compat", "strict_full"}
_ALLOWED_REASONING_MODES = {"compat", "llm_rag_only"}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip()
    return value if value else default


def normalize_release_profile(value: str) -> str:
    token = str(value or "").strip().lower()
    return token if token in _ALLOWED_RELEASE_PROFILES else "compat"


def is_strict_release_profile(value: str) -> bool:
    return normalize_release_profile(value) == "strict_full"


def normalize_reasoning_mode(value: str) -> str:
    token = str(value or "").strip().lower()
    return token if token in _ALLOWED_REASONING_MODES else "llm_rag_only"


def _env_float(name: str, default: float, min_value: float, max_value: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        parsed = float(raw.strip())
    except ValueError:
        return default
    return max(min_value, min(parsed, max_value))


def load_settings() -> Settings:
    project_root = Path(__file__).resolve().parents[2]
    data_dir = Path(_env_str("ONCOAI_DATA_DIR", str(project_root / "data")))
    docs_dir = data_dir / "docs"
    reports_dir = data_dir / "reports"
    db_path = Path(_env_str("ONCOAI_DB_PATH", str(data_dir / "oncoai.sqlite3")))

    return Settings(
        project_root=project_root,
        data_dir=data_dir,
        docs_dir=docs_dir,
        reports_dir=reports_dir,
        db_path=db_path,
        local_core_base_url=_env_str("LOCAL_CORE_BASE_URL", "http://localhost:8000"),
        demo_token=_env_str("DEMO_TOKEN", "demo-token"),
        rate_limit_per_minute=int(os.getenv("RATE_LIMIT_PER_MINUTE", "60")),
        llm_primary_url=_env_str("LLM_PRIMARY_URL", ""),
        llm_primary_model=_env_str("LLM_PRIMARY_MODEL", "gpt-4o-mini"),
        llm_primary_api_key=_env_str("LLM_PRIMARY_API_KEY", _env_str("OPENAI_API_KEY", "")),
        llm_fallback_url=_env_str("LLM_FALLBACK_URL", ""),
        llm_fallback_model=_env_str("LLM_FALLBACK_MODEL", "qwen2.5-7b-instruct"),
        llm_fallback_api_key=_env_str("LLM_FALLBACK_API_KEY", ""),
        release_profile=normalize_release_profile(_env_str("ONCOAI_RELEASE_PROFILE", "compat")),
        reasoning_mode=normalize_reasoning_mode(_env_str("ONCOAI_REASONING_MODE", "llm_rag_only")),
        prompt_registry_dir=Path(_env_str("ONCOAI_PROMPT_REGISTRY_DIR", str(project_root / "docs" / "prompts"))),
        vector_backend=_env_str("VECTOR_BACKEND", "local"),
        qdrant_url=_env_str("QDRANT_URL", ""),
        qdrant_collection=_env_str("QDRANT_COLLECTION", "oncoai_chunks"),
        retrieval_top_k=int(os.getenv("RETRIEVAL_TOP_K", "12")),
        rerank_top_n=int(os.getenv("RERANK_TOP_N", "6")),
        embedding_backend=_env_str("EMBEDDING_BACKEND", "hash"),
        embedding_url=_env_str("EMBEDDING_URL", ""),
        embedding_model=_env_str("EMBEDDING_MODEL", ""),
        embedding_api_key=_env_str(
            "EMBEDDING_API_KEY",
            _env_str("OPENAI_API_KEY", _env_str("LLM_PRIMARY_API_KEY", "")),
        ),
        reranker_backend=_env_str("RERANKER_BACKEND", "lexical"),
        rag_engine=_env_str("RAG_ENGINE", "basic"),
        llm_generation_enabled=_env_bool("LLM_GENERATION_ENABLED", False),
        llm_probe_enabled=_env_bool("LLM_PROBE_ENABLED", False),
        session_audit_retention_days=max(1, min(int(os.getenv("SESSION_AUDIT_RETENTION_DAYS", "90")), 3650)),
        session_audit_alert_min_events=max(1, min(int(os.getenv("SESSION_AUDIT_ALERT_MIN_EVENTS", "10")), 100_000)),
        session_audit_alert_deny_rate_warn=_env_float(
            "SESSION_AUDIT_ALERT_DENY_RATE_WARN",
            default=0.35,
            min_value=0.0,
            max_value=1.0,
        ),
        session_audit_alert_deny_rate_critical=_env_float(
            "SESSION_AUDIT_ALERT_DENY_RATE_CRITICAL",
            default=0.60,
            min_value=0.0,
            max_value=1.0,
        ),
        session_audit_alert_error_count_warn=max(
            1,
            min(int(os.getenv("SESSION_AUDIT_ALERT_ERROR_COUNT_WARN", "5")), 1_000_000),
        ),
        session_audit_alert_error_count_critical=max(
            1,
            min(int(os.getenv("SESSION_AUDIT_ALERT_ERROR_COUNT_CRITICAL", "20")), 1_000_000),
        ),
        session_audit_alert_replay_count_warn=max(
            1,
            min(int(os.getenv("SESSION_AUDIT_ALERT_REPLAY_COUNT_WARN", "1")), 1_000_000),
        ),
        session_audit_alert_replay_count_critical=max(
            1,
            min(int(os.getenv("SESSION_AUDIT_ALERT_REPLAY_COUNT_CRITICAL", "3")), 1_000_000),
        ),
        session_audit_alert_config_error_count_warn=max(
            1,
            min(int(os.getenv("SESSION_AUDIT_ALERT_CONFIG_ERROR_COUNT_WARN", "1")), 1_000_000),
        ),
        session_audit_alert_config_error_count_critical=max(
            1,
            min(int(os.getenv("SESSION_AUDIT_ALERT_CONFIG_ERROR_COUNT_CRITICAL", "3")), 1_000_000),
        ),
        case_import_allow_full_mode=_env_bool("CASE_IMPORT_ALLOW_FULL_MODE", False),
        case_import_full_require_ack=_env_bool("CASE_IMPORT_FULL_REQUIRE_ACK", True),
        case_import_deid_redact_pii=_env_bool("CASE_IMPORT_DEID_REDACT_PII", True),
        oncoai_doctor_schema_v1_2_enabled=_env_bool("ONCOAI_DOCTOR_SCHEMA_V1_2_ENABLED", True),
        oncoai_structural_chunker_enabled=_env_bool("ONCOAI_STRUCTURAL_CHUNKER_ENABLED", True),
        oncoai_guideline_sync_enabled=_env_bool("ONCOAI_GUIDELINE_SYNC_ENABLED", True),
        oncoai_casefacts_enabled=_env_bool("ONCOAI_CASEFACTS_ENABLED", True),
        oncoai_prompt_schema_strict=_env_bool("ONCOAI_PROMPT_SCHEMA_STRICT", False),
        oncoai_compat_v1_1_projection_enabled=_env_bool("ONCOAI_COMPAT_V1_1_PROJECTION_ENABLED", True),
        oncoai_drug_safety_enabled=_env_bool("ONCOAI_DRUG_SAFETY_ENABLED", True),
        drug_safety_cache_ttl_hours=max(1, min(int(os.getenv("DRUG_SAFETY_CACHE_TTL_HOURS", str(24 * 14))), 24 * 365)),
        drug_safety_request_timeout_sec=max(3, min(int(os.getenv("DRUG_SAFETY_REQUEST_TIMEOUT_SEC", "12")), 120)),
        drug_safety_openfda_base_url=_env_str("DRUG_SAFETY_OPENFDA_BASE_URL", "https://api.fda.gov"),
    )
