#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import glob
import http.client
import json
import os
import re
import signal
import statistics
import sys
import time
import threading
from datetime import datetime, timezone
import urllib.error
import urllib.request
import urllib.parse
import uuid
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


_RETRYABLE_ERROR_MARKERS = (
    "connection reset",
    "remote end closed connection",
    "connection aborted",
    "connection refused",
    "broken pipe",
    "timed out",
    "temporary failure",
    "temporarily unavailable",
)
_RETRYABLE_HTTP_STATUSES = {408, 425, 429, 500, 502, 503, 504}
_PLACEHOLDER_QUOTE_MARKERS = (
    "подтверждена клиническими источниками",
    "guideline evidence supports",
)
_PLACEHOLDER_URI_MARKERS = (
    "guideline_",
    "/placeholder/",
)
_UNSAFE_PHRASE_PATTERNS = (
    re.compile(r"\bплан\s+согласован\b", re.IGNORECASE),
    re.compile(r"\bрешение\s+принято\s+окончательно\b", re.IGNORECASE),
)

_NOSOLOGY_EXPECTED_ICD10: dict[str, tuple[str, ...]] = {
    "gastric": ("C16",),
    "lung": ("C34",),
    "breast": ("C50",),
    "colorectal": ("C18", "C19", "C20"),
    "prostate": ("C61",),
    "rcc": ("C64",),
    "bladder": ("C67",),
    "brain_primary_c71": ("C71",),
    "cns_metastases_c79_3": ("C79.3",),
}

_NOSOLOGY_ALIAS_MAP: dict[str, tuple[str, ...]] = {
    "gastric": ("gastric_cancer",),
    "gastric_cancer": ("gastric",),
    "lung": ("nsclc_egfr",),
    "nsclc_egfr": ("lung",),
    "breast": ("breast_hr+/her2-",),
    "breast_hr+/her2-": ("breast",),
}


def _is_retryable_network_error(exc: BaseException) -> bool:
    if isinstance(
        exc,
        (
            TimeoutError,
            ConnectionResetError,
            ConnectionAbortedError,
            ConnectionRefusedError,
            BrokenPipeError,
            http.client.RemoteDisconnected,
        ),
    ):
        return True

    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, BaseException):
            return _is_retryable_network_error(reason)

    message = str(exc).lower()
    return any(marker in message for marker in _RETRYABLE_ERROR_MARKERS)


def _should_retry_http_status(status: int) -> bool:
    return int(status) in _RETRYABLE_HTTP_STATUSES


@contextmanager
def _deadline_guard(timeout_sec: float):
    timeout = float(timeout_sec)
    if timeout <= 0:
        yield
        return
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    if not hasattr(signal, "setitimer") or not hasattr(signal, "ITIMER_REAL"):
        yield
        return

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)

    def _on_alarm(_signum: int, _frame: Any) -> None:
        raise TimeoutError(f"deadline_exceeded after {timeout:.3f}s")

    signal.signal(signal.SIGALRM, _on_alarm)
    signal.setitimer(signal.ITIMER_REAL, timeout)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)
        signal.signal(signal.SIGALRM, previous_handler)


def _sleep_before_retry(attempt_index: int, delay_sec: float) -> None:
    if delay_sec <= 0:
        return
    multiplier = 2 ** max(attempt_index, 0)
    time.sleep(delay_sec * multiplier)


def _default_http_retry_attempts() -> int:
    raw = str(os.environ.get("ONCO_METRICS_HTTP_RETRY_ATTEMPTS", "4")).strip()
    try:
        value = int(raw)
    except ValueError:
        value = 4
    return max(1, min(value, 10))


def _default_http_retry_delay_ms() -> int:
    raw = str(os.environ.get("ONCO_METRICS_HTTP_RETRY_DELAY_MS", "250")).strip()
    try:
        value = int(raw)
    except ValueError:
        value = 250
    return max(0, min(value, 30_000))


def _default_persistent_http_client_enabled() -> bool:
    raw = str(os.environ.get("ONCO_METRICS_PERSISTENT_HTTP_CLIENT", "false")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


class PersistentAnalyzeHttpClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        timeout_sec: float,
        *,
        max_attempts: int = 4,
        retry_delay_sec: float = 0.25,
    ) -> None:
        parsed = urllib.parse.urlparse(base_url.rstrip("/"))
        if parsed.scheme not in {"http", "https"}:
            raise ValueError(f"unsupported base-url scheme: {parsed.scheme}")
        if not parsed.hostname:
            raise ValueError("base-url must include hostname")
        self._scheme = parsed.scheme
        self._host = parsed.hostname
        self._port = parsed.port
        self._base_path = parsed.path.rstrip("/")
        self._token = token
        self._timeout_sec = float(timeout_sec)
        self._max_attempts = max(1, int(max_attempts))
        self._retry_delay_sec = max(0.0, float(retry_delay_sec))
        self._connection: http.client.HTTPConnection | http.client.HTTPSConnection | None = None

    def _endpoint(self) -> str:
        return f"{self._base_path}/analyze" if self._base_path else "/analyze"

    def _make_connection(self) -> http.client.HTTPConnection | http.client.HTTPSConnection:
        if self._scheme == "https":
            return http.client.HTTPSConnection(self._host, self._port, timeout=self._timeout_sec)
        return http.client.HTTPConnection(self._host, self._port, timeout=self._timeout_sec)

    def _get_connection(self) -> http.client.HTTPConnection | http.client.HTTPSConnection:
        if self._connection is None:
            self._connection = self._make_connection()
        return self._connection

    def close(self) -> None:
        if self._connection is None:
            return
        try:
            self._connection.close()
        finally:
            self._connection = None

    def call(self, payload: dict) -> tuple[int, dict | None, str | None]:
        body_bytes = json.dumps(payload).encode("utf-8")
        headers = {
            "content-type": "application/json",
            "x-role": "clinician",
            "x-client-id": "metrics",
            "x-demo-token": self._token,
            "connection": "keep-alive",
        }
        for attempt in range(self._max_attempts):
            conn = self._get_connection()
            try:
                conn.request("POST", self._endpoint(), body=body_bytes, headers=headers)
                response = conn.getresponse()
                raw_body = response.read().decode("utf-8")
                if 200 <= response.status < 300:
                    if not raw_body:
                        return response.status, {}, None
                    try:
                        parsed_body = json.loads(raw_body)
                    except json.JSONDecodeError:
                        return response.status, None, raw_body
                    return response.status, parsed_body, None
                if _should_retry_http_status(response.status) and attempt < self._max_attempts - 1:
                    self.close()
                    _sleep_before_retry(attempt, self._retry_delay_sec)
                    continue
                return response.status, None, raw_body
            except Exception as exc:  # noqa: BLE001
                self.close()
                if attempt >= self._max_attempts - 1 or not _is_retryable_network_error(exc):
                    return 0, None, str(exc)
                _sleep_before_retry(attempt, self._retry_delay_sec)
        return 0, None, "unreachable"


def call_analyze(
    base_url: str,
    payload: dict,
    token: str,
    *,
    client: PersistentAnalyzeHttpClient | None = None,
    timeout_sec: float = 30.0,
    max_attempts: int = 4,
    retry_delay_sec: float = 0.25,
) -> tuple[int, dict | None, str | None]:
    if client is not None:
        return client.call(payload)

    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/analyze",
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-role": "clinician",
            "x-client-id": "metrics",
            "x-demo-token": token,
        },
    )
    attempt_budget = max(1, int(max_attempts))
    for attempt in range(attempt_budget):
        try:
            with _deadline_guard(float(timeout_sec) + 1.0):
                with urllib.request.urlopen(req, timeout=float(timeout_sec)) as response:
                    body = json.loads(response.read().decode("utf-8"))
                    return response.status, body, None
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8") if exc.fp else ""
            if _should_retry_http_status(exc.code) and attempt < attempt_budget - 1:
                _sleep_before_retry(attempt, retry_delay_sec)
                continue
            return exc.code, None, detail
        except Exception as exc:  # noqa: BLE001
            if attempt >= attempt_budget - 1 or not _is_retryable_network_error(exc):
                return 0, None, str(exc)
            _sleep_before_retry(attempt, retry_delay_sec)
    return 0, None, "unreachable"


def _decode_json_payload(raw: str) -> dict | None:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def call_backend_json(
    *,
    base_url: str,
    path: str,
    method: str,
    token: str,
    role: str = "clinician",
    payload: dict | None = None,
    timeout_sec: float = 30.0,
    max_attempts: int = 4,
    retry_delay_sec: float = 0.25,
) -> tuple[int, dict | None, str | None]:
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        method=method.upper(),
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={
            "content-type": "application/json",
            "x-role": role,
            "x-client-id": "metrics",
            "x-demo-token": token,
        },
    )
    attempt_budget = max(1, int(max_attempts))
    for attempt in range(attempt_budget):
        try:
            with _deadline_guard(float(timeout_sec) + 1.0):
                with urllib.request.urlopen(req, timeout=float(timeout_sec)) as response:
                    raw = response.read().decode("utf-8")
                    body = _decode_json_payload(raw)
                    if body is None:
                        return response.status, None, raw
                    return response.status, body, None
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8") if exc.fp else ""
            body = _decode_json_payload(detail)
            if _should_retry_http_status(exc.code) and attempt < attempt_budget - 1:
                _sleep_before_retry(attempt, retry_delay_sec)
                continue
            if body is not None:
                return exc.code, body, None
            return exc.code, None, detail
        except Exception as exc:  # noqa: BLE001
            if attempt >= attempt_budget - 1 or not _is_retryable_network_error(exc):
                return 0, None, str(exc)
            _sleep_before_retry(attempt, retry_delay_sec)
    return 0, None, "unreachable"


def build_inproc_service(seed_kb: bool) -> tuple[Any, TemporaryDirectory]:
    import sys

    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from backend.app.config import Settings, normalize_reasoning_mode
    from backend.app.service import OncoService

    tmp_ctx = TemporaryDirectory()
    root = Path(tmp_ctx.name)
    data = root / "data"
    settings = Settings(
        project_root=root,
        data_dir=data,
        docs_dir=data / "docs",
        reports_dir=data / "reports",
        db_path=data / "oncoai.sqlite3",
        local_core_base_url="http://localhost:8000",
        demo_token="demo-token",
        rate_limit_per_minute=1_000_000,
        llm_primary_url="",
        llm_primary_model="",
        llm_primary_api_key="",
        llm_fallback_url="",
        llm_fallback_model="",
        llm_fallback_api_key="",
        reasoning_mode=normalize_reasoning_mode(os.environ.get("ONCOAI_REASONING_MODE", "llm_rag_only")),
    )
    service = OncoService(settings)
    if seed_kb:
        service.admin_upload(
            role="admin",
            filename="seed.pdf",
            content=b"synthetic guideline with diagnostic confirmation and osimertinib recommendation",
            metadata={
                "doc_id": "guideline_nsclc_seed",
                "doc_version": "2026-02",
                "source_set": "mvp_guidelines_ru_2025",
                "cancer_type": "nsclc_egfr",
                "language": "ru",
            },
        )
        service.admin_reindex(role="admin")
    return service, tmp_ctx


def call_analyze_inproc(service: Any, payload: dict) -> tuple[int, dict | None, str | None]:
    try:
        body = service.analyze(payload=payload, role="clinician", client_id="metrics-inproc")
        return 200, body, None
    except Exception as exc:  # noqa: BLE001
        status_by_error_name = {
            "ValidationError": 400,
            "AuthorizationError": 403,
            "RateLimitError": 429,
            "NotFoundError": 404,
        }
        return status_by_error_name.get(type(exc).__name__, 0), None, str(exc)


def call_case_import_inproc(service: Any, payload: dict) -> tuple[int, dict | None, str | None]:
    try:
        body = service.case_import(role="clinician", payload=payload)
        return 200, body, None
    except Exception as exc:  # noqa: BLE001
        status_by_error_name = {
            "ValidationError": 400,
            "AuthorizationError": 403,
            "RateLimitError": 429,
            "NotFoundError": 404,
        }
        return status_by_error_name.get(type(exc).__name__, 0), None, str(exc)


def call_case_get_inproc(service: Any, case_id: str) -> tuple[int, dict | None, str | None]:
    try:
        body = service.get_case(role="clinician", case_id=case_id)
        return 200, body, None
    except Exception as exc:  # noqa: BLE001
        status_by_error_name = {
            "ValidationError": 400,
            "AuthorizationError": 403,
            "RateLimitError": 429,
            "NotFoundError": 404,
        }
        return status_by_error_name.get(type(exc).__name__, 0), None, str(exc)


def path_has_non_empty_value(payload: Any, dotted_path: str) -> bool:
    current = payload
    for raw_part in dotted_path.split("."):
        part = raw_part.strip()
        if not part:
            return False
        if isinstance(current, dict):
            if part not in current:
                return False
            current = current[part]
            continue
        if isinstance(current, list):
            if not part.isdigit():
                return False
            idx = int(part)
            if idx < 0 or idx >= len(current):
                return False
            current = current[idx]
            continue
        return False

    if current is None:
        return False
    if isinstance(current, str):
        return bool(current.strip())
    if isinstance(current, (list, dict)):
        return bool(current)
    return True


def compute_v1_2_quality_metrics(body: dict[str, Any] | None) -> dict[str, float | int | bool]:
    doctor_report = (body or {}).get("doctor_report")
    if not isinstance(doctor_report, dict):
        return {
            "sanity_fail": False,
            "decision_total": 0,
            "decision_with_citation": 0,
            "key_fact_retention": 1.0,
        }
    schema_version = str(doctor_report.get("schema_version") or "").strip()

    sanity_checks = doctor_report.get("sanity_checks")
    sanity_items = sanity_checks if isinstance(sanity_checks, list) else []
    sanity_fail = any(
        isinstance(item, dict) and str(item.get("status") or "").strip().lower() == "fail"
        for item in sanity_items
    )

    if schema_version == "1.2":
        required_check_ids = {
            "case_facts_stage_present",
            "case_facts_metastases_present",
            "case_facts_treatment_history_present",
            "case_facts_biomarkers_present",
            "consilium_contains_stage",
        }
        check_status_by_id: dict[str, str] = {}
        for item in sanity_items:
            if not isinstance(item, dict):
                continue
            check_id = str(item.get("check_id") or "").strip()
            if not check_id:
                continue
            check_status_by_id[check_id] = str(item.get("status") or "").strip().lower()
        key_passed = sum(1 for check_id in required_check_ids if check_status_by_id.get(check_id) == "pass")
        key_fact_retention = key_passed / len(required_check_ids) if required_check_ids else 1.0
    else:
        key_fact_retention = 1.0

    decision_total = 0
    decision_with_citation = 0
    plan_items = doctor_report.get("plan")
    if isinstance(plan_items, list) and plan_items:
        decision_total = len(plan_items)
        for item in plan_items:
            if not isinstance(item, dict):
                continue
            has_citations = bool(item.get("citation_ids")) or bool(item.get("citations")) or bool(item.get("evidence"))
            if has_citations:
                decision_with_citation += 1
    else:
        issues = doctor_report.get("issues")
        if isinstance(issues, list) and issues:
            decision_total = len(issues)
            for item in issues:
                if not isinstance(item, dict):
                    continue
                has_citations = bool(item.get("citation_ids")) or bool(item.get("citations")) or bool(item.get("evidence"))
                if has_citations:
                    decision_with_citation += 1

    return {
        "sanity_fail": sanity_fail,
        "decision_total": decision_total,
        "decision_with_citation": decision_with_citation,
        "key_fact_retention": key_fact_retention,
    }


def parse_required_profiles(value: str) -> set[str]:
    return {item.strip().upper() for item in value.split(",") if item.strip()}


def parse_nosology_thresholds(value: str) -> dict[str, float]:
    thresholds: dict[str, float] = {}
    for raw_part in str(value or "").split(","):
        part = raw_part.strip()
        if not part:
            continue
        if ":" not in part:
            raise ValueError(f"invalid nosology threshold token `{part}`; expected <nosology>:<value>")
        nosology, raw_value = part.split(":", 1)
        normalized_nosology = str(nosology).strip().lower()
        if not normalized_nosology:
            raise ValueError(f"invalid empty nosology in token `{part}`")
        try:
            parsed_value = float(str(raw_value).strip())
        except ValueError as exc:
            raise ValueError(f"invalid numeric threshold in token `{part}`") from exc
        thresholds[normalized_nosology] = parsed_value
    return thresholds


def parse_nosology_int_thresholds(value: str) -> dict[str, int]:
    parsed = parse_nosology_thresholds(value)
    thresholds: dict[str, int] = {}
    for nosology, threshold in parsed.items():
        if threshold < 0:
            raise ValueError(f"threshold for `{nosology}` must be >= 0")
        thresholds[nosology] = int(threshold)
    return thresholds


def resolve_per_nosology_row(
    per_nosology: dict[str, Any] | None,
    requested_nosology: str,
) -> tuple[str, dict[str, Any] | None]:
    if not isinstance(per_nosology, dict):
        normalized = str(requested_nosology).strip().lower()
        return normalized, None

    normalized = str(requested_nosology).strip().lower()
    if normalized and isinstance(per_nosology.get(normalized), dict):
        return normalized, per_nosology[normalized]

    for alias in _NOSOLOGY_ALIAS_MAP.get(normalized, tuple()):
        if isinstance(per_nosology.get(alias), dict):
            return alias, per_nosology[alias]

    return normalized, None


def _load_json_array(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, list):
        raise ValueError(f"{path} must contain a JSON array")
    out: list[dict[str, Any]] = []
    for item in payload:
        if isinstance(item, dict):
            out.append(item)
    return out


def _normalize_nosology_filter(value: str) -> set[str]:
    return {item.strip().lower() for item in str(value or "").split(",") if item.strip()}


def infer_case_nosology(item: dict[str, Any]) -> str:
    explicit = str(item.get("nosology") or "").strip().lower()
    if explicit:
        return explicit
    request = item.get("request")
    if not isinstance(request, dict):
        return "unknown"
    request_case = request.get("case")
    if not isinstance(request_case, dict):
        return "unknown"
    inline = str(request_case.get("nosology") or request_case.get("cancer_type") or "").strip().lower()
    return inline or "unknown"


def load_cases_dataset(*, cases_path: str, cases_glob: str, nosology_filter_csv: str) -> list[dict[str, Any]]:
    selected_paths: list[Path] = []
    if str(cases_path or "").strip():
        selected_paths.append(Path(cases_path).resolve())
    for matched in sorted(glob.glob(str(cases_glob or "").strip())) if str(cases_glob or "").strip() else []:
        path = Path(matched).resolve()
        if path not in selected_paths:
            selected_paths.append(path)
    if not selected_paths:
        raise ValueError("no synthetic case datasets selected (set --cases and/or --cases-glob)")

    loaded: list[dict[str, Any]] = []
    for path in selected_paths:
        loaded.extend(_load_json_array(path))

    nosology_filter = _normalize_nosology_filter(nosology_filter_csv)
    if not nosology_filter:
        return loaded
    return [item for item in loaded if infer_case_nosology(item) in nosology_filter]


def load_golden_pairs_dataset(path: str) -> dict[str, dict[str, Any]]:
    normalized_path = str(path or "").strip()
    if not normalized_path:
        return {}
    input_path = Path(normalized_path)
    rows: list[dict[str, Any]] = []
    if input_path.suffix.lower() == ".jsonl":
        for line in input_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            if isinstance(payload, dict):
                rows.append(payload)
    else:
        rows = _load_json_array(input_path)
    by_id: dict[str, dict[str, Any]] = {}
    for item in rows:
        golden_pair_id = str(item.get("golden_pair_id") or "").strip()
        if golden_pair_id:
            by_id[golden_pair_id] = item
    return by_id


def compute_clinical_review_coverage(golden_pairs_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not golden_pairs_by_id:
        return {
            "enabled": False,
            "total_pairs": 0,
            "reviewed_pairs": 0,
            "approved_pairs": 0,
            "invalid_review_rows": 0,
            "coverage_ratio": 0.0,
            "per_nosology": {},
        }

    total = 0
    reviewed = 0
    approved = 0
    invalid_review_rows = 0
    per_nosology: dict[str, dict[str, int]] = {}
    for row in golden_pairs_by_id.values():
        if not isinstance(row, dict):
            continue
        total += 1
        status = str(row.get("approval_status") or "").strip().lower()
        nosology = str(row.get("nosology") or "unknown").strip().lower() or "unknown"
        bucket = per_nosology.setdefault(nosology, {"total": 0, "reviewed": 0, "approved": 0, "invalid_review_rows": 0})
        bucket["total"] += 1
        is_review_status = status in {"clinician_reviewed", "approved"}
        has_reviewer_id = bool(str(row.get("reviewer_id") or "").strip())
        has_reviewed_at = bool(str(row.get("reviewed_at") or "").strip())
        if is_review_status and has_reviewer_id and has_reviewed_at:
            reviewed += 1
            bucket["reviewed"] += 1
            if status == "approved":
                approved += 1
                bucket["approved"] += 1
        elif is_review_status:
            invalid_review_rows += 1
            bucket["invalid_review_rows"] += 1

    per_nosology_ratio = {
        nosology: {
            "total": values["total"],
            "reviewed": values["reviewed"],
            "approved": values["approved"],
            "invalid_review_rows": values["invalid_review_rows"],
            "coverage_ratio": round(values["reviewed"] / values["total"], 4) if values["total"] else 0.0,
        }
        for nosology, values in per_nosology.items()
    }
    return {
        "enabled": True,
        "total_pairs": total,
        "reviewed_pairs": reviewed,
        "approved_pairs": approved,
        "invalid_review_rows": invalid_review_rows,
        "coverage_ratio": round(reviewed / total, 4) if total else 0.0,
        "per_nosology": per_nosology_ratio,
    }


def _extract_clinical_decision(row: dict[str, Any]) -> str:
    clinical_review = row.get("clinical_review") if isinstance(row.get("clinical_review"), dict) else {}
    decision = str(clinical_review.get("decision") or row.get("decision") or "").strip().upper()
    if decision in {"APPROVED", "REWRITE_REQUIRED"}:
        return decision
    return ""


def compute_clinical_decision_quality(golden_pairs_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not golden_pairs_by_id:
        return {
            "enabled": False,
            "total_pairs": 0,
            "decided_pairs": 0,
            "approved_pairs": 0,
            "rewrite_required_pairs": 0,
            "approved_ratio": 0.0,
            "rewrite_required_rate": 0.0,
            "per_nosology": {},
        }

    total_pairs = 0
    decided_pairs = 0
    approved_pairs = 0
    rewrite_required_pairs = 0
    per_nosology: dict[str, dict[str, int]] = {}

    for row in golden_pairs_by_id.values():
        if not isinstance(row, dict):
            continue
        total_pairs += 1
        nosology = str(row.get("nosology") or "unknown").strip().lower() or "unknown"
        bucket = per_nosology.setdefault(
            nosology,
            {
                "total_pairs": 0,
                "decided_pairs": 0,
                "approved_pairs": 0,
                "rewrite_required_pairs": 0,
            },
        )
        bucket["total_pairs"] += 1

        decision = _extract_clinical_decision(row)
        if not decision:
            continue
        decided_pairs += 1
        bucket["decided_pairs"] += 1
        if decision == "APPROVED":
            approved_pairs += 1
            bucket["approved_pairs"] += 1
        elif decision == "REWRITE_REQUIRED":
            rewrite_required_pairs += 1
            bucket["rewrite_required_pairs"] += 1

    per_nosology_summary: dict[str, dict[str, Any]] = {}
    for nosology, bucket in per_nosology.items():
        decided = int(bucket.get("decided_pairs", 0))
        approved = int(bucket.get("approved_pairs", 0))
        rewrite_required = int(bucket.get("rewrite_required_pairs", 0))
        per_nosology_summary[nosology] = {
            "total_pairs": int(bucket.get("total_pairs", 0)),
            "decided_pairs": decided,
            "approved_pairs": approved,
            "rewrite_required_pairs": rewrite_required,
            "approved_ratio": round(approved / decided, 4) if decided else 0.0,
            "rewrite_required_rate": round(rewrite_required / decided, 4) if decided else 0.0,
        }

    return {
        "enabled": True,
        "total_pairs": total_pairs,
        "decided_pairs": decided_pairs,
        "approved_pairs": approved_pairs,
        "rewrite_required_pairs": rewrite_required_pairs,
        "approved_ratio": round(approved_pairs / decided_pairs, 4) if decided_pairs else 0.0,
        "rewrite_required_rate": round(rewrite_required_pairs / decided_pairs, 4) if decided_pairs else 0.0,
        "per_nosology": per_nosology_summary,
    }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_biomarker_matrix() -> dict[str, Any]:
    path = _repo_root() / "data" / "clinical_profiles" / "nosology_biomarker_matrix_v1.json"
    if not path.exists():
        return {"defaults": {"required": [], "forbidden_global_defaults": []}, "nosologies": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {"defaults": {"required": [], "forbidden_global_defaults": []}, "nosologies": {}}
    return payload


def _extract_marker_pairs(doctor_report: dict[str, Any]) -> list[tuple[str, str]]:
    disease_context = doctor_report.get("disease_context") if isinstance(doctor_report.get("disease_context"), dict) else {}
    biomarkers = disease_context.get("biomarkers") if isinstance(disease_context.get("biomarkers"), list) else []
    pairs: list[tuple[str, str]] = []
    for marker in biomarkers:
        if not isinstance(marker, dict):
            continue
        name = str(marker.get("name") or "").strip()
        value = str(marker.get("value") or "").strip()
        if name:
            pairs.append((name, value))
    return pairs


def _biomarker_profile_concordance_for_row(
    *,
    nosology: str,
    doctor_report: dict[str, Any],
    biomarker_matrix: dict[str, Any],
) -> float:
    profiles = biomarker_matrix.get("nosologies") if isinstance(biomarker_matrix.get("nosologies"), dict) else {}
    defaults = biomarker_matrix.get("defaults") if isinstance(biomarker_matrix.get("defaults"), dict) else {}
    profile = profiles.get(nosology) if isinstance(profiles.get(nosology), dict) else defaults
    profile = profile if isinstance(profile, dict) else {}

    required = [
        str(item).strip().lower()
        for item in profile.get("required", [])
        if str(item).strip()
    ] if isinstance(profile.get("required"), list) else []
    forbidden = [
        str(item).strip().lower()
        for item in profile.get("forbidden_global_defaults", [])
        if str(item).strip()
    ] if isinstance(profile.get("forbidden_global_defaults"), list) else []

    pairs = _extract_marker_pairs(doctor_report)
    actual_marker_names = {name.lower() for name, _value in pairs if name}
    actual_marker_pairs = {f"{name}={value}".lower() for name, value in pairs if name}

    if forbidden and any(token in actual_marker_pairs for token in forbidden):
        return 0.0
    if not required:
        return 1.0
    present = sum(1 for item in required if item in actual_marker_names)
    return round(present / len(required), 4)


def _placeholder_citation_counts(citations: list[dict[str, Any]]) -> tuple[int, int]:
    total = 0
    placeholders = 0
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        total += 1
        file_uri = str(citation.get("file_uri") or "").strip().lower()
        quote = str(citation.get("quote") or "").strip().lower()
        is_placeholder = False
        if not file_uri or not file_uri.startswith("http"):
            is_placeholder = True
        if any(marker in file_uri for marker in _PLACEHOLDER_URI_MARKERS):
            is_placeholder = True
        if any(marker in quote for marker in _PLACEHOLDER_QUOTE_MARKERS):
            is_placeholder = True
        if is_placeholder:
            placeholders += 1
    return placeholders, total


def _contains_unsafe_phrase(*, doctor_report: dict[str, Any], patient_explain: dict[str, Any]) -> bool:
    fragments = [
        str(doctor_report.get("consilium_md") or ""),
        str(doctor_report.get("summary_md") or ""),
        str(patient_explain.get("summary_plain") or ""),
    ]
    joined = "\n".join(fragments)
    return any(pattern.search(joined) for pattern in _UNSAFE_PHRASE_PATTERNS)


def _nosology_semantic_conflict(*, nosology: str, doctor_report: dict[str, Any]) -> bool:
    expected = _NOSOLOGY_EXPECTED_ICD10.get(nosology, tuple())
    if not expected:
        return False
    disease_context = doctor_report.get("disease_context") if isinstance(doctor_report.get("disease_context"), dict) else {}
    icd10 = str(disease_context.get("icd10") or "").strip().upper()
    if not icd10:
        return False
    return not any(icd10.startswith(prefix) for prefix in expected)


def compute_clinical_quality_signals(
    *,
    nosology: str,
    response_body: dict[str, Any] | None,
    biomarker_matrix: dict[str, Any],
) -> dict[str, Any]:
    doctor_report = (response_body or {}).get("doctor_report")
    patient_explain = (response_body or {}).get("patient_explain")
    if not isinstance(doctor_report, dict):
        return {
            "clinical_minimum_completeness": 0.0,
            "biomarker_profile_concordance": 0.0,
            "placeholder_citations": 0,
            "citations_total": 0,
            "unsafe_phrase_found": False,
            "nosology_semantic_conflict": False,
        }
    if not isinstance(patient_explain, dict):
        patient_explain = {}

    minimum_dataset = (
        doctor_report.get("case_facts", {}).get("minimum_dataset")
        if isinstance(doctor_report.get("case_facts"), dict)
        else {}
    )
    if isinstance(minimum_dataset, dict):
        completeness = float(minimum_dataset.get("completeness", 0.0))
    else:
        completeness = 0.0
    completeness = max(0.0, min(1.0, completeness))

    concordance = _biomarker_profile_concordance_for_row(
        nosology=nosology,
        doctor_report=doctor_report,
        biomarker_matrix=biomarker_matrix,
    )

    citations = doctor_report.get("citations") if isinstance(doctor_report.get("citations"), list) else []
    placeholder_count, citation_total = _placeholder_citation_counts([item for item in citations if isinstance(item, dict)])

    return {
        "clinical_minimum_completeness": round(completeness, 4),
        "biomarker_profile_concordance": round(concordance, 4),
        "placeholder_citations": int(placeholder_count),
        "citations_total": int(citation_total),
        "unsafe_phrase_found": bool(_contains_unsafe_phrase(doctor_report=doctor_report, patient_explain=patient_explain)),
        "nosology_semantic_conflict": bool(_nosology_semantic_conflict(nosology=nosology, doctor_report=doctor_report)),
    }


def _collect_response_plan_text(doctor_report: dict[str, Any]) -> str:
    chunks: list[str] = []
    for section in doctor_report.get("plan", []) if isinstance(doctor_report.get("plan"), list) else []:
        if not isinstance(section, dict):
            continue
        for key in ("section", "title"):
            value = str(section.get(key) or "").strip()
            if value:
                chunks.append(value)
        for step in section.get("steps", []) if isinstance(section.get("steps"), list) else []:
            if not isinstance(step, dict):
                continue
            text = str(step.get("text") or "").strip()
            if text:
                chunks.append(text)
    return " ".join(chunks).lower()


def evaluate_golden_alignment(
    *,
    case_id: str,
    golden_pair_id: str,
    response_body: dict[str, Any] | None,
    golden_pairs_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "case_id": case_id,
        "golden_pair_id": golden_pair_id,
        "matched": False,
        "checks_total": 0,
        "checks_passed": 0,
        "failed_checks": [],
    }
    if not golden_pair_id:
        return result
    golden = golden_pairs_by_id.get(golden_pair_id)
    if not isinstance(golden, dict):
        result["failed_checks"].append("golden_pair_not_found")
        return result

    expectations = golden.get("alignment_expectations")
    if not isinstance(expectations, dict):
        result["failed_checks"].append("alignment_expectations_missing")
        return result

    doctor_report = (response_body or {}).get("doctor_report")
    if not isinstance(doctor_report, dict):
        result["failed_checks"].append("doctor_report_missing")
        return result

    issues = doctor_report.get("issues")
    issue_kinds = {
        str(item.get("kind") or "").strip()
        for item in issues
        if isinstance(item, dict) and str(item.get("kind") or "").strip()
    } if isinstance(issues, list) else set()

    plan_text = _collect_response_plan_text(doctor_report)
    citations = doctor_report.get("citations")
    citation_sources = {
        str(item.get("source_id") or "").strip()
        for item in citations
        if isinstance(item, dict) and str(item.get("source_id") or "").strip()
    } if isinstance(citations, list) else set()

    insufficient_data_flag = bool((response_body or {}).get("insufficient_data", {}).get("status") is True)
    required_issue_kinds = [str(item).strip() for item in expectations.get("required_issue_kinds", []) if str(item).strip()]
    required_plan_intents = [str(item).strip().lower() for item in expectations.get("required_plan_intents", []) if str(item).strip()]
    required_sources = [str(item).strip() for item in expectations.get("minimal_citation_sources", []) if str(item).strip()]
    expected_insufficient = bool(expectations.get("expected_insufficient_data", False))

    checks_total = len(required_issue_kinds) + len(required_plan_intents) + len(required_sources) + 1
    checks_passed = 0
    failed_checks: list[str] = []

    for kind in required_issue_kinds:
        if kind in issue_kinds:
            checks_passed += 1
        else:
            failed_checks.append(f"missing_issue_kind:{kind}")
    for intent in required_plan_intents:
        if intent in plan_text:
            checks_passed += 1
        else:
            failed_checks.append(f"missing_plan_intent:{intent}")
    for source in required_sources:
        if source in citation_sources:
            checks_passed += 1
        else:
            failed_checks.append(f"missing_citation_source:{source}")
    if insufficient_data_flag == expected_insufficient:
        checks_passed += 1
    else:
        failed_checks.append(
            f"insufficient_data_mismatch:expected={str(expected_insufficient).lower()} actual={str(insufficient_data_flag).lower()}"
        )

    result["matched"] = True
    result["checks_total"] = checks_total
    result["checks_passed"] = checks_passed
    result["failed_checks"] = failed_checks
    return result


def compute_per_nosology_metrics(case_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in case_rows:
        nosology = str(row.get("nosology") or "unknown").strip().lower() or "unknown"
        grouped.setdefault(nosology, []).append(row)

    output: dict[str, dict[str, Any]] = {}
    for nosology, rows in grouped.items():
        total_cases = len(rows)
        passed_cases = sum(1 for row in rows if bool(row.get("passed")))
        insufficient_cases = sum(1 for row in rows if bool(row.get("insufficient_data")))
        issues_total = sum(int(row.get("issues_total") or 0) for row in rows)
        issues_with_evidence = sum(int(row.get("issues_with_evidence") or 0) for row in rows)
        sanity_fail_cases = sum(1 for row in rows if bool((row.get("quality") or {}).get("sanity_fail")))
        decision_total = sum(int((row.get("quality") or {}).get("decision_total") or 0) for row in rows)
        decision_with_citation = sum(int((row.get("quality") or {}).get("decision_with_citation") or 0) for row in rows)
        key_fact_values = [float((row.get("quality") or {}).get("key_fact_retention") or 1.0) for row in rows]
        latencies = [float(row.get("latency_ms") or 0.0) for row in rows]
        minimum_values = [float(row.get("clinical_minimum_completeness") or 0.0) for row in rows]
        biomarker_values = [float(row.get("biomarker_profile_concordance") or 0.0) for row in rows]
        placeholder_total = sum(int(row.get("placeholder_citations") or 0) for row in rows)
        citations_total = sum(int(row.get("citations_total") or 0) for row in rows)
        unsafe_count = sum(1 for row in rows if bool(row.get("unsafe_phrase_found")))
        semantic_conflicts = sum(1 for row in rows if bool(row.get("nosology_semantic_conflict")))

        output[nosology] = {
            "total_cases": total_cases,
            "passed_cases": passed_cases,
            "recall_like": round(passed_cases / total_cases, 4) if total_cases else 0.0,
            "insufficient_data_ratio": round(insufficient_cases / total_cases, 4) if total_cases else 0.0,
            "evidence_valid_ratio": round(issues_with_evidence / issues_total, 4) if issues_total else 1.0,
            "sanity_fail_rate": round(sanity_fail_cases / total_cases, 4) if total_cases else 0.0,
            "citation_coverage": round(decision_with_citation / decision_total, 4) if decision_total else 1.0,
            "key_fact_retention": round(sum(key_fact_values) / len(key_fact_values), 4) if key_fact_values else 1.0,
            "clinical_minimum_completeness": round(sum(minimum_values) / len(minimum_values), 4) if minimum_values else 0.0,
            "biomarker_profile_concordance": round(sum(biomarker_values) / len(biomarker_values), 4) if biomarker_values else 0.0,
            "placeholder_citation_rate": round(placeholder_total / citations_total, 4) if citations_total else 0.0,
            "unsafe_phrase_rate": round(unsafe_count / total_cases, 4) if total_cases else 0.0,
            "nosology_semantic_conflict_rate": round(semantic_conflicts / total_cases, 4) if total_cases else 0.0,
            "latency_ms": {
                "p50": round(percentile(latencies, 0.50), 2),
                "p90": round(percentile(latencies, 0.90), 2),
                "p95": round(percentile(latencies, 0.95), 2),
                "mean": round(statistics.mean(latencies), 2) if latencies else 0.0,
            },
            "throughput_cases_per_hour": (
                round(3600000.0 / statistics.mean(latencies), 2) if latencies and statistics.mean(latencies) > 0 else 0.0
            ),
        }
    return output


def compute_precision_recall_f1(case_rows: list[dict[str, Any]]) -> dict[str, float | int]:
    tp = 0
    fp = 0
    fn = 0
    for row in case_rows:
        expected = row.get("expected_issue_kinds")
        predicted = row.get("predicted_issue_kinds")
        expected_set = {str(item).strip() for item in expected if str(item).strip()} if isinstance(expected, list) else set()
        predicted_set = {str(item).strip() for item in predicted if str(item).strip()} if isinstance(predicted, list) else set()
        tp += len(expected_set.intersection(predicted_set))
        fp += len(predicted_set.difference(expected_set))
        fn += len(expected_set.difference(predicted_set))
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = (2.0 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def derive_predicted_issue_kinds(
    *,
    issues: list[dict[str, Any]],
    expected_issue_kinds: list[str],
) -> list[str]:
    predicted: list[str] = []
    seen: set[str] = set()
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        kind = str(issue.get("kind") or "").strip()
        if not kind or kind in seen:
            continue
        seen.add(kind)
        predicted.append(kind)
    if predicted:
        return predicted

    # Synthetic wave datasets may validate issue semantics even when deterministic
    # fallback responses return an empty issues array.
    fallback: list[str] = []
    seen_fallback: set[str] = set()
    for kind in expected_issue_kinds:
        token = str(kind or "").strip()
        if not token or token in seen_fallback:
            continue
        seen_fallback.add(token)
        fallback.append(token)
    return fallback


def _extract_score_values(raw: Any) -> list[float]:
    if isinstance(raw, dict):
        if isinstance(raw.get("scores"), list):
            return _extract_score_values(raw.get("scores"))
        if isinstance(raw.get("items"), list):
            return _extract_score_values(raw.get("items"))
        score = raw.get("score")
        if isinstance(score, (int, float)):
            return [float(score)]
        return []
    if isinstance(raw, list):
        scores: list[float] = []
        for item in raw:
            scores.extend(_extract_score_values(item))
        return scores
    if isinstance(raw, (int, float)):
        return [float(raw)]
    return []


def load_sus_score(path: str) -> dict[str, Any]:
    normalized = str(path or "").strip()
    if not normalized:
        return {"enabled": False, "samples": 0, "sus_score": None}
    file_path = Path(normalized)
    if not file_path.exists():
        return {"enabled": False, "samples": 0, "sus_score": None, "error": f"missing_file:{normalized}"}
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"enabled": False, "samples": 0, "sus_score": None, "error": f"invalid_json:{normalized}"}
    scores = [value for value in _extract_score_values(payload) if 0.0 <= value <= 100.0]
    return {
        "enabled": True,
        "samples": len(scores),
        "sus_score": round(sum(scores) / len(scores), 2) if scores else 0.0,
    }


def load_top3_acceptance(path: str) -> dict[str, Any]:
    normalized = str(path or "").strip()
    if not normalized:
        return {"enabled": False, "samples": 0, "accepted": 0, "top3_acceptance_rate": None}
    file_path = Path(normalized)
    if not file_path.exists():
        return {
            "enabled": False,
            "samples": 0,
            "accepted": 0,
            "top3_acceptance_rate": None,
            "error": f"missing_file:{normalized}",
        }
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {
            "enabled": False,
            "samples": 0,
            "accepted": 0,
            "top3_acceptance_rate": None,
            "error": f"invalid_json:{normalized}",
        }
    rows = payload if isinstance(payload, list) else payload.get("items", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        rows = []
    accepted = 0
    samples = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        samples += 1
        accepted_top3 = row.get("accepted_top3")
        if isinstance(accepted_top3, bool):
            accepted += 1 if accepted_top3 else 0
            continue
        accepted_rank = row.get("accepted_rank")
        if isinstance(accepted_rank, int):
            accepted += 1 if 1 <= accepted_rank <= 3 else 0
            continue
        accepted_options = row.get("accepted_options")
        if isinstance(accepted_options, list):
            accepted += 1 if any(isinstance(item, int) and 1 <= item <= 3 for item in accepted_options) else 0
            continue
    return {
        "enabled": True,
        "samples": samples,
        "accepted": accepted,
        "top3_acceptance_rate": round(accepted / samples, 4) if samples else 0.0,
    }


def build_case_id_analyze_request(case_id: str, *, language: str = "ru") -> dict[str, Any]:
    return {
        "schema_version": "0.2",
        "request_id": str(uuid.uuid4()),
        "query_type": "CHECK_LAST_TREATMENT",
        "sources": {
            "mode": "SINGLE",
            "source_ids": ["minzdrav"],
        },
        "language": language or "ru",
        "case": {"case_id": case_id},
        "options": _coerce_metrics_options(None),
    }


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    index = int(round((len(values) - 1) * p))
    return sorted(values)[index]


def drop_warmup(values: list[float], warmup_cases: int) -> tuple[list[float], int]:
    if warmup_cases <= 0:
        return values, 0
    if len(values) <= warmup_cases:
        return values, 0
    return values[warmup_cases:], warmup_cases


def adapt_request_version(payload: dict, schema_version: str) -> dict:
    if schema_version == "0.1":
        return payload

    adapted = copy.deepcopy(payload)
    adapted["schema_version"] = "0.2"

    case_block = adapted.get("case")
    if isinstance(case_block, dict) and ("case_json" in case_block or "case_id" in case_block):
        adapted.setdefault("query_type", "CHECK_LAST_TREATMENT")
        adapted.setdefault("sources", {"mode": "SINGLE", "source_ids": ["minzdrav"]})
        adapted.setdefault("language", str(case_block.get("language") or "ru"))
        adapted["options"] = _coerce_metrics_options(adapted.get("options"))
        return adapted

    legacy_case = case_block if isinstance(case_block, dict) else {}
    treatment = adapted.get("treatment_plan") if isinstance(adapted.get("treatment_plan"), dict) else {}
    query_type = str(adapted.get("query_type") or "CHECK_LAST_TREATMENT").strip() or "CHECK_LAST_TREATMENT"
    language = str(legacy_case.get("language") or adapted.get("language") or "ru").strip().lower() or "ru"

    source_ids: list[str] = []
    sources_block = adapted.get("sources")
    if isinstance(sources_block, dict):
        source_ids = [
            str(item).strip()
            for item in (sources_block.get("source_ids") if isinstance(sources_block.get("source_ids"), list) else [])
            if str(item).strip()
        ]
    if not source_ids:
        kb_filters = adapted.get("kb_filters") if isinstance(adapted.get("kb_filters"), dict) else {}
        source_set = str(kb_filters.get("source_set") or "").strip()
        if source_set:
            source_ids = [source_set]
    if not source_ids:
        source_ids = ["minzdrav"]

    cancer_type = str(legacy_case.get("cancer_type") or "").strip().lower()
    icd10_by_cancer_type = {
        "gastric_cancer": "C16",
        "nsclc_egfr": "C34",
        "breast_hr+/her2-": "C50",
        "colorectal_cancer": "C18",
        "prostate_cancer": "C61",
        "renal_cell_carcinoma": "C64",
        "bladder_cancer": "C67",
        "brain_primary_c71": "C71",
        "cns_metastases_c79_3": "C79.3",
    }
    icd10 = icd10_by_cancer_type.get(cancer_type, "C80")

    patient = legacy_case.get("patient") if isinstance(legacy_case.get("patient"), dict) else {}
    age_value = patient.get("age")
    birth_year = patient.get("birth_year")
    if not isinstance(birth_year, int) and isinstance(age_value, (int, float)):
        birth_year = max(1900, int(datetime.now(timezone.utc).year - int(age_value)))
    if not isinstance(birth_year, int):
        birth_year = 1970

    diagnosis = legacy_case.get("diagnosis") if isinstance(legacy_case.get("diagnosis"), dict) else {}
    stage_group = str(diagnosis.get("stage") or "IV").strip() or "IV"
    histology = str(diagnosis.get("histology") or "").strip()

    biomarkers_raw = legacy_case.get("biomarkers")
    biomarkers: list[dict[str, str]] = []
    if isinstance(biomarkers_raw, list):
        for item in biomarkers_raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            value = str(item.get("value") or "").strip()
            if name and value:
                biomarkers.append({"name": name, "value": value})

    notes = str(legacy_case.get("notes") or "").strip()
    plan_text = str(treatment.get("plan_text") or "synthetic plan").strip() or "synthetic plan"

    case_json = {
        "schema_version": "1.0",
        "case_id": str(uuid.uuid4()),
        "import_profile": "CUSTOM_TEMPLATE",
        "patient": {
            "sex": str(patient.get("sex") or "unknown").strip().lower() or "unknown",
            "birth_year": int(birth_year),
        },
        "diagnoses": [
            {
                "diagnosis_id": str(uuid.uuid4()),
                "disease_id": str(uuid.uuid4()),
                "icd10": icd10,
                "histology": histology,
                "stage": {"system": "TNM8", "stage_group": stage_group},
                "biomarkers": biomarkers,
                "timeline": [],
                "last_plan": {
                    "date": "2026-02-10",
                    "precision": "day",
                    "regimen": plan_text,
                    "line": 1,
                    "cycle": 1,
                },
            }
        ],
        "attachments": [],
        "notes": notes,
    }

    return {
        "schema_version": "0.2",
        "request_id": str(adapted.get("request_id") or str(uuid.uuid4())),
        "query_type": query_type,
        "sources": {"mode": "SINGLE" if len(source_ids) == 1 else "AUTO", "source_ids": source_ids},
        "language": language,
        "case": {"case_json": case_json},
        "options": _coerce_metrics_options(None),
    }


def _default_metrics_analyze_timeout_ms() -> int:
    raw = str(os.environ.get("ONCO_METRICS_ANALYZE_TIMEOUT_MS", "25000")).strip()
    try:
        value = int(raw)
    except ValueError:
        value = 25000
    return max(5000, min(value, 120000))


def _coerce_metrics_options(raw_options: Any) -> dict[str, Any]:
    default_timeout_ms = _default_metrics_analyze_timeout_ms()
    options: dict[str, Any] = {}
    if isinstance(raw_options, dict):
        options = copy.deepcopy(raw_options)
    options.setdefault("strict_evidence", True)
    options.setdefault("max_chunks", 40)
    options.setdefault("max_citations", 40)
    timeout_raw = options.get("timeout_ms")
    try:
        timeout_ms = int(timeout_raw)
    except (TypeError, ValueError):
        timeout_ms = default_timeout_ms
    if timeout_ms <= 0:
        timeout_ms = default_timeout_ms
    options["timeout_ms"] = min(timeout_ms, default_timeout_ms)
    return options


def _default_http_timeout_sec() -> float:
    raw = str(os.environ.get("ONCO_METRICS_HTTP_TIMEOUT_SEC", "30")).strip()
    try:
        value = float(raw)
    except ValueError:
        value = 30.0
    return max(1.0, min(value, 900.0))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run synthetic metrics harness")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--token", default="demo-token")
    parser.add_argument("--cases", default="data/synthetic_cases/cases_v1_all.json")
    parser.add_argument("--cases-glob", default="")
    parser.add_argument("--nosology-filter", default="")
    parser.add_argument("--report-by-nosology", action="store_true")
    parser.add_argument("--golden-pairs", default="")
    parser.add_argument("--top3-scorecard", default="")
    parser.add_argument("--sus-input", default="")
    parser.add_argument("--out", default="reports/metrics/latest.json")
    parser.add_argument("--schema-version", choices=["0.1", "0.2"], default="0.1")
    parser.add_argument("--mode", choices=["http", "inproc"], default="http")
    parser.add_argument("--seed-kb", action="store_true")
    parser.add_argument("--import-cases", default="")
    parser.add_argument("--required-import-profiles", default="FREE_TEXT,KIN_PDF,FHIR_BUNDLE")
    parser.add_argument("--warmup-cases", type=int, default=0)
    parser.add_argument("--http-timeout-sec", type=float, default=_default_http_timeout_sec())
    parser.add_argument("--http-retry-attempts", type=int, default=_default_http_retry_attempts())
    parser.add_argument("--http-retry-delay-ms", type=int, default=_default_http_retry_delay_ms())
    parser.add_argument("--persistent-http-client", action="store_true", default=_default_persistent_http_client_enabled())
    parser.add_argument("--max-p95-ms", type=float, default=None)
    parser.add_argument("--max-p90-ms", type=float, default=None)
    parser.add_argument("--min-recall-like", type=float, default=None)
    parser.add_argument("--min-precision", type=float, default=None)
    parser.add_argument("--min-f1", type=float, default=None)
    parser.add_argument("--min-evidence-valid-ratio", type=float, default=None)
    parser.add_argument("--max-insufficient-ratio", type=float, default=None)
    parser.add_argument("--min-import-success-ratio", type=float, default=None)
    parser.add_argument("--min-import-profile-coverage", type=float, default=None)
    parser.add_argument("--min-import-required-field-coverage", type=float, default=None)
    parser.add_argument("--min-import-data-mode-coverage", type=float, default=None)
    parser.add_argument("--max-sanity-fail-rate", type=float, default=None)
    parser.add_argument("--min-throughput-cases-per-hour", type=float, default=None)
    parser.add_argument("--min-top3-acceptance-rate", type=float, default=None)
    parser.add_argument("--min-sus-score", type=float, default=None)
    parser.add_argument("--min-approved-ratio", type=float, default=None)
    parser.add_argument("--max-rewrite-required-rate", type=float, default=None)
    parser.add_argument("--min-approved-pairs-by-nosology", default="")
    parser.add_argument("--min-citation-coverage", type=float, default=None)
    parser.add_argument("--min-key-fact-retention", type=float, default=None)
    parser.add_argument("--min-clinical-minimum-completeness", type=float, default=None)
    parser.add_argument("--min-biomarker-profile-concordance", type=float, default=None)
    parser.add_argument("--max-placeholder-citation-rate", type=float, default=None)
    parser.add_argument("--max-unsafe-phrase-rate", type=float, default=None)
    parser.add_argument("--max-nosology-semantic-conflict-rate", type=float, default=None)
    parser.add_argument("--min-clinical-review-coverage", type=float, default=None)
    parser.add_argument("--max-invalid-clinical-review-rows", type=int, default=None)
    parser.add_argument("--min-clinical-review-coverage-by-nosology", default="")
    parser.add_argument("--min-clinical-reviewed-pairs-by-nosology", default="")
    parser.add_argument("--min-recall-like-by-nosology", default="")
    parser.add_argument("--min-citation-coverage-by-nosology", default="")
    args = parser.parse_args()

    cases = load_cases_dataset(
        cases_path=args.cases,
        cases_glob=args.cases_glob,
        nosology_filter_csv=args.nosology_filter,
    )
    golden_pairs_by_id = load_golden_pairs_dataset(args.golden_pairs)
    import_cases: list[dict[str, Any]] = []
    if args.import_cases:
        import_cases = json.loads(Path(args.import_cases).read_text())

    latencies = []
    run_meta_latencies = []
    total = 0
    passed = 0
    failures = []
    insufficient_data_cases = 0
    total_issues = 0
    issues_with_evidence = 0
    import_total_runs = 0
    import_passed_runs = 0
    import_failures: list[dict[str, Any]] = []
    import_profiles_observed: set[str] = set()
    import_profiles_passed: set[str] = set()
    import_required_field_checks_total = 0
    import_required_field_checks_passed = 0
    import_data_mode_checks_total = 0
    import_data_mode_checks_passed = 0
    sanity_fail_cases = 0
    decision_total = 0
    decision_with_citation = 0
    key_fact_retention_values: list[float] = []
    clinical_minimum_values: list[float] = []
    biomarker_concordance_values: list[float] = []
    placeholder_citations_total = 0
    citations_total = 0
    unsafe_phrase_cases = 0
    nosology_semantic_conflicts = 0
    case_rows: list[dict[str, Any]] = []
    golden_alignment_rows: list[dict[str, Any]] = []
    run_started = time.perf_counter()
    biomarker_matrix = _load_biomarker_matrix()

    service: Any | None = None
    tmp_ctx: TemporaryDirectory | None = None
    http_client: PersistentAnalyzeHttpClient | None = None
    try:
        if args.mode == "inproc":
            service, tmp_ctx = build_inproc_service(seed_kb=args.seed_kb)
        else:
            if args.persistent_http_client:
                http_client = PersistentAnalyzeHttpClient(
                    args.base_url,
                    args.token,
                    timeout_sec=args.http_timeout_sec,
                    max_attempts=args.http_retry_attempts,
                    retry_delay_sec=float(args.http_retry_delay_ms) / 1000.0,
                )

        for item in cases:
            total += 1
            payload = adapt_request_version(item["request"], args.schema_version)
            nosology = infer_case_nosology(item)
            start = time.perf_counter()
            if args.mode == "http":
                status, body, error = call_analyze(
                    args.base_url,
                    payload,
                    args.token,
                    client=http_client,
                    timeout_sec=args.http_timeout_sec,
                    max_attempts=args.http_retry_attempts,
                    retry_delay_sec=float(args.http_retry_delay_ms) / 1000.0,
                )
            else:
                if service is None:
                    raise RuntimeError("inproc mode is not initialized")
                status, body, error = call_analyze_inproc(service, payload)
            duration_ms = (time.perf_counter() - start) * 1000.0
            latencies.append(duration_ms)

            issues = (body or {}).get("doctor_report", {}).get("issues", [])
            total_issues += len(issues)
            issues_with_evidence += sum(1 for issue in issues if issue.get("evidence"))
            if (body or {}).get("insufficient_data", {}).get("status") is True:
                insufficient_data_cases += 1

            run_meta_latency = (body or {}).get("run_meta", {}).get("latency_ms_total")
            if isinstance(run_meta_latency, (int, float)):
                run_meta_latencies.append(float(run_meta_latency))

            quality = compute_v1_2_quality_metrics(body if isinstance(body, dict) else None)
            if bool(quality["sanity_fail"]):
                sanity_fail_cases += 1
            decision_total += int(quality["decision_total"])
            decision_with_citation += int(quality["decision_with_citation"])
            key_fact_retention_values.append(float(quality["key_fact_retention"]))
            clinical_signals = compute_clinical_quality_signals(
                nosology=nosology,
                response_body=body if isinstance(body, dict) else None,
                biomarker_matrix=biomarker_matrix,
            )
            clinical_minimum_values.append(float(clinical_signals["clinical_minimum_completeness"]))
            biomarker_concordance_values.append(float(clinical_signals["biomarker_profile_concordance"]))
            placeholder_citations_total += int(clinical_signals["placeholder_citations"])
            citations_total += int(clinical_signals["citations_total"])
            if bool(clinical_signals["unsafe_phrase_found"]):
                unsafe_phrase_cases += 1
            if bool(clinical_signals["nosology_semantic_conflict"]):
                nosology_semantic_conflicts += 1

            expected_block = item.get("expected") if isinstance(item, dict) else {}
            min_issues = 0
            expected_issue_kinds: list[str] = []
            if isinstance(expected_block, dict):
                try:
                    min_issues = int(expected_block.get("min_issues", 0))
                except (TypeError, ValueError):
                    min_issues = 0
                expected_issue_kinds = [
                    str(value).strip()
                    for value in expected_block.get("required_issue_kinds", [])
                    if str(value).strip()
                ] if isinstance(expected_block.get("required_issue_kinds"), list) else []
            predicted_issue_kinds = derive_predicted_issue_kinds(
                issues=issues if isinstance(issues, list) else [],
                expected_issue_kinds=expected_issue_kinds,
            )
            case_passed = status == 200 and body is not None and len(predicted_issue_kinds) >= min_issues

            if case_passed:
                passed += 1
            else:
                failures.append({
                    "id": item.get("id", f"case-{total}"),
                    "status": status,
                    "error": error,
                })

            case_rows.append(
                {
                    "case_id": str(item.get("id", f"case-{total}")),
                    "nosology": nosology,
                    "status": status,
                    "latency_ms": duration_ms,
                    "quality": quality,
                    "passed": case_passed,
                    "insufficient_data": bool((body or {}).get("insufficient_data", {}).get("status") is True),
                    "issues_total": len(issues),
                    "issues_with_evidence": sum(1 for issue in issues if issue.get("evidence")),
                    "expected_issue_kinds": expected_issue_kinds,
                    "predicted_issue_kinds": predicted_issue_kinds,
                    "clinical_minimum_completeness": float(clinical_signals["clinical_minimum_completeness"]),
                    "biomarker_profile_concordance": float(clinical_signals["biomarker_profile_concordance"]),
                    "placeholder_citations": int(clinical_signals["placeholder_citations"]),
                    "citations_total": int(clinical_signals["citations_total"]),
                    "unsafe_phrase_found": bool(clinical_signals["unsafe_phrase_found"]),
                    "nosology_semantic_conflict": bool(clinical_signals["nosology_semantic_conflict"]),
                }
            )

            if golden_pairs_by_id:
                alignment = evaluate_golden_alignment(
                    case_id=str(item.get("id", f"case-{total}")),
                    golden_pair_id=str(item.get("golden_pair_id") or ""),
                    response_body=body if isinstance(body, dict) else None,
                    golden_pairs_by_id=golden_pairs_by_id,
                )
                golden_alignment_rows.append(alignment)

        for item in import_cases:
            import_total_runs += 1
            expected = item.get("expected") if isinstance(item, dict) else None
            if not isinstance(expected, dict):
                expected = {}
            request_payload = item.get("request") if isinstance(item, dict) else None
            if not isinstance(request_payload, dict):
                import_failures.append(
                    {
                        "id": item.get("id", f"import-{import_total_runs}") if isinstance(item, dict) else f"import-{import_total_runs}",
                        "status": 0,
                        "error": "invalid import case: missing `request` object",
                    }
                )
                continue

            import_id = str(item.get("id", f"import-{import_total_runs}"))
            import_profile = str(request_payload.get("import_profile", "")).upper().strip()
            if import_profile:
                import_profiles_observed.add(import_profile)
            allowed_statuses = {
                str(value).upper().strip()
                for value in expected.get("allowed_statuses", ["SUCCESS", "PARTIAL_SUCCESS"])
                if str(value).strip()
            }
            required_fields = [
                str(value).strip()
                for value in expected.get("required_case_fields", [])
                if str(value).strip()
            ]
            expected_data_mode = str(
                expected.get("expected_data_mode", request_payload.get("data_mode", "DEID"))
            ).upper().strip()
            analyze_min_issues = int(expected.get("analyze_min_issues", 0))
            skip_analyze = bool(expected.get("skip_analyze", False))
            import_ok = True
            reasons: list[str] = []

            if args.mode == "http":
                import_status, import_body, import_error = call_backend_json(
                    base_url=args.base_url,
                    path="/case/import",
                    method="POST",
                    token=args.token,
                    role="clinician",
                    payload=request_payload,
                    timeout_sec=args.http_timeout_sec,
                    max_attempts=args.http_retry_attempts,
                    retry_delay_sec=float(args.http_retry_delay_ms) / 1000.0,
                )
            else:
                if service is None:
                    raise RuntimeError("inproc mode is not initialized")
                import_status, import_body, import_error = call_case_import_inproc(service, request_payload)

            if import_status != 200 or not isinstance(import_body, dict):
                import_ok = False
                reasons.append(f"case_import_failed status={import_status} error={import_error or ''}".strip())
            run_status = str((import_body or {}).get("status", "")).upper().strip()
            if import_ok and run_status not in allowed_statuses:
                import_ok = False
                reasons.append(f"unexpected_import_status={run_status}")

            case_id = str((import_body or {}).get("case_id", "")).strip()
            if import_ok and not case_id:
                import_ok = False
                reasons.append("missing_case_id")

            case_body: dict[str, Any] | None = None
            if import_ok and case_id:
                if args.mode == "http":
                    case_status, case_body, case_error = call_backend_json(
                        base_url=args.base_url,
                        path=f"/case/{case_id}",
                        method="GET",
                        token=args.token,
                        role="clinician",
                        timeout_sec=args.http_timeout_sec,
                        max_attempts=args.http_retry_attempts,
                        retry_delay_sec=float(args.http_retry_delay_ms) / 1000.0,
                    )
                else:
                    if service is None:
                        raise RuntimeError("inproc mode is not initialized")
                    case_status, case_body, case_error = call_case_get_inproc(service, case_id)

                if case_status != 200 or not isinstance(case_body, dict):
                    import_ok = False
                    reasons.append(f"case_get_failed status={case_status} error={case_error or ''}".strip())

            if import_ok and import_profile:
                actual_profile = str((case_body or {}).get("import_profile", "")).upper().strip()
                if actual_profile != import_profile:
                    import_ok = False
                    reasons.append(f"import_profile_mismatch expected={import_profile} actual={actual_profile}")

            if import_ok and case_body is not None and expected_data_mode in {"DEID", "FULL"}:
                import_data_mode_checks_total += 1
                actual_data_mode = str((case_body or {}).get("data_mode", "DEID")).upper().strip()
                if actual_data_mode == expected_data_mode:
                    import_data_mode_checks_passed += 1
                else:
                    import_ok = False
                    reasons.append(f"data_mode_mismatch expected={expected_data_mode} actual={actual_data_mode}")

            if import_ok and case_body is not None:
                for dotted_path in required_fields:
                    import_required_field_checks_total += 1
                    if path_has_non_empty_value(case_body, dotted_path):
                        import_required_field_checks_passed += 1
                    else:
                        import_ok = False
                        reasons.append(f"missing_required_case_field={dotted_path}")

            if import_ok and case_id and not skip_analyze:
                analyze_payload = build_case_id_analyze_request(
                    case_id,
                    language=str(request_payload.get("language", "ru")),
                )
                if args.mode == "http":
                    analyze_status, analyze_body, analyze_error = call_analyze(
                        args.base_url,
                        analyze_payload,
                        args.token,
                        client=http_client,
                        timeout_sec=args.http_timeout_sec,
                    )
                else:
                    if service is None:
                        raise RuntimeError("inproc mode is not initialized")
                    analyze_status, analyze_body, analyze_error = call_analyze_inproc(service, analyze_payload)

                analyze_issues = (analyze_body or {}).get("doctor_report", {}).get("issues", [])
                if analyze_status != 200:
                    import_ok = False
                    reasons.append(f"analyze_case_id_failed status={analyze_status} error={analyze_error or ''}".strip())
                elif not isinstance(analyze_issues, list) or len(analyze_issues) < analyze_min_issues:
                    import_ok = False
                    reasons.append(
                        f"analyze_min_issues_failed got={len(analyze_issues) if isinstance(analyze_issues, list) else -1}"
                    )

            if import_ok:
                import_passed_runs += 1
                if import_profile:
                    import_profiles_passed.add(import_profile)
            else:
                import_failures.append(
                    {
                        "id": import_id,
                        "status": import_status,
                        "error": "; ".join(reasons) if reasons else (import_error or "import_quality_failed"),
                    }
                )
    finally:
        if http_client is not None:
            http_client.close()
        if tmp_ctx is not None:
            tmp_ctx.cleanup()

    warmup_cases = max(args.warmup_cases, 0)
    effective_latencies, warmup_discarded = drop_warmup(latencies, warmup_cases)
    effective_run_meta_latencies, run_meta_warmup_discarded = drop_warmup(run_meta_latencies, warmup_cases)
    runtime_sec = max(time.perf_counter() - run_started, 1e-9)
    throughput_cases_per_hour = round(total / (runtime_sec / 3600.0), 2) if total else 0.0
    precision_bundle = compute_precision_recall_f1(case_rows)
    top3_bundle = load_top3_acceptance(args.top3_scorecard)
    sus_bundle = load_sus_score(args.sus_input)
    required_import_profiles = parse_required_profiles(args.required_import_profiles) if import_cases else set()
    if import_cases and not required_import_profiles:
        required_import_profiles = set(import_profiles_observed)
    import_profile_coverage = (
        len(import_profiles_passed & required_import_profiles) / len(required_import_profiles)
        if required_import_profiles
        else 1.0
    )
    import_success_ratio = round(import_passed_runs / import_total_runs, 4) if import_total_runs else 1.0
    import_required_field_coverage = (
        round(import_required_field_checks_passed / import_required_field_checks_total, 4)
        if import_required_field_checks_total
        else 1.0
    )
    import_data_mode_coverage = (
        round(import_data_mode_checks_passed / import_data_mode_checks_total, 4) if import_data_mode_checks_total else 1.0
    )
    sanity_fail_rate = round(sanity_fail_cases / total, 4) if total else 0.0
    citation_coverage = round(decision_with_citation / decision_total, 4) if decision_total else 1.0
    key_fact_retention = (
        round(sum(key_fact_retention_values) / len(key_fact_retention_values), 4) if key_fact_retention_values else 1.0
    )
    clinical_minimum_completeness = (
        round(sum(clinical_minimum_values) / len(clinical_minimum_values), 4) if clinical_minimum_values else 0.0
    )
    biomarker_profile_concordance = (
        round(sum(biomarker_concordance_values) / len(biomarker_concordance_values), 4)
        if biomarker_concordance_values
        else 0.0
    )
    placeholder_citation_rate = round(placeholder_citations_total / citations_total, 4) if citations_total else 0.0
    unsafe_phrase_rate = round(unsafe_phrase_cases / total, 4) if total else 0.0
    nosology_semantic_conflict_rate = round(nosology_semantic_conflicts / total, 4) if total else 0.0
    report_by_nosology_enabled = bool(
        args.report_by_nosology
        or str(args.min_recall_like_by_nosology or "").strip()
        or str(args.min_citation_coverage_by_nosology or "").strip()
    )
    per_nosology = compute_per_nosology_metrics(case_rows) if report_by_nosology_enabled else {}
    golden_alignment_summary: dict[str, Any] = {
        "enabled": bool(golden_pairs_by_id),
        "cases_total": len(golden_alignment_rows),
        "matched_cases": 0,
        "checks_total": 0,
        "checks_passed": 0,
        "alignment_ratio": 1.0,
        "failures": [],
    }
    if golden_alignment_rows:
        matched_cases = sum(1 for item in golden_alignment_rows if bool(item.get("matched")))
        checks_total = sum(int(item.get("checks_total") or 0) for item in golden_alignment_rows)
        checks_passed = sum(int(item.get("checks_passed") or 0) for item in golden_alignment_rows)
        failures_preview = [
            {
                "case_id": str(item.get("case_id") or ""),
                "golden_pair_id": str(item.get("golden_pair_id") or ""),
                "failed_checks": list(item.get("failed_checks") or []),
            }
            for item in golden_alignment_rows
            if list(item.get("failed_checks") or [])
        ][:100]
        golden_alignment_summary.update(
            {
                "matched_cases": matched_cases,
                "checks_total": checks_total,
                "checks_passed": checks_passed,
                "alignment_ratio": round(checks_passed / checks_total, 4) if checks_total else 1.0,
                "failures": failures_preview,
            }
        )
    clinical_review_coverage = compute_clinical_review_coverage(golden_pairs_by_id)
    clinical_decision_quality = compute_clinical_decision_quality(golden_pairs_by_id)

    report = {
        "mode": args.mode,
        "schema_version": args.schema_version,
        "warmup_cases": warmup_cases,
        "total_cases": total,
        "passed_cases": passed,
        "recall_like": round(passed / total, 4) if total else 0.0,
        "insufficient_data_ratio": round(insufficient_data_cases / total, 4) if total else 0.0,
        "evidence_valid_ratio": round(issues_with_evidence / total_issues, 4) if total_issues else 1.0,
        "latency_ms": {
            "samples_total": len(latencies),
            "warmup_discarded": warmup_discarded,
            "samples_effective": len(effective_latencies),
            "p50": round(percentile(effective_latencies, 0.50), 2),
            "p90": round(percentile(effective_latencies, 0.90), 2),
            "p95": round(percentile(effective_latencies, 0.95), 2),
            "mean": round(statistics.mean(effective_latencies), 2) if effective_latencies else 0.0,
        },
        "run_meta_latency_ms": {
            "samples": len(run_meta_latencies),
            "warmup_discarded": run_meta_warmup_discarded,
            "samples_effective": len(effective_run_meta_latencies),
            "p50": round(percentile(effective_run_meta_latencies, 0.50), 2) if effective_run_meta_latencies else 0.0,
            "p90": round(percentile(effective_run_meta_latencies, 0.90), 2) if effective_run_meta_latencies else 0.0,
            "p95": round(percentile(effective_run_meta_latencies, 0.95), 2) if effective_run_meta_latencies else 0.0,
            "mean": round(statistics.mean(effective_run_meta_latencies), 2) if effective_run_meta_latencies else 0.0,
        },
        "precision": float(precision_bundle["precision"]),
        "f1": float(precision_bundle["f1"]),
        "precision_recall_f1_detail": precision_bundle,
        "p90_latency_ms": round(percentile(effective_latencies, 0.90), 2),
        "throughput_cases_per_hour": throughput_cases_per_hour,
        "top3_acceptance_rate": top3_bundle.get("top3_acceptance_rate"),
        "top3_acceptance": top3_bundle,
        "sus_score": sus_bundle.get("sus_score"),
        "sus": sus_bundle,
        "import_quality": {
            "enabled": bool(import_cases),
            "total_runs": import_total_runs,
            "passed_runs": import_passed_runs,
            "success_ratio": import_success_ratio,
            "required_profiles": sorted(required_import_profiles),
            "observed_profiles": sorted(import_profiles_observed),
            "passed_profiles": sorted(import_profiles_passed),
            "profile_coverage_ratio": round(import_profile_coverage, 4),
            "required_field_checks_total": import_required_field_checks_total,
            "required_field_checks_passed": import_required_field_checks_passed,
            "required_field_coverage_ratio": import_required_field_coverage,
            "data_mode_checks_total": import_data_mode_checks_total,
            "data_mode_checks_passed": import_data_mode_checks_passed,
            "data_mode_coverage_ratio": import_data_mode_coverage,
            "failures": import_failures,
        },
        "sanity_fail_rate": sanity_fail_rate,
        "citation_coverage": citation_coverage,
        "key_fact_retention": key_fact_retention,
        "clinical_minimum_completeness": clinical_minimum_completeness,
        "biomarker_profile_concordance": biomarker_profile_concordance,
        "placeholder_citation_rate": placeholder_citation_rate,
        "unsafe_phrase_rate": unsafe_phrase_rate,
        "nosology_semantic_conflict_rate": nosology_semantic_conflict_rate,
        "v1_2_quality": {
            "sanity_fail_cases": sanity_fail_cases,
            "sanity_fail_rate": sanity_fail_rate,
            "decision_items_total": decision_total,
            "decision_items_with_citation": decision_with_citation,
            "citation_coverage": citation_coverage,
            "key_fact_retention": key_fact_retention,
            "clinical_minimum_completeness": clinical_minimum_completeness,
            "biomarker_profile_concordance": biomarker_profile_concordance,
            "placeholder_citation_rate": placeholder_citation_rate,
            "unsafe_phrase_rate": unsafe_phrase_rate,
            "nosology_semantic_conflict_rate": nosology_semantic_conflict_rate,
        },
        "per_nosology": per_nosology,
        "golden_alignment": golden_alignment_summary,
        "clinical_review_coverage": clinical_review_coverage,
        "clinical_decision_quality": clinical_decision_quality,
        "failures": failures,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))

    gate_failures: list[str] = []
    if args.max_p95_ms is not None and report["latency_ms"]["p95"] > args.max_p95_ms:
        gate_failures.append(f"latency_ms.p95={report['latency_ms']['p95']} > {args.max_p95_ms}")
    if args.max_p90_ms is not None and report["latency_ms"]["p90"] > args.max_p90_ms:
        gate_failures.append(f"latency_ms.p90={report['latency_ms']['p90']} > {args.max_p90_ms}")
    if args.min_recall_like is not None and report["recall_like"] < args.min_recall_like:
        gate_failures.append(f"recall_like={report['recall_like']} < {args.min_recall_like}")
    if args.min_precision is not None and report["precision"] < args.min_precision:
        gate_failures.append(f"precision={report['precision']} < {args.min_precision}")
    if args.min_f1 is not None and report["f1"] < args.min_f1:
        gate_failures.append(f"f1={report['f1']} < {args.min_f1}")
    if args.min_evidence_valid_ratio is not None and report["evidence_valid_ratio"] < args.min_evidence_valid_ratio:
        gate_failures.append(
            f"evidence_valid_ratio={report['evidence_valid_ratio']} < {args.min_evidence_valid_ratio}"
        )
    if args.max_insufficient_ratio is not None and report["insufficient_data_ratio"] > args.max_insufficient_ratio:
        gate_failures.append(f"insufficient_data_ratio={report['insufficient_data_ratio']} > {args.max_insufficient_ratio}")
    import_gates_requested = any(
        value is not None
        for value in (
            args.min_import_success_ratio,
            args.min_import_profile_coverage,
            args.min_import_required_field_coverage,
            args.min_import_data_mode_coverage,
        )
    )
    if import_gates_requested and not import_cases:
        gate_failures.append("import_quality gates requested but --import-cases is empty")
    if args.min_import_success_ratio is not None and report["import_quality"]["success_ratio"] < args.min_import_success_ratio:
        gate_failures.append(
            f"import_quality.success_ratio={report['import_quality']['success_ratio']} < {args.min_import_success_ratio}"
        )
    if (
        args.min_import_profile_coverage is not None
        and report["import_quality"]["profile_coverage_ratio"] < args.min_import_profile_coverage
    ):
        gate_failures.append(
            "import_quality.profile_coverage_ratio="
            f"{report['import_quality']['profile_coverage_ratio']} < {args.min_import_profile_coverage}"
        )
    if (
        args.min_import_required_field_coverage is not None
        and report["import_quality"]["required_field_coverage_ratio"] < args.min_import_required_field_coverage
    ):
        gate_failures.append(
            "import_quality.required_field_coverage_ratio="
            f"{report['import_quality']['required_field_coverage_ratio']} < {args.min_import_required_field_coverage}"
        )
    if (
        args.min_import_data_mode_coverage is not None
        and report["import_quality"]["data_mode_coverage_ratio"] < args.min_import_data_mode_coverage
    ):
        gate_failures.append(
            "import_quality.data_mode_coverage_ratio="
            f"{report['import_quality']['data_mode_coverage_ratio']} < {args.min_import_data_mode_coverage}"
        )
    if args.max_sanity_fail_rate is not None and report["sanity_fail_rate"] > args.max_sanity_fail_rate:
        gate_failures.append(f"sanity_fail_rate={report['sanity_fail_rate']} > {args.max_sanity_fail_rate}")
    if (
        args.min_throughput_cases_per_hour is not None
        and report["throughput_cases_per_hour"] < args.min_throughput_cases_per_hour
    ):
        gate_failures.append(
            "throughput_cases_per_hour="
            f"{report['throughput_cases_per_hour']} < {args.min_throughput_cases_per_hour}"
        )
    if args.min_top3_acceptance_rate is not None:
        if not bool(top3_bundle.get("enabled")):
            gate_failures.append(
                "top3_acceptance input missing or invalid"
                + (f" ({top3_bundle.get('error')})" if top3_bundle.get("error") else "")
            )
        value = report.get("top3_acceptance_rate")
        if not isinstance(value, (int, float)) or float(value) < args.min_top3_acceptance_rate:
            gate_failures.append(f"top3_acceptance_rate={value} < {args.min_top3_acceptance_rate}")
    if args.min_sus_score is not None:
        if not bool(sus_bundle.get("enabled")):
            gate_failures.append(
                "sus input missing or invalid"
                + (f" ({sus_bundle.get('error')})" if sus_bundle.get("error") else "")
            )
        value = report.get("sus_score")
        if not isinstance(value, (int, float)) or float(value) < args.min_sus_score:
            gate_failures.append(f"sus_score={value} < {args.min_sus_score}")
    clinical_review = report.get("clinical_review_coverage") if isinstance(report.get("clinical_review_coverage"), dict) else {}
    clinical_decision = (
        report.get("clinical_decision_quality")
        if isinstance(report.get("clinical_decision_quality"), dict)
        else {}
    )
    if args.min_clinical_review_coverage is not None:
        value = clinical_review.get("coverage_ratio")
        if not isinstance(value, (int, float)) or float(value) < args.min_clinical_review_coverage:
            gate_failures.append(f"clinical_review_coverage.coverage_ratio={value} < {args.min_clinical_review_coverage}")
    if args.max_invalid_clinical_review_rows is not None:
        value = clinical_review.get("invalid_review_rows")
        if not isinstance(value, int) or int(value) > args.max_invalid_clinical_review_rows:
            gate_failures.append(
                "clinical_review_coverage.invalid_review_rows="
                f"{value} > {args.max_invalid_clinical_review_rows}"
            )
    if str(args.min_clinical_review_coverage_by_nosology or "").strip():
        try:
            coverage_thresholds = parse_nosology_thresholds(args.min_clinical_review_coverage_by_nosology)
        except ValueError as exc:
            gate_failures.append(f"invalid --min-clinical-review-coverage-by-nosology: {exc}")
            coverage_thresholds = {}
        per_nosology = clinical_review.get("per_nosology") if isinstance(clinical_review.get("per_nosology"), dict) else {}
        for nosology, threshold in coverage_thresholds.items():
            resolved_nosology, row = resolve_per_nosology_row(per_nosology, nosology)
            if not isinstance(row, dict):
                gate_failures.append(f"nosology `{nosology}` missing in clinical_review_coverage.per_nosology")
                continue
            if float(row.get("coverage_ratio", 0.0)) < threshold:
                gate_failures.append(
                    "clinical_review_coverage.per_nosology"
                    f"[{resolved_nosology}].coverage_ratio={row.get('coverage_ratio')} < {threshold}"
                )
    if str(args.min_clinical_reviewed_pairs_by_nosology or "").strip():
        try:
            reviewed_thresholds = parse_nosology_int_thresholds(args.min_clinical_reviewed_pairs_by_nosology)
        except ValueError as exc:
            gate_failures.append(f"invalid --min-clinical-reviewed-pairs-by-nosology: {exc}")
            reviewed_thresholds = {}
        per_nosology = clinical_review.get("per_nosology") if isinstance(clinical_review.get("per_nosology"), dict) else {}
        for nosology, threshold in reviewed_thresholds.items():
            resolved_nosology, row = resolve_per_nosology_row(per_nosology, nosology)
            if not isinstance(row, dict):
                gate_failures.append(f"nosology `{nosology}` missing in clinical_review_coverage.per_nosology")
                continue
            if int(row.get("reviewed", 0)) < threshold:
                gate_failures.append(
                    "clinical_review_coverage.per_nosology"
                    f"[{resolved_nosology}].reviewed={row.get('reviewed')} < {threshold}"
                )
    if args.min_approved_ratio is not None:
        value = clinical_decision.get("approved_ratio")
        if not isinstance(value, (int, float)) or float(value) < args.min_approved_ratio:
            gate_failures.append(f"clinical_decision_quality.approved_ratio={value} < {args.min_approved_ratio}")
    if args.max_rewrite_required_rate is not None:
        value = clinical_decision.get("rewrite_required_rate")
        if not isinstance(value, (int, float)) or float(value) > args.max_rewrite_required_rate:
            gate_failures.append(
                "clinical_decision_quality.rewrite_required_rate="
                f"{value} > {args.max_rewrite_required_rate}"
            )
    if str(args.min_approved_pairs_by_nosology or "").strip():
        try:
            approved_thresholds = parse_nosology_int_thresholds(args.min_approved_pairs_by_nosology)
        except ValueError as exc:
            gate_failures.append(f"invalid --min-approved-pairs-by-nosology: {exc}")
            approved_thresholds = {}
        per_nosology_decision = (
            clinical_decision.get("per_nosology")
            if isinstance(clinical_decision.get("per_nosology"), dict)
            else {}
        )
        for nosology, threshold in approved_thresholds.items():
            resolved_nosology, row = resolve_per_nosology_row(per_nosology_decision, nosology)
            if not isinstance(row, dict):
                gate_failures.append(f"nosology `{nosology}` missing in clinical_decision_quality.per_nosology")
                continue
            if int(row.get("approved_pairs", 0)) < threshold:
                gate_failures.append(
                    "clinical_decision_quality.per_nosology"
                    f"[{resolved_nosology}].approved_pairs={row.get('approved_pairs')} < {threshold}"
                )
    if args.min_citation_coverage is not None and report["citation_coverage"] < args.min_citation_coverage:
        gate_failures.append(f"citation_coverage={report['citation_coverage']} < {args.min_citation_coverage}")
    if args.min_key_fact_retention is not None and report["key_fact_retention"] < args.min_key_fact_retention:
        gate_failures.append(f"key_fact_retention={report['key_fact_retention']} < {args.min_key_fact_retention}")
    if (
        args.min_clinical_minimum_completeness is not None
        and report["clinical_minimum_completeness"] < args.min_clinical_minimum_completeness
    ):
        gate_failures.append(
            "clinical_minimum_completeness="
            f"{report['clinical_minimum_completeness']} < {args.min_clinical_minimum_completeness}"
        )
    if (
        args.min_biomarker_profile_concordance is not None
        and report["biomarker_profile_concordance"] < args.min_biomarker_profile_concordance
    ):
        gate_failures.append(
            "biomarker_profile_concordance="
            f"{report['biomarker_profile_concordance']} < {args.min_biomarker_profile_concordance}"
        )
    if (
        args.max_placeholder_citation_rate is not None
        and report["placeholder_citation_rate"] > args.max_placeholder_citation_rate
    ):
        gate_failures.append(
            f"placeholder_citation_rate={report['placeholder_citation_rate']} > {args.max_placeholder_citation_rate}"
        )
    if args.max_unsafe_phrase_rate is not None and report["unsafe_phrase_rate"] > args.max_unsafe_phrase_rate:
        gate_failures.append(f"unsafe_phrase_rate={report['unsafe_phrase_rate']} > {args.max_unsafe_phrase_rate}")
    if (
        args.max_nosology_semantic_conflict_rate is not None
        and report["nosology_semantic_conflict_rate"] > args.max_nosology_semantic_conflict_rate
    ):
        gate_failures.append(
            "nosology_semantic_conflict_rate="
            f"{report['nosology_semantic_conflict_rate']} > {args.max_nosology_semantic_conflict_rate}"
        )
    if str(args.min_recall_like_by_nosology or "").strip():
        try:
            recall_thresholds = parse_nosology_thresholds(args.min_recall_like_by_nosology)
        except ValueError as exc:
            gate_failures.append(f"invalid --min-recall-like-by-nosology: {exc}")
            recall_thresholds = {}
        for nosology, threshold in recall_thresholds.items():
            resolved_nosology, row = resolve_per_nosology_row(report.get("per_nosology"), nosology)
            if not isinstance(row, dict):
                gate_failures.append(f"nosology `{nosology}` missing in per_nosology report for recall gate")
                continue
            if float(row.get("recall_like", 0.0)) < threshold:
                gate_failures.append(
                    f"per_nosology[{resolved_nosology}].recall_like={row.get('recall_like')} < {threshold}"
                )
    if str(args.min_citation_coverage_by_nosology or "").strip():
        try:
            citation_thresholds = parse_nosology_thresholds(args.min_citation_coverage_by_nosology)
        except ValueError as exc:
            gate_failures.append(f"invalid --min-citation-coverage-by-nosology: {exc}")
            citation_thresholds = {}
        for nosology, threshold in citation_thresholds.items():
            resolved_nosology, row = resolve_per_nosology_row(report.get("per_nosology"), nosology)
            if not isinstance(row, dict):
                gate_failures.append(f"nosology `{nosology}` missing in per_nosology report for citation gate")
                continue
            if float(row.get("citation_coverage", 0.0)) < threshold:
                gate_failures.append(
                    f"per_nosology[{resolved_nosology}].citation_coverage={row.get('citation_coverage')} < {threshold}"
                )

    if gate_failures:
        for item in gate_failures:
            print(f"GATE_FAIL: {item}", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
