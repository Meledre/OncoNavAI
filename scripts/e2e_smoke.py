#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any

DEFAULT_GASTRIC_PACK_DIR = "/Users/meledre/Downloads/json_pack"
GASTRIC_UPLOAD_PAYLOADS = (
    "admin_upload_minzdrav_574_1_unknown.json",
    "admin_upload_russco_2023_22_unknown.json",
)
# Prefer KIN text payload for smoke stability under DEID+PII guard.
# Keep legacy file name as fallback for packs that do not contain the KIN variant.
GASTRIC_CASE_IMPORT_PAYLOADS = (
    "case_import_kin_pdf_text_stomach.json",
    "case_import_case_pdf_stomach.json",
)
GASTRIC_ANALYZE_PAYLOAD = "analyze_next_steps_case_pdf_stomach_case_id_minzdrav.json"

DISEASE_ID_C16 = "a76e5701-e3b1-54fd-a4b8-001bcd63de6e"
DISEASE_ID_C34 = "2efcb0a0-2b4a-5f44-a247-9e1c6d9a7f42"
DISEASE_ID_C50 = "9d9d8f58-2a2d-5c9d-b43d-7d4af8854d38"
DISEASE_ID_DECOY = "00000000-0000-0000-0000-000000000000"


def _default_http_timeout_sec() -> int:
    raw = str(os.environ.get("ONCO_SMOKE_HTTP_TIMEOUT_SEC", "30")).strip()
    try:
        value = int(raw)
    except ValueError:
        value = 30
    return max(5, min(value, 900))


DEFAULT_HTTP_TIMEOUT_SEC = _default_http_timeout_sec()


def _default_analyze_http_timeout_sec() -> int:
    raw = str(os.environ.get("ONCO_SMOKE_ANALYZE_HTTP_TIMEOUT_SEC", "")).strip()
    default_value = max(DEFAULT_HTTP_TIMEOUT_SEC, 300)
    if not raw:
        return default_value
    try:
        value = int(raw)
    except ValueError:
        value = default_value
    return max(30, min(value, 1800))


DEFAULT_ANALYZE_HTTP_TIMEOUT_SEC = _default_analyze_http_timeout_sec()


def _default_smoke_doc_version() -> str:
    raw = str(os.environ.get("ONCO_SMOKE_DOC_VERSION", "smoke-v1")).strip()
    return raw[:80] if raw else "smoke-v1"


def _skip_reindex_requested() -> bool:
    raw = str(os.environ.get("ONCO_SMOKE_SKIP_REINDEX", "")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _http_call(
    *,
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: int = DEFAULT_HTTP_TIMEOUT_SEC,
) -> tuple[int, str]:
    status, text, _ = _http_call_with_headers(
        method=method,
        url=url,
        headers=headers,
        body=body,
        timeout=timeout,
    )
    return status, text


def _http_call_with_headers(
    *,
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: int = DEFAULT_HTTP_TIMEOUT_SEC,
) -> tuple[int, str, dict[str, str]]:
    request = urllib.request.Request(url, method=method, data=body, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            normalized_headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
            return response.status, response.read().decode("utf-8"), normalized_headers
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8") if exc.fp else ""
        error_headers = {str(key).lower(): str(value) for key, value in (exc.headers.items() if exc.headers else [])}
        return exc.code, detail, error_headers


def _request_json(
    *,
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    payload: dict | None = None,
    timeout: int | None = None,
) -> tuple[int, dict]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    merged_headers = {"content-type": "application/json", **(headers or {})}
    request_timeout = int(timeout) if timeout is not None else DEFAULT_HTTP_TIMEOUT_SEC
    normalized_url = str(url).rstrip("/").lower()
    if normalized_url.endswith("/api/analyze") or normalized_url.endswith("/api/patient/analyze"):
        request_timeout = max(request_timeout, DEFAULT_ANALYZE_HTTP_TIMEOUT_SEC)
    status, text = _http_call(method=method, url=url, headers=merged_headers, body=body, timeout=request_timeout)
    if not text:
        return status, {}
    try:
        return status, json.loads(text)
    except json.JSONDecodeError:
        return status, {"raw": text}


def _build_multipart_body(
    fields: dict[str, str],
    *,
    file_name: str,
    file_bytes: bytes,
    mime_type: str = "application/pdf",
) -> tuple[str, bytes]:
    boundary = f"----OncoAISmoke{int(time.time() * 1000)}"
    lines: list[bytes] = []

    for key, value in fields.items():
        lines.append(f"--{boundary}\r\n".encode("utf-8"))
        lines.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        lines.append(value.encode("utf-8"))
        lines.append(b"\r\n")

    lines.append(f"--{boundary}\r\n".encode("utf-8"))
    lines.append(
        f'Content-Disposition: form-data; name="file"; filename="{file_name}"\r\n'.encode("utf-8")
    )
    lines.append(f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"))
    lines.append(file_bytes)
    lines.append(b"\r\n")
    lines.append(f"--{boundary}--\r\n".encode("utf-8"))
    return boundary, b"".join(lines)


def _load_pdf(path: str | None) -> tuple[str, bytes]:
    if path:
        file_path = Path(path)
        return file_path.name, file_path.read_bytes()

    # Sufficient for MVP smoke ingestion flow.
    synthetic_pdf = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
    return "smoke.pdf", synthetic_pdf


def _pdf_flow_input(pack_dir: str, *, case_file: str = "") -> tuple[str, str, str]:
    if str(case_file or "").strip():
        file_path = Path(str(case_file).strip())
        if not file_path.exists():
            raise RuntimeError(f"case file not found: {file_path}")
        raw = file_path.read_bytes()
        return file_path.name, _encode_base64_content(raw), _guess_mime_type(file_path.name)

    api_requests = Path(pack_dir) / "api_requests"
    if api_requests.exists():
        for file_name in GASTRIC_UPLOAD_PAYLOADS:
            payload_path = api_requests / file_name
            if not payload_path.exists():
                continue
            payload = _load_json_payload(payload_path)
            content_base64 = str(payload.get("content_base64") or "").strip()
            filename = str(payload.get("filename") or "smoke.pdf").strip() or "smoke.pdf"
            if content_base64:
                try:
                    base64.b64decode(content_base64, validate=True)
                    return filename, content_base64, "application/pdf"
                except Exception:  # noqa: BLE001
                    continue

    fallback_name, fallback_bytes = _load_pdf(None)
    return fallback_name, _encode_base64_content(fallback_bytes), "application/pdf"


def _extract_patient_summary(payload: dict[str, Any]) -> str:
    patient_explain = payload.get("patient_explain") if isinstance(payload.get("patient_explain"), dict) else {}
    return str(patient_explain.get("summary") or patient_explain.get("summary_plain") or "").strip()


def _run_pdf_page_flow(base_url: str, *, pack_dir: str, case_file: str = "") -> dict[str, Any]:
    filename, content_base64, mime_type = _pdf_flow_input(pack_dir, case_file=case_file)

    import_status, import_payload = _request_json_with_role_retry(
        method="POST",
        url=f"{base_url.rstrip('/')}/api/case/import-file",
        base_url=base_url,
        role="clinician",
        payload={
            "filename": filename,
            "content_base64": content_base64,
            "mime_type": mime_type,
            "data_mode": "DEID",
        },
    )
    _require_ok(import_status, import_payload, "pdf page-flow import-file")
    case_id = str(import_payload.get("case_id") or "").strip()
    import_run_id = str(import_payload.get("import_run_id") or "").strip()
    if not case_id or not import_run_id:
        raise RuntimeError(f"pdf page-flow import payload incomplete: {import_payload}")

    analyze_status, analyze_payload = _request_json_with_role_retry(
        method="POST",
        url=f"{base_url.rstrip('/')}/api/analyze",
        base_url=base_url,
        role="clinician",
        payload={
            "schema_version": "0.2",
            "request_id": str(uuid.uuid4()),
            "query_type": "NEXT_STEPS",
            "sources": {"mode": "AUTO", "source_ids": ["minzdrav", "russco"]},
            "language": "ru",
            "case": {"case_id": case_id},
            "options": {"strict_evidence": True, "max_chunks": 40, "max_citations": 40, "timeout_ms": 120000},
        },
        extra_headers={"x-client-id": "e2e-pdf-page-flow"},
    )
    _require_ok(analyze_status, analyze_payload, "pdf page-flow doctor analyze")
    doctor_report = analyze_payload.get("doctor_report") if isinstance(analyze_payload.get("doctor_report"), dict) else {}
    if not doctor_report:
        raise RuntimeError(f"pdf page-flow doctor analyze missing doctor_report: {analyze_payload}")
    if not isinstance(analyze_payload.get("patient_explain"), dict):
        raise RuntimeError("pdf page-flow doctor analyze missing patient_explain")
    citation_count, sources_used, issues_count = _collect_pack_citation_metrics(analyze_payload)

    patient_status, patient_payload = _request_json_with_role_retry(
        method="POST",
        url=f"{base_url.rstrip('/')}/api/patient/analyze",
        base_url=base_url,
        role="patient",
        payload={
            "filename": filename,
            "content_base64": content_base64,
            "mime_type": mime_type,
            "request_id": str(uuid.uuid4()),
            "query_type": "NEXT_STEPS",
            "sources": {"mode": "AUTO", "source_ids": ["minzdrav", "russco"]},
            "language": "ru",
        },
    )
    _require_ok(patient_status, patient_payload, "pdf page-flow patient analyze")
    if "doctor_report" in patient_payload:
        raise RuntimeError(f"pdf page-flow patient payload leaked doctor_report: {patient_payload}")
    patient_summary = _extract_patient_summary(patient_payload)
    if not patient_summary:
        raise RuntimeError(f"pdf page-flow patient payload has empty summary: {patient_payload}")

    return {
        "doctor_case_id": case_id,
        "doctor_import_run_id": import_run_id,
        "doctor_issues_count": issues_count,
        "doctor_citations_count": citation_count,
        "doctor_sources_used": sources_used,
        "doctor_routing_meta": (
            analyze_payload.get("run_meta", {}).get("routing_meta", {})
            if isinstance(analyze_payload.get("run_meta"), dict)
            else {}
        ),
        "patient_case_id": str(patient_payload.get("case_id") or "").strip(),
        "patient_import_run_id": str(patient_payload.get("import_run_id") or "").strip(),
        "patient_summary_present": bool(patient_summary),
        "patient_routing_meta": (
            patient_payload.get("run_meta", {}).get("routing_meta", {})
            if isinstance(patient_payload.get("run_meta"), dict)
            else {}
        ),
    }


def _load_json_payload(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"gastric pack file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid gastric pack json: {path}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"gastric pack payload must be an object: {path}")
    return data


def _decode_base64_payload(raw_value: str, *, path: Path) -> bytes:
    value = str(raw_value).strip()
    if not value:
        raise RuntimeError(f"gastric pack payload has empty content_base64: {path}")
    try:
        return base64.b64decode(value, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"invalid content_base64 in gastric pack payload: {path}") from exc


def _encode_base64_content(raw: bytes) -> str:
    return base64.b64encode(raw).decode("utf-8")


def _guess_mime_type(file_name: str) -> str:
    normalized = str(file_name or "").strip().lower()
    if normalized.endswith(".txt") or normalized.endswith(".md"):
        return "text/plain"
    if normalized.endswith(".docx"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return "application/pdf"


def _json_list_field(values: list[str]) -> str:
    return json.dumps([str(item).strip() for item in values if str(item).strip()], ensure_ascii=False)


def _upload_doc_from_payload(
    base_url: str,
    payload: dict,
    *,
    payload_path: Path,
    action_label: str = "upload",
) -> dict[str, Any]:
    file_name = str(payload.get("filename") or "guideline.pdf").strip() or "guideline.pdf"
    file_bytes = _decode_base64_payload(str(payload.get("content_base64") or ""), path=payload_path)
    fields = {
        "doc_id": str(payload.get("doc_id") or "").strip(),
        "doc_version": str(payload.get("doc_version") or "").strip(),
        "source_set": str(payload.get("source_set") or "").strip(),
        "cancer_type": str(payload.get("cancer_type") or "").strip(),
        "language": str(payload.get("language") or "ru").strip(),
    }
    for field_name, field_value in fields.items():
        if not field_value:
            raise RuntimeError(f"{action_label} payload missing required field `{field_name}`: {payload_path}")

    disease_id = str(payload.get("disease_id") or "").strip()
    if disease_id:
        fields["disease_id"] = disease_id

    source_url = str(payload.get("source_url") or "").strip()
    if source_url:
        fields["source_url"] = source_url

    doc_kind = str(payload.get("doc_kind") or "").strip().lower()
    if doc_kind:
        fields["doc_kind"] = doc_kind

    icd10_prefixes = payload.get("icd10_prefixes")
    if isinstance(icd10_prefixes, list):
        normalized_prefixes = [str(item).strip().upper() for item in icd10_prefixes if str(item).strip()]
        if normalized_prefixes:
            fields["icd10_prefixes"] = _json_list_field(normalized_prefixes)

    nosology_keywords = payload.get("nosology_keywords")
    if isinstance(nosology_keywords, list):
        normalized_keywords = [str(item).strip() for item in nosology_keywords if str(item).strip()]
        if normalized_keywords:
            fields["nosology_keywords"] = _json_list_field(normalized_keywords)

    boundary, multipart_body = _build_multipart_body(
        fields,
        file_name=file_name,
        file_bytes=file_bytes,
        mime_type=_guess_mime_type(file_name),
    )
    upload_status, upload_text = _http_call(
        method="POST",
        url=f"{base_url.rstrip('/')}/api/admin/upload",
        headers=_role_headers(
            "admin",
            base_url=base_url,
            extra={"content-type": f"multipart/form-data; boundary={boundary}"},
        ),
        body=multipart_body,
    )
    try:
        upload_payload = json.loads(upload_text) if upload_text else {}
    except json.JSONDecodeError:
        upload_payload = {"raw": upload_text}
    _require_ok(upload_status, upload_payload, f"{action_label} ({payload_path.name})")
    return upload_payload if isinstance(upload_payload, dict) else {}


def _run_admin_doc_release_workflow(
    base_url: str,
    *,
    doc_id: str,
    doc_version: str,
) -> None:
    normalized_doc_id = str(doc_id or "").strip()
    normalized_doc_version = str(doc_version or "").strip()
    if not normalized_doc_id or not normalized_doc_version:
        raise RuntimeError("admin release workflow requires non-empty doc_id/doc_version")

    base_path = f"{base_url.rstrip('/')}/api/admin/docs/{normalized_doc_id}/{normalized_doc_version}"
    rechunk_status, rechunk_payload = _request_json_with_role_retry(
        method="POST",
        url=f"{base_path}/rechunk",
        base_url=base_url,
        role="admin",
    )
    _require_ok(rechunk_status, rechunk_payload, f"admin rechunk {normalized_doc_id}:{normalized_doc_version}")

    approve_status, approve_payload = _request_json_with_role_retry(
        method="POST",
        url=f"{base_path}/approve",
        base_url=base_url,
        role="admin",
    )
    _require_ok(approve_status, approve_payload, f"admin approve {normalized_doc_id}:{normalized_doc_version}")

    index_status, index_payload = _request_json_with_role_retry(
        method="POST",
        url=f"{base_path}/index",
        base_url=base_url,
        role="admin",
    )
    _require_ok(index_status, index_payload, f"admin index {normalized_doc_id}:{normalized_doc_version}")
    if str(index_payload.get("status") or "").upper() != "INDEXED":
        raise RuntimeError(f"admin index did not return INDEXED: {index_payload}")


def _collect_pack_citation_metrics(analyze_payload: dict) -> tuple[int, list[str], int]:
    doctor_report = analyze_payload.get("doctor_report") if isinstance(analyze_payload.get("doctor_report"), dict) else {}
    issues = doctor_report.get("issues") if isinstance(doctor_report.get("issues"), list) else []
    citations = doctor_report.get("citations") if isinstance(doctor_report.get("citations"), list) else []

    issue_count = len(issues)
    citation_id_set: set[str] = set()
    legacy_evidence_count = 0
    legacy_sources: set[str] = set()
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        for citation_id in issue.get("citation_ids") if isinstance(issue.get("citation_ids"), list) else []:
            normalized = str(citation_id).strip()
            if normalized:
                citation_id_set.add(normalized)
        evidence_list = issue.get("evidence") if isinstance(issue.get("evidence"), list) else []
        for evidence in evidence_list:
            if not isinstance(evidence, dict):
                continue
            legacy_evidence_count += 1
            source_from_evidence = str(evidence.get("source_id") or evidence.get("source_set") or "").strip()
            if source_from_evidence:
                legacy_sources.add(source_from_evidence)

    citation_count = len(citation_id_set)
    citations_by_id: dict[str, dict] = {}
    fallback_citation_count = 0
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        fallback_citation_count += 1
        citation_id = str(citation.get("citation_id") or "").strip()
        if citation_id:
            citations_by_id[citation_id] = citation

    sources_used: set[str] = set()
    for citation_id in citation_id_set:
        citation = citations_by_id.get(citation_id, {})
        source_id = str(citation.get("source_id") or "").strip()
        if source_id:
            sources_used.add(source_id)
    if citation_count == 0:
        for citation in citations:
            if not isinstance(citation, dict):
                continue
            source_id = str(citation.get("source_id") or "").strip()
            if source_id:
                sources_used.add(source_id)
        sources_used.update(legacy_sources)
        if fallback_citation_count > 0:
            citation_count = fallback_citation_count
        elif legacy_evidence_count > 0:
            citation_count = legacy_evidence_count

    patient_explain = analyze_payload.get("patient_explain")
    if isinstance(patient_explain, dict):
        for source in patient_explain.get("sources_used") if isinstance(patient_explain.get("sources_used"), list) else []:
            normalized = str(source).strip()
            if normalized:
                sources_used.add(normalized)

    run_meta = analyze_payload.get("run_meta") if isinstance(analyze_payload.get("run_meta"), dict) else {}
    routing_meta = run_meta.get("routing_meta") if isinstance(run_meta.get("routing_meta"), dict) else {}
    for source in routing_meta.get("source_ids") if isinstance(routing_meta.get("source_ids"), list) else []:
        normalized = str(source).strip()
        if normalized:
            sources_used.add(normalized)

    return citation_count, sorted(sources_used), issue_count


def _run_gastric_flow(base_url: str, *, max_attempts: int, pack_dir: str) -> dict:
    pack_root = Path(pack_dir)
    api_requests = pack_root / "api_requests"
    if not api_requests.exists():
        raise RuntimeError(f"ONCOAI_GASTRIC_PACK_DIR must contain api_requests/: {pack_root}")

    for file_name in GASTRIC_UPLOAD_PAYLOADS:
        payload_path = api_requests / file_name
        upload_payload = _load_json_payload(payload_path)
        # Ensure gastric docs contribute deterministic routing hints even when pack metadata is sparse.
        if str(upload_payload.get("doc_id") or "").strip() == "minzdrav_574_1":
            upload_payload.setdefault("disease_id", DISEASE_ID_C16)
            upload_payload.setdefault("icd10_prefixes", ["C16"])
            upload_payload.setdefault("nosology_keywords", ["рак желудка", "gastric cancer"])
        if str(upload_payload.get("doc_id") or "").strip() == "russco_2023_22":
            upload_payload.setdefault("disease_id", DISEASE_ID_C16)
            upload_payload.setdefault("icd10_prefixes", ["C16"])
            upload_payload.setdefault("nosology_keywords", ["рак желудка", "gastric cancer"])
        _upload_doc_from_payload(base_url, upload_payload, payload_path=payload_path, action_label="gastric upload")

    reindex_payload = _poll_reindex(base_url, max_attempts=max_attempts)

    case_import_payload_path: Path | None = None
    for file_name in GASTRIC_CASE_IMPORT_PAYLOADS:
        candidate = api_requests / file_name
        if candidate.exists():
            case_import_payload_path = candidate
            break
    if case_import_payload_path is None:
        raise RuntimeError(
            "gastric pack must contain one of case import payloads: "
            + ", ".join(GASTRIC_CASE_IMPORT_PAYLOADS)
        )
    case_import_payload = _load_json_payload(case_import_payload_path)
    import_status, import_response = _request_json(
        method="POST",
        url=f"{base_url.rstrip('/')}/api/case/import",
        headers=_role_headers("clinician", base_url=base_url),
        payload=case_import_payload,
    )
    _require_ok(import_status, import_response, f"gastric case import ({case_import_payload_path.name})")

    case_id = str(import_response.get("case_id") or "").strip()
    import_run_id = str(import_response.get("import_run_id") or "").strip()
    if not case_id or not import_run_id:
        raise RuntimeError(f"gastric case import returned incomplete payload: {import_response}")

    analyze_payload_path = api_requests / GASTRIC_ANALYZE_PAYLOAD
    analyze_request = _load_json_payload(analyze_payload_path)
    analyze_request["request_id"] = str(uuid.uuid4())
    analyze_request["query_type"] = "NEXT_STEPS"
    analyze_request["language"] = str(analyze_request.get("language") or "ru").strip() or "ru"
    case_block = analyze_request.get("case")
    if not isinstance(case_block, dict):
        case_block = {}
        analyze_request["case"] = case_block
    case_block["case_id"] = case_id
    analyze_request["sources"] = {"mode": "AUTO", "source_ids": ["minzdrav", "russco"]}

    analyze_status, analyze_response = _request_json(
        method="POST",
        url=f"{base_url.rstrip('/')}/api/analyze",
        headers=_role_headers("clinician", base_url=base_url, extra={"x-client-id": "e2e-gastric-smoke"}),
        payload=analyze_request,
    )
    _require_ok(analyze_status, analyze_response, f"gastric analyze ({GASTRIC_ANALYZE_PAYLOAD})")

    citation_count, sources_used, issue_count = _collect_pack_citation_metrics(analyze_response)
    if citation_count < 1:
        raise RuntimeError(
            f"gastric flow expected at least one citation, got={citation_count}, response={analyze_response}"
        )
    if issue_count < 1:
        raise RuntimeError(
            f"gastric flow expected at least one issue in doctor_report, got={issue_count}, response={analyze_response}"
        )
    expected_sources = {"minzdrav", "russco"}
    if not expected_sources.issubset(set(sources_used)):
        raise RuntimeError(
            "gastric flow expected evidence from both sources "
            f"{sorted(expected_sources)}, got={sources_used}"
        )
    run_meta = analyze_response.get("run_meta") if isinstance(analyze_response.get("run_meta"), dict) else {}
    routing_meta = run_meta.get("routing_meta") if isinstance(run_meta.get("routing_meta"), dict) else {}
    resolved_cancer_type = str(routing_meta.get("resolved_cancer_type") or "").strip()
    if not resolved_cancer_type or resolved_cancer_type == "unknown":
        raise RuntimeError(
            f"gastric flow expected resolved_cancer_type in routing_meta, got={routing_meta}, response={analyze_response}"
        )
    patient_summary = _extract_patient_summary(analyze_response)
    if not patient_summary:
        raise RuntimeError(f"gastric flow expected non-empty patient_explain summary, got response={analyze_response}")
    return {
        "reindex_payload": reindex_payload,
        "import_response": import_response,
        "analyze_response": analyze_response,
        "case_id": case_id,
        "import_run_id": import_run_id,
        "citations_count": citation_count,
        "sources_used": sources_used,
        "issues_count": issue_count,
    }


def _routing_ratio_from_run_meta(run_meta_payload: dict[str, Any]) -> float:
    routing_meta = run_meta_payload.get("routing_meta") if isinstance(run_meta_payload.get("routing_meta"), dict) else {}
    baseline = int(routing_meta.get("baseline_candidate_chunks") or 0)
    candidate = int(routing_meta.get("candidate_chunks") or 0)
    ratio = float(routing_meta.get("reduction_ratio") or 0.0)
    if baseline > 0 and ratio <= 0:
        ratio = max(0.0, 1.0 - (float(candidate) / float(baseline)))
    return max(0.0, min(1.0, ratio))


def _run_multi_onco_flow(
    base_url: str,
    *,
    max_attempts: int,
    min_routing_reduction: float,
    selected_cases: list[str] | None = None,
) -> dict:
    selected = {item.strip().upper() for item in (selected_cases or []) if item and item.strip()}

    def _doc_case_label(doc_id: str) -> str:
        parts = str(doc_id or "").strip().lower().split("_")
        if len(parts) < 2:
            return ""
        case_code = parts[1]
        if not case_code.startswith("c"):
            return ""
        return case_code.upper()

    doc_specs = [
        {
            "filename": "c16_minzdrav_demo.txt",
            "content": b"C16 gastric cancer adenocarcinoma mFOLFOX6 HER2 minzdrav guideline",
            "doc_id": "kr_c16_minzdrav_2026",
            "doc_version": "2026.2",
            "source_set": "minzdrav",
            "cancer_type": "gastric_cancer",
            "language": "ru",
            "disease_id": DISEASE_ID_C16,
            "icd10_prefixes": ["C16"],
            "nosology_keywords": ["рак желудка", "gastric cancer", "stomach cancer"],
        },
        {
            "filename": "c16_russco_demo.txt",
            "content": b"C16 gastric cancer adenocarcinoma mFOLFOX6 HER2 russco guideline",
            "doc_id": "kr_c16_russco_2026",
            "doc_version": "2026.2",
            "source_set": "russco",
            "cancer_type": "gastric_cancer",
            "language": "ru",
            "disease_id": DISEASE_ID_C16,
            "icd10_prefixes": ["C16"],
            "nosology_keywords": ["рак желудка", "gastric cancer", "stomach cancer"],
        },
        {
            "filename": "c16_minzdrav_decoy.txt",
            "content": b"decoy gastric cancer reference minzdrav",
            "doc_id": "demo_c16_minzdrav_decoy_2026",
            "doc_version": "2026.2",
            "source_set": "minzdrav",
            "cancer_type": "gastric_cancer",
            "language": "ru",
            "disease_id": DISEASE_ID_DECOY,
            "icd10_prefixes": ["C80"],
            "nosology_keywords": ["нерелевантный decoy"],
        },
        {
            "filename": "c16_russco_decoy.txt",
            "content": b"decoy gastric cancer reference russco",
            "doc_id": "demo_c16_russco_decoy_2026",
            "doc_version": "2026.2",
            "source_set": "russco",
            "cancer_type": "gastric_cancer",
            "language": "ru",
            "disease_id": DISEASE_ID_DECOY,
            "icd10_prefixes": ["C80"],
            "nosology_keywords": ["нерелевантный decoy"],
        },
        {
            "filename": "c34_minzdrav_demo.txt",
            "content": b"C34 NSCLC EGFR osimertinib minzdrav guideline",
            "doc_id": "kr_c34_minzdrav_2026",
            "doc_version": "2026.2",
            "source_set": "minzdrav",
            "cancer_type": "nsclc_egfr",
            "language": "ru",
            "disease_id": DISEASE_ID_C34,
            "icd10_prefixes": ["C34"],
            "nosology_keywords": ["рак легкого", "немелкоклеточный", "nsclc"],
        },
        {
            "filename": "c34_russco_demo.txt",
            "content": b"C34 NSCLC EGFR osimertinib russco guideline",
            "doc_id": "kr_c34_russco_2026",
            "doc_version": "2026.2",
            "source_set": "russco",
            "cancer_type": "nsclc_egfr",
            "language": "ru",
            "disease_id": DISEASE_ID_C34,
            "icd10_prefixes": ["C34"],
            "nosology_keywords": ["рак легкого", "немелкоклеточный", "nsclc"],
        },
        {
            "filename": "c34_minzdrav_decoy.txt",
            "content": b"decoy nsclc guideline minzdrav",
            "doc_id": "demo_c34_minzdrav_decoy_2026",
            "doc_version": "2026.2",
            "source_set": "minzdrav",
            "cancer_type": "nsclc_egfr",
            "language": "ru",
            "disease_id": DISEASE_ID_DECOY,
            "icd10_prefixes": ["C80"],
            "nosology_keywords": ["нерелевантный decoy"],
        },
        {
            "filename": "c34_russco_decoy.txt",
            "content": b"decoy nsclc guideline russco",
            "doc_id": "demo_c34_russco_decoy_2026",
            "doc_version": "2026.2",
            "source_set": "russco",
            "cancer_type": "nsclc_egfr",
            "language": "ru",
            "disease_id": DISEASE_ID_DECOY,
            "icd10_prefixes": ["C80"],
            "nosology_keywords": ["нерелевантный decoy"],
        },
        {
            "filename": "c50_minzdrav_demo.txt",
            "content": b"C50 breast cancer HR+ HER2- CDK4/6 minzdrav guideline",
            "doc_id": "kr_c50_minzdrav_2026",
            "doc_version": "2026.2",
            "source_set": "minzdrav",
            "cancer_type": "breast_hr+/her2-",
            "language": "ru",
            "disease_id": DISEASE_ID_C50,
            "icd10_prefixes": ["C50"],
            "nosology_keywords": ["рак молочной железы", "breast cancer", "hr+ her2-"],
        },
        {
            "filename": "c50_russco_demo.txt",
            "content": b"C50 breast cancer HR+ HER2- CDK4/6 russco guideline",
            "doc_id": "kr_c50_russco_2026",
            "doc_version": "2026.2",
            "source_set": "russco",
            "cancer_type": "breast_hr+/her2-",
            "language": "ru",
            "disease_id": DISEASE_ID_C50,
            "icd10_prefixes": ["C50"],
            "nosology_keywords": ["рак молочной железы", "breast cancer", "hr+ her2-"],
        },
        {
            "filename": "c50_minzdrav_decoy.txt",
            "content": b"decoy breast cancer guideline minzdrav",
            "doc_id": "demo_c50_minzdrav_decoy_2026",
            "doc_version": "2026.2",
            "source_set": "minzdrav",
            "cancer_type": "breast_hr+/her2-",
            "language": "ru",
            "disease_id": DISEASE_ID_DECOY,
            "icd10_prefixes": ["C80"],
            "nosology_keywords": ["нерелевантный decoy"],
        },
        {
            "filename": "c50_russco_decoy.txt",
            "content": b"decoy breast cancer guideline russco",
            "doc_id": "demo_c50_russco_decoy_2026",
            "doc_version": "2026.2",
            "source_set": "russco",
            "cancer_type": "breast_hr+/her2-",
            "language": "ru",
            "disease_id": DISEASE_ID_DECOY,
            "icd10_prefixes": ["C80"],
            "nosology_keywords": ["нерелевантный decoy"],
        },
    ]
    if selected:
        doc_specs = [
            doc for doc in doc_specs if _doc_case_label(str(doc.get("doc_id") or "")) in selected
        ]
        if not doc_specs:
            raise RuntimeError(
                f"multi-onco flow has no matching guideline docs for filter={sorted(selected)}; "
                "available=['C16','C34','C50']"
            )

    for doc in doc_specs:
        upload_payload = {
            "filename": str(doc["filename"]),
            "content_base64": _encode_base64_content(bytes(doc["content"])),
            "doc_id": str(doc["doc_id"]),
            "doc_version": str(doc["doc_version"]),
            "source_set": str(doc["source_set"]),
            "cancer_type": str(doc["cancer_type"]),
            "language": str(doc["language"]),
            "disease_id": str(doc["disease_id"]),
            "icd10_prefixes": list(doc["icd10_prefixes"]),
            "nosology_keywords": list(doc["nosology_keywords"]),
            "source_url": str(
                doc.get("source_url")
                or (
                    "https://cr.minzdrav.gov.ru/preview-cr/demo"
                    if str(doc["source_set"]) == "minzdrav"
                    else "https://www.rosoncoweb.ru/standarts/RUSSCO/2026/demo.pdf"
                )
            ),
        }
        upload_result_raw = _upload_doc_from_payload(
            base_url,
            upload_payload,
            payload_path=Path(f"/tmp/{doc['doc_id']}.json"),
            action_label=f"multi-onco upload {doc['doc_id']}",
        )
        upload_result = upload_result_raw if isinstance(upload_result_raw, dict) else {}
        if str(upload_result.get("status") or "").strip().lower() == "duplicate_skipped":
            continue
        effective_doc_id = str(upload_result.get("doc_id") or doc["doc_id"]).strip() or str(doc["doc_id"])
        effective_doc_version = (
            str(upload_result.get("doc_version") or doc["doc_version"]).strip() or str(doc["doc_version"])
        )
        _run_admin_doc_release_workflow(
            base_url,
            doc_id=effective_doc_id,
            doc_version=effective_doc_version,
        )

    reindex_payload = {"status": "release_workflow_per_doc"}

    case_specs = [
        {
            "label": "C16",
            "filename": "case_c16.txt",
            "text": "Диагноз: C16.9. Аденокарцинома желудка, стадия IV. План лечения: mFOLFOX6, HER2 positive.",
            "expected_cancer_type": "gastric_cancer",
        },
        {
            "label": "C34",
            "filename": "case_c34.txt",
            "text": "Диагноз: C34.9. Немелкоклеточный рак легкого, EGFR L858R, стадия IV. Режим: osimertinib 80 mg.",
            "expected_cancer_type": "nsclc_egfr",
        },
        {
            "label": "C50",
            "filename": "case_c50.txt",
            "text": "Диагноз: C50.9. Рак молочной железы HR+ HER2-, стадия III. Рассмотреть CDK4/6 ингибитор.",
            "expected_cancer_type": "breast_hr+/her2-",
        },
    ]
    if selected:
        case_specs = [spec for spec in case_specs if str(spec.get("label", "")).upper() in selected]
        if not case_specs:
            raise RuntimeError(
                f"multi-onco flow has no matching cases for filter={sorted(selected)}; available=['C16','C34','C50']"
            )

    expected_sources = {"minzdrav", "russco"}
    case_results: list[dict[str, Any]] = []
    source_union: set[str] = set()
    total_citations = 0
    total_issues = 0
    min_ratio = 1.0
    strategies: set[str] = set()
    last_case_id = ""
    last_import_run_id = ""
    last_analyze_response: dict[str, Any] = {}

    for case_spec in case_specs:
        file_bytes = str(case_spec["text"]).encode("utf-8")
        base64_payload = _encode_base64_content(file_bytes)

        import_status, import_response = _request_json(
            method="POST",
            url=f"{base_url.rstrip('/')}/api/case/import-file",
            headers=_role_headers("clinician", base_url=base_url),
            payload={
                "filename": str(case_spec["filename"]),
                "content_base64": base64_payload,
                "mime_type": "text/plain",
                "data_mode": "DEID",
            },
        )
        _require_ok(import_status, import_response, f"multi-onco case import ({case_spec['label']})")
        case_id = str(import_response.get("case_id") or "").strip()
        import_run_id = str(import_response.get("import_run_id") or "").strip()
        if not case_id or not import_run_id:
            raise RuntimeError(
                f"multi-onco case import returned incomplete payload for {case_spec['label']}: {import_response}"
            )

        analyze_request = {
            "schema_version": "0.2",
            "request_id": str(uuid.uuid4()),
            "query_type": "NEXT_STEPS",
            "sources": {"mode": "AUTO", "source_ids": ["minzdrav", "russco"]},
            "kb_filters": {
                "source_mode": "AUTO",
                "source_sets": ["minzdrav", "russco"],
                "doc_ids": [
                    f"kr_{str(case_spec['label']).lower()}_minzdrav_2026",
                    f"kr_{str(case_spec['label']).lower()}_russco_2026",
                ],
            },
            "language": "ru",
            "case": {"case_id": case_id},
            "options": {"strict_evidence": True, "max_chunks": 40, "max_citations": 40, "timeout_ms": 120000},
        }
        analyze_status, analyze_response = _request_json(
            method="POST",
            url=f"{base_url.rstrip('/')}/api/analyze",
            headers=_role_headers(
                "clinician",
                base_url=base_url,
                extra={"x-client-id": f"e2e-multi-onco-{str(case_spec['label']).lower()}"},
            ),
            payload=analyze_request,
        )
        _require_ok(analyze_status, analyze_response, f"multi-onco analyze ({case_spec['label']})")

        citation_count, sources_used, issue_count = _collect_pack_citation_metrics(analyze_response)
        if citation_count < 1:
            raise RuntimeError(
                f"multi-onco flow expected at least one citation for {case_spec['label']}, got={citation_count}, "
                f"response={analyze_response}"
            )
        doctor_report = analyze_response.get("doctor_report") if isinstance(analyze_response.get("doctor_report"), dict) else {}
        verification_summary = (
            doctor_report.get("verification_summary")
            if isinstance(doctor_report.get("verification_summary"), dict)
            else {}
        )
        verification_category = str(verification_summary.get("category") or "").strip().upper()
        # In strict LLM+RAG mode a fully compliant plan can legitimately produce zero issues.
        if issue_count < 1 and verification_category != "OK":
            raise RuntimeError(
                f"multi-onco flow expected issues>=1 or verification_summary=OK for {case_spec['label']}, "
                f"got issues={issue_count}, verification_category={verification_category}, "
                f"response={analyze_response}"
            )
        if not expected_sources.issubset(set(sources_used)):
            raise RuntimeError(
                f"multi-onco flow expected sources {sorted(expected_sources)} for {case_spec['label']}, got={sources_used}"
            )

        run_meta = analyze_response.get("run_meta") if isinstance(analyze_response.get("run_meta"), dict) else {}
        routing_meta = run_meta.get("routing_meta") if isinstance(run_meta.get("routing_meta"), dict) else {}
        resolved_cancer_type = str(routing_meta.get("resolved_cancer_type") or "").strip()
        if resolved_cancer_type != str(case_spec["expected_cancer_type"]):
            raise RuntimeError(
                "multi-onco resolved cancer_type mismatch: "
                f"case={case_spec['label']} expected={case_spec['expected_cancer_type']} got={resolved_cancer_type} "
                f"routing_meta={routing_meta}"
            )
        match_strategy = str(routing_meta.get("match_strategy") or "").strip()
        if match_strategy in {"default_sources_fallback", "manual_source_override"}:
            raise RuntimeError(
                "multi-onco expected deterministic routing (icd10/keyword/cancer_type), "
                f"got strategy={match_strategy} for case={case_spec['label']}, routing_meta={routing_meta}"
            )
        reduction_ratio = _routing_ratio_from_run_meta(run_meta)
        if min_routing_reduction > 0 and reduction_ratio < float(min_routing_reduction):
            raise RuntimeError(
                f"multi-onco routing reduction gate failed for {case_spec['label']}: "
                f"reduction={reduction_ratio:.3f}, required={float(min_routing_reduction):.3f}, "
                f"routing_meta={routing_meta}"
            )

        patient_status, patient_response = _request_json(
            method="POST",
            url=f"{base_url.rstrip('/')}/api/patient/analyze",
            headers=_role_headers("patient", base_url=base_url),
            payload={
                "filename": str(case_spec["filename"]),
                "content_base64": base64_payload,
                "mime_type": "text/plain",
                "request_id": str(uuid.uuid4()),
                "query_type": "NEXT_STEPS",
                "sources": {"mode": "AUTO", "source_ids": ["minzdrav", "russco"]},
                "language": "ru",
            },
        )
        _require_ok(patient_status, patient_response, f"multi-onco patient analyze ({case_spec['label']})")
        if "doctor_report" in patient_response:
            raise RuntimeError(
                f"patient endpoint leaked doctor_report for {case_spec['label']}: payload={patient_response}"
            )
        patient_explain = (
            patient_response.get("patient_explain")
            if isinstance(patient_response.get("patient_explain"), dict)
            else {}
        )
        patient_summary = str(patient_explain.get("summary") or patient_explain.get("summary_plain") or "").strip()
        if not patient_summary:
            raise RuntimeError(
                f"patient endpoint missing summary for {case_spec['label']}: payload={patient_response}"
            )
        patient_run_meta = (
            patient_response.get("run_meta")
            if isinstance(patient_response.get("run_meta"), dict)
            else {}
        )
        patient_routing_meta = (
            patient_run_meta.get("routing_meta")
            if isinstance(patient_run_meta.get("routing_meta"), dict)
            else {}
        )
        patient_cancer_type = str(patient_routing_meta.get("resolved_cancer_type") or "").strip()
        if patient_cancer_type and patient_cancer_type != str(case_spec["expected_cancer_type"]):
            raise RuntimeError(
                f"patient routing mismatch for {case_spec['label']}: expected={case_spec['expected_cancer_type']}, "
                f"got={patient_cancer_type}, routing_meta={patient_routing_meta}"
            )

        total_citations += int(citation_count)
        total_issues += int(issue_count)
        source_union.update(sources_used)
        min_ratio = min(min_ratio, reduction_ratio)
        if match_strategy:
            strategies.add(match_strategy)
        case_results.append(
            {
                "label": str(case_spec["label"]),
                "case_id": case_id,
                "import_run_id": import_run_id,
                "routing_match_strategy": match_strategy,
                "routing_reduction_ratio": round(reduction_ratio, 4),
                "resolved_cancer_type": resolved_cancer_type,
                "citations_count": int(citation_count),
                "sources_used": sources_used,
                "issues_count": int(issue_count),
                "patient_summary_present": True,
            }
        )
        last_case_id = case_id
        last_import_run_id = import_run_id
        last_analyze_response = analyze_response

    if not case_results:
        raise RuntimeError("multi-onco flow did not execute any cases")

    return {
        "reindex_payload": reindex_payload,
        "cases": case_results,
        "case_id": last_case_id,
        "import_run_id": last_import_run_id,
        "analyze_response": last_analyze_response,
        "citations_count": total_citations,
        "sources_used": sorted(source_union),
        "issues_count": total_issues,
        "min_routing_reduction_ratio": round(min_ratio, 4),
        "match_strategies": sorted(strategies),
    }


def _require_ok(status: int, payload: dict, action: str) -> None:
    if 200 <= status < 300:
        return
    raise RuntimeError(f"{action} failed: HTTP {status}, payload={payload}")


_ROLE_COOKIE_CACHE: dict[tuple[str, str], str] = {}
_SMOKE_AUTH_MODE = "auto"


def _role_credentials_from_env(role: str) -> tuple[str, str]:
    prefix = role.upper()
    username = os.environ.get(f"ONCO_SMOKE_{prefix}_USERNAME", "").strip()
    password = os.environ.get(f"ONCO_SMOKE_{prefix}_PASSWORD", "")
    return username, password


def _base64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _smoke_auth_mode() -> str:
    value = str(_SMOKE_AUTH_MODE or os.environ.get("ONCO_SMOKE_AUTH_MODE", "auto")).strip().lower()
    if value in {"demo", "credentials", "idp"}:
        return value
    return "auto"


def _idp_secret() -> str:
    return (
        str(os.environ.get("ONCO_SMOKE_IDP_SECRET", "")).strip()
        or str(os.environ.get("SESSION_IDP_HS256_SECRET", "")).strip()
    )


def _idp_token_from_env(role: str) -> str:
    # Supports role-specific tokens from env:
    # ONCO_SMOKE_IDP_ADMIN_TOKEN / ONCO_SMOKE_IDP_CLINICIAN_TOKEN / ONCO_SMOKE_IDP_PATIENT_TOKEN
    # and generic ONCO_SMOKE_IDP_TOKEN.
    specific = str(os.environ.get(f"ONCO_SMOKE_IDP_{role.upper()}_TOKEN", "")).strip()
    if specific:
        return specific
    generic = str(os.environ.get("ONCO_SMOKE_IDP_TOKEN", "")).strip()
    if generic:
        return generic
    return ""


def _idp_claim_names() -> tuple[str, str]:
    role_claim = str(os.environ.get("ONCO_SMOKE_IDP_ROLE_CLAIM", "role")).strip() or "role"
    user_claim = str(os.environ.get("ONCO_SMOKE_IDP_USER_ID_CLAIM", "sub")).strip() or "sub"
    return role_claim, user_claim


def _idp_allowed_algs() -> set[str]:
    raw = (
        str(os.environ.get("ONCO_SMOKE_IDP_ALLOWED_ALGS", "")).strip()
        or str(os.environ.get("SESSION_IDP_ALLOWED_ALGS", "")).strip()
        or "RS256,HS256"
    )
    values = [item.strip().upper() for item in raw.split(",") if item.strip()]
    return set(values)


def _idp_negative_token(name: str) -> str:
    return str(os.environ.get(name, "")).strip()


def _build_mock_idp_token(alg: str, payload_overrides: dict[str, str | int] | None = None) -> str:
    issuer = (
        str(os.environ.get("ONCO_SMOKE_IDP_ISSUER", "")).strip()
        or str(os.environ.get("SESSION_IDP_ISSUER", "")).strip()
        or "https://idp.local/onco"
    )
    audience = (
        str(os.environ.get("ONCO_SMOKE_IDP_AUDIENCE", "")).strip()
        or str(os.environ.get("SESSION_IDP_AUDIENCE", "")).strip()
        or "oncoai-bff"
    )
    role_claim, user_claim = _idp_claim_names()
    now = int(time.time())
    header = {"alg": alg, "typ": "JWT", "kid": "onco-smoke-mock"}
    payload: dict[str, str | int] = {
        "iss": issuer,
        "aud": audience,
        "iat": now,
        "nbf": now - 1,
        "exp": now + 900,
        "jti": str(uuid.uuid4()),
        role_claim: "admin",
        user_claim: "smoke:admin:mock",
    }
    for key, value in (payload_overrides or {}).items():
        payload[str(key)] = value
    return (
        f"{_base64url_encode(json.dumps(header, separators=(',', ':')).encode('utf-8'))}."
        f"{_base64url_encode(json.dumps(payload, separators=(',', ':')).encode('utf-8'))}."
        f"{_base64url_encode(b'invalid-signature')}"
    )


def _build_hs256_idp_token(
    role: str,
    *,
    payload_overrides: dict[str, str | int] | None = None,
    drop_claims: set[str] | None = None,
) -> str:
    secret = _idp_secret()
    if not secret:
        raise RuntimeError("ONCO_SMOKE_IDP_SECRET is required for idp smoke mode")

    if str(os.environ.get("ONCO_SMOKE_IDP_ALG", "HS256")).strip().upper() != "HS256":
        raise RuntimeError("ONCO_SMOKE_IDP_ALG currently supports HS256 only in smoke script")

    issuer = (
        str(os.environ.get("ONCO_SMOKE_IDP_ISSUER", "")).strip()
        or str(os.environ.get("SESSION_IDP_ISSUER", "")).strip()
        or "https://idp.local/onco"
    )
    audience = (
        str(os.environ.get("ONCO_SMOKE_IDP_AUDIENCE", "")).strip()
        or str(os.environ.get("SESSION_IDP_AUDIENCE", "")).strip()
        or "oncoai-bff"
    )
    role_claim, user_claim = _idp_claim_names()
    user_id = str(os.environ.get(f"ONCO_SMOKE_{role.upper()}_USER_ID", "")).strip() or f"smoke:{role}"
    ttl_sec_raw = str(os.environ.get("ONCO_SMOKE_IDP_TTL_SEC", "900")).strip()
    try:
        ttl_sec = max(60, int(ttl_sec_raw))
    except ValueError:
        ttl_sec = 900

    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT", "kid": "onco-smoke-hs256"}
    payload: dict[str, str | int] = {
        "iss": issuer,
        "aud": audience,
        "iat": now,
        "nbf": now - 1,
        "exp": now + ttl_sec,
        "jti": str(uuid.uuid4()),
        role_claim: role,
        user_claim: user_id,
    }
    for key, value in (payload_overrides or {}).items():
        payload[str(key)] = value
    for claim in (drop_claims or set()):
        payload.pop(str(claim), None)
    signing_input = (
        f"{_base64url_encode(json.dumps(header, separators=(',', ':')).encode('utf-8'))}."
        f"{_base64url_encode(json.dumps(payload, separators=(',', ':')).encode('utf-8'))}"
    )
    signature = hmac.new(secret.encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256).digest()
    return f"{signing_input}.{_base64url_encode(signature)}"


def _session_login(
    base_url: str,
    payload: dict[str, str],
    *,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, str, list[str], dict[str, str]]:
    body = json.dumps(payload).encode("utf-8")
    headers = {"content-type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/session/login",
        method="POST",
        data=body,
        headers=headers,
    )
    set_cookie_headers: list[str] = []
    response_headers: dict[str, str] = {}
    status = 0
    response_text = ""
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status = response.status
            response_text = response.read().decode("utf-8")
            set_cookie_headers = list(response.headers.get_all("Set-Cookie") or [])
            response_headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
    except urllib.error.HTTPError as exc:
        status = exc.code
        response_text = exc.read().decode("utf-8") if exc.fp else ""
        set_cookie_headers = list(exc.headers.get_all("Set-Cookie") or [])
        response_headers = {str(key).lower(): str(value) for key, value in (exc.headers.items() if exc.headers else [])}
    return status, response_text, set_cookie_headers, response_headers


def _signed_role_cookie(base_url: str, role: str) -> str:
    cache_key = (base_url.rstrip("/"), role)
    cached = _ROLE_COOKIE_CACHE.get(cache_key)
    if cached:
        return cached

    if role not in {"admin", "clinician", "patient"}:
        raise RuntimeError(f"Unsupported role for smoke cookie bootstrap: {role}")

    username, password = _role_credentials_from_env(role)
    auth_mode = _smoke_auth_mode()
    use_idp = auth_mode == "idp" or (auth_mode == "auto" and bool(_idp_secret()))
    if use_idp:
        idp_token = _idp_token_from_env(role)
        if not idp_token:
            idp_token = _build_hs256_idp_token(role)
        payload = {"id_token": idp_token}
    elif auth_mode == "credentials":
        payload = {"username": username, "password": password}
    elif username and password:
        payload = {"username": username, "password": password}
    else:
        payload = {"role": role}
    status, response_text, set_cookie_headers, _ = _session_login(base_url, payload)
    retry_attempt = 0
    while status == 429 and retry_attempt < 3:
        retry_attempt += 1
        retry_after_sec = 1
        try:
            parsed = json.loads(response_text) if response_text else {}
        except json.JSONDecodeError:
            parsed = {}
        if str(parsed.get("reason") or "") != "login_rate_limited":
            break
        try:
            retry_after_sec = max(1, int(parsed.get("retry_after_sec") or 1))
        except (TypeError, ValueError):
            retry_after_sec = 1
        time.sleep(min(retry_after_sec, 30))
        status, response_text, set_cookie_headers, _ = _session_login(base_url, payload)

    cookie = SimpleCookie()
    for raw_cookie in set_cookie_headers:
        cookie.load(raw_cookie)

    required = [
        "session_access",
        "session_access_sig",
        "session_refresh",
        "session_refresh_sig",
    ]
    missing = [name for name in required if cookie.get(name) is None]
    if missing:
        env_hint = (
            f" For credentials mode set ONCO_SMOKE_{role.upper()}_USERNAME and ONCO_SMOKE_{role.upper()}_PASSWORD."
        )
        raise RuntimeError(
            "failed to bootstrap signed session cookie "
            f"for role={role}; status={status}; missing={missing}; set-cookie headers={set_cookie_headers}; "
            f"response={response_text!r}.{env_hint}"
        )

    cookie_header = "; ".join(f"{name}={cookie[name].value}" for name in required)
    _ROLE_COOKIE_CACHE[cache_key] = cookie_header
    return cookie_header


def _role_headers(role: str, *, base_url: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"cookie": _signed_role_cookie(base_url, role)}
    if extra:
        headers.update(extra)
    return headers


def _invalidate_role_cookie(base_url: str, role: str) -> None:
    _ROLE_COOKIE_CACHE.pop((base_url.rstrip("/"), role), None)


def _request_json_with_role_retry(
    *,
    method: str,
    url: str,
    base_url: str,
    role: str,
    payload: dict | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, dict]:
    headers = _role_headers(role, base_url=base_url, extra=extra_headers)
    status, body = _request_json(method=method, url=url, headers=headers, payload=payload)
    if status not in {401, 403}:
        return status, body

    _invalidate_role_cookie(base_url, role)
    retry_headers = _role_headers(role, base_url=base_url, extra=extra_headers)
    return _request_json(method=method, url=url, headers=retry_headers, payload=payload)


def _http_call_with_role_retry(
    *,
    method: str,
    url: str,
    base_url: str,
    role: str,
    body: bytes | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, str, dict[str, str]]:
    headers = _role_headers(role, base_url=base_url, extra=extra_headers)
    status, text, response_headers = _http_call_with_headers(method=method, url=url, headers=headers, body=body)
    if status not in {401, 403}:
        return status, text, response_headers

    _invalidate_role_cookie(base_url, role)
    retry_headers = _role_headers(role, base_url=base_url, extra=extra_headers)
    return _http_call_with_headers(method=method, url=url, headers=retry_headers, body=body)


def _require_role_spoof_blocked(base_url: str) -> None:
    # R1 hardening: x-role header must not grant admin access without server-side role.
    status, payload = _request_json(
        method="GET",
        url=f"{base_url.rstrip('/')}/api/admin/docs",
        headers={"x-role": "admin"},
    )
    if status not in {401, 403}:
        raise RuntimeError(
            "role spoofing check failed: expected HTTP 401/403 for /api/admin/docs without role cookie, "
            f"got HTTP {status}, payload={payload}"
        )

    # Session-only hardening: legacy role/role_sig cookies must not authenticate admin.
    legacy_cookie_headers = {"cookie": "role=admin; role_sig=deadbeef"}
    legacy_status, legacy_payload = _request_json(
        method="GET",
        url=f"{base_url.rstrip('/')}/api/admin/docs",
        headers=legacy_cookie_headers,
    )
    if legacy_status not in {401, 403}:
        raise RuntimeError(
            "legacy role cookie check failed: expected HTTP 401/403 for /api/admin/docs with role/role_sig only, "
            f"got HTTP {legacy_status}, payload={legacy_payload}"
        )


def _require_session_error_contract(base_url: str) -> None:
    me_status, me_text, me_headers = _http_call_with_headers(
        method="GET",
        url=f"{base_url.rstrip('/')}/api/session/me",
    )
    try:
        me_payload = json.loads(me_text) if me_text else {}
    except json.JSONDecodeError:
        me_payload = {"raw": me_text}
    if me_status != 401:
        raise RuntimeError(
            "session me auth-required check failed: expected HTTP 401 without session, "
            f"got HTTP {me_status}, payload={me_payload}"
        )
    if me_payload.get("authenticated") is not False:
        raise RuntimeError(f"session me auth-required payload mismatch: {me_payload}")
    if str(me_payload.get("error_code") or "") != "BFF_AUTH_REQUIRED":
        raise RuntimeError(
            "session me auth-required payload must include error_code=BFF_AUTH_REQUIRED, "
            f"got payload={me_payload}"
        )
    if str(me_payload.get("code") or "") != "BFF_AUTH_REQUIRED":
        raise RuntimeError(
            "session me auth-required payload must include code=BFF_AUTH_REQUIRED, "
            f"got payload={me_payload}"
        )
    if str(me_payload.get("reason") or "") != "auth_required":
        raise RuntimeError(
            "session me auth-required payload must include reason=auth_required, "
            f"got payload={me_payload}"
        )
    me_corr = str(me_payload.get("correlation_id") or "").strip()
    me_corr_header = str(me_headers.get("x-correlation-id", "")).strip()
    if not me_corr:
        raise RuntimeError(f"session me auth-required payload must include non-empty correlation_id: {me_payload}")
    if me_corr != me_corr_header:
        raise RuntimeError(
            "session me auth-required payload/header correlation mismatch: "
            f"payload={me_corr!r}, header={me_corr_header!r}, full_payload={me_payload}"
        )

    revoke_status, revoke_text, revoke_headers = _http_call_with_headers(
        method="POST",
        url=f"{base_url.rstrip('/')}/api/session/revoke",
        headers={"content-type": "application/json"},
        body=json.dumps({"scope": "self"}).encode("utf-8"),
    )
    try:
        revoke_payload = json.loads(revoke_text) if revoke_text else {}
    except json.JSONDecodeError:
        revoke_payload = {"raw": revoke_text}
    if revoke_status != 401:
        raise RuntimeError(
            "session revoke auth-required check failed: expected HTTP 401 without session, "
            f"got HTTP {revoke_status}, payload={revoke_payload}"
        )
    if str(revoke_payload.get("error_code") or "") != "BFF_AUTH_REQUIRED":
        raise RuntimeError(
            "session revoke auth-required payload must include error_code=BFF_AUTH_REQUIRED, "
            f"got payload={revoke_payload}"
        )
    if str(revoke_payload.get("code") or "") != "BFF_AUTH_REQUIRED":
        raise RuntimeError(
            "session revoke auth-required payload must include code=BFF_AUTH_REQUIRED, "
            f"got payload={revoke_payload}"
        )
    if str(revoke_payload.get("reason") or "") != "auth_required":
        raise RuntimeError(
            "session revoke auth-required payload must include reason=auth_required, "
            f"got payload={revoke_payload}"
        )
    revoke_corr = str(revoke_payload.get("correlation_id") or "").strip()
    revoke_corr_header = str(revoke_headers.get("x-correlation-id", "")).strip()
    if not revoke_corr:
        raise RuntimeError(
            f"session revoke auth-required payload must include non-empty correlation_id: {revoke_payload}"
        )
    if revoke_corr != revoke_corr_header:
        raise RuntimeError(
            "session revoke auth-required payload/header correlation mismatch: "
            f"payload={revoke_corr!r}, header={revoke_corr_header!r}, full_payload={revoke_payload}"
        )

    clinician_revoke_status, clinician_revoke_text, clinician_revoke_headers = _http_call_with_headers(
        method="POST",
        url=f"{base_url.rstrip('/')}/api/session/revoke",
        headers=_role_headers(
            "clinician",
            base_url=base_url,
            extra={"content-type": "application/json"},
        ),
        body=json.dumps({"scope": "user", "user_id": "smoke-forbidden-target"}).encode("utf-8"),
    )
    try:
        clinician_revoke_payload = json.loads(clinician_revoke_text) if clinician_revoke_text else {}
    except json.JSONDecodeError:
        clinician_revoke_payload = {"raw": clinician_revoke_text}
    if clinician_revoke_status != 403:
        raise RuntimeError(
            "session revoke admin-role check failed: expected HTTP 403 for clinician scope=user, "
            f"got HTTP {clinician_revoke_status}, payload={clinician_revoke_payload}"
        )
    if str(clinician_revoke_payload.get("error_code") or "") != "BFF_FORBIDDEN":
        raise RuntimeError(
            "session revoke admin-role check failed: expected error_code=BFF_FORBIDDEN, "
            f"got payload={clinician_revoke_payload}"
        )
    if str(clinician_revoke_payload.get("code") or "") != "BFF_FORBIDDEN":
        raise RuntimeError(
            "session revoke admin-role check failed: expected code=BFF_FORBIDDEN, "
            f"got payload={clinician_revoke_payload}"
        )
    if str(clinician_revoke_payload.get("reason") or "") != "admin_role_required":
        raise RuntimeError(
            "session revoke admin-role check failed: expected reason=admin_role_required, "
            f"got payload={clinician_revoke_payload}"
        )
    clinician_corr = str(clinician_revoke_payload.get("correlation_id") or "").strip()
    clinician_corr_header = str(clinician_revoke_headers.get("x-correlation-id", "")).strip()
    if not clinician_corr:
        raise RuntimeError(
            "session revoke admin-role check failed: missing payload correlation_id, "
            f"payload={clinician_revoke_payload}"
        )
    if clinician_corr != clinician_corr_header:
        raise RuntimeError(
            "session revoke admin-role check failed: payload/header correlation mismatch: "
            f"payload={clinician_corr!r}, header={clinician_corr_header!r}, full_payload={clinician_revoke_payload}"
        )

    missing_user_status, missing_user_text, missing_user_headers = _http_call_with_headers(
        method="POST",
        url=f"{base_url.rstrip('/')}/api/session/revoke",
        headers=_role_headers(
            "admin",
            base_url=base_url,
            extra={"content-type": "application/json"},
        ),
        body=json.dumps({"scope": "user"}).encode("utf-8"),
    )
    try:
        missing_user_payload = json.loads(missing_user_text) if missing_user_text else {}
    except json.JSONDecodeError:
        missing_user_payload = {"raw": missing_user_text}
    if missing_user_status != 400:
        raise RuntimeError(
            "session revoke missing-user-id check failed: expected HTTP 400 for scope=user without user_id, "
            f"got HTTP {missing_user_status}, payload={missing_user_payload}"
        )
    if str(missing_user_payload.get("error_code") or "") != "BFF_BAD_REQUEST":
        raise RuntimeError(
            "session revoke missing-user-id check failed: expected error_code=BFF_BAD_REQUEST, "
            f"got payload={missing_user_payload}"
        )
    if str(missing_user_payload.get("code") or "") != "BFF_BAD_REQUEST":
        raise RuntimeError(
            "session revoke missing-user-id check failed: expected code=BFF_BAD_REQUEST, "
            f"got payload={missing_user_payload}"
        )
    if str(missing_user_payload.get("reason") or "") != "user_id_required_for_scope_user":
        raise RuntimeError(
            "session revoke missing-user-id check failed: expected reason=user_id_required_for_scope_user, "
            f"got payload={missing_user_payload}"
        )
    missing_corr = str(missing_user_payload.get("correlation_id") or "").strip()
    missing_corr_header = str(missing_user_headers.get("x-correlation-id", "")).strip()
    if not missing_corr:
        raise RuntimeError(
            "session revoke missing-user-id check failed: missing payload correlation_id, "
            f"payload={missing_user_payload}"
        )
    if missing_corr != missing_corr_header:
        raise RuntimeError(
            "session revoke missing-user-id check failed: payload/header correlation mismatch: "
            f"payload={missing_corr!r}, header={missing_corr_header!r}, full_payload={missing_user_payload}"
        )


def _require_login_rate_limit_contract(base_url: str) -> None:
    enabled = str(os.environ.get("ONCO_SMOKE_CHECK_LOGIN_RATE_LIMIT", "false")).strip().lower()
    if enabled in {"0", "false", "no", "off"}:
        return
    if _smoke_auth_mode() == "idp":
        return

    attempts_raw = str(os.environ.get("ONCO_SMOKE_LOGIN_RATE_LIMIT_PROBE_ATTEMPTS", "120")).strip()
    try:
        attempts = max(1, min(2_000, int(attempts_raw)))
    except ValueError:
        attempts = 120

    probe_headers = {"x-forwarded-for": "198.51.100.77"}
    for _ in range(attempts):
        status, response_text, _, response_headers = _session_login(
            base_url,
            {"role": "clinician"},
            extra_headers=probe_headers,
        )
        if status != 429:
            continue
        try:
            payload = json.loads(response_text) if response_text else {}
        except json.JSONDecodeError:
            payload = {"raw": response_text}
        if str(payload.get("error_code") or "") != "BFF_RATE_LIMITED":
            raise RuntimeError(
                "login rate-limit contract check failed: expected error_code=BFF_RATE_LIMITED, "
                f"payload={payload}"
            )
        if str(payload.get("code") or "") != "BFF_RATE_LIMITED":
            raise RuntimeError(
                "login rate-limit contract check failed: expected code=BFF_RATE_LIMITED, "
                f"payload={payload}"
            )
        if str(payload.get("reason") or "") != "login_rate_limited":
            raise RuntimeError(
                "login rate-limit contract check failed: expected reason=login_rate_limited, "
                f"payload={payload}"
            )
        corr = str(payload.get("correlation_id") or "").strip()
        corr_header = str(response_headers.get("x-correlation-id", "")).strip()
        if not corr:
            raise RuntimeError(f"login rate-limit contract check failed: missing payload correlation_id: {payload}")
        if corr != corr_header:
            raise RuntimeError(
                "login rate-limit contract check failed: payload/header correlation mismatch: "
                f"payload={corr!r}, header={corr_header!r}, full_payload={payload}"
            )
        retry_after = str(response_headers.get("retry-after", "")).strip()
        if not retry_after:
            raise RuntimeError("login rate-limit contract check failed: retry-after header is missing")
        return

    raise RuntimeError(
        "login rate-limit contract check failed: did not observe HTTP 429 after probe attempts; "
        "increase ONCO_SMOKE_LOGIN_RATE_LIMIT_PROBE_ATTEMPTS or lower SESSION_LOGIN_RATE_LIMIT_PER_MINUTE"
    )


def _require_idp_login_contract(base_url: str) -> None:
    login_status, login_text, login_headers = _http_call_with_headers(
        method="GET",
        url=f"{base_url.rstrip('/')}/api/session/login",
    )
    try:
        login_payload = json.loads(login_text) if login_text else {}
    except json.JSONDecodeError:
        login_payload = {"raw": login_text}
    if login_status != 405:
        raise RuntimeError(
            "idp login endpoint contract check failed: expected HTTP 405 in idp mode for GET /api/session/login, "
            f"got HTTP {login_status}, payload={login_payload}"
        )
    if str(login_payload.get("error_code") or "") != "BFF_AUTH_REQUIRED":
        raise RuntimeError(
            "idp login endpoint contract check failed: expected error_code=BFF_AUTH_REQUIRED, "
            f"payload={login_payload}"
        )
    if str(login_payload.get("code") or "") != "BFF_AUTH_REQUIRED":
        raise RuntimeError(
            "idp login endpoint contract check failed: expected code=BFF_AUTH_REQUIRED, "
            f"payload={login_payload}"
        )
    login_reason = str(login_payload.get("reason") or "")
    if login_reason not in {"idp_mode_external_auth", "idp_mode_missing_config"}:
        raise RuntimeError(
            "idp login endpoint contract check failed: expected reason idp_mode_external_auth|idp_mode_missing_config, "
            f"payload={login_payload}"
        )
    login_corr = str(login_payload.get("correlation_id") or "").strip()
    login_corr_header = str(login_headers.get("x-correlation-id", "")).strip()
    if not login_corr:
        raise RuntimeError(
            f"idp login endpoint contract check failed: missing correlation_id in payload={login_payload}"
        )
    if login_corr != login_corr_header:
        raise RuntimeError(
            "idp login endpoint contract check failed: payload/header correlation mismatch: "
            f"payload={login_corr!r}, header={login_corr_header!r}, full_payload={login_payload}"
        )

    missing_status, missing_text, missing_headers = _http_call_with_headers(
        method="POST",
        url=f"{base_url.rstrip('/')}/api/session/login",
        headers={"content-type": "application/json"},
        body=json.dumps({}).encode("utf-8"),
    )
    try:
        missing_payload = json.loads(missing_text) if missing_text else {}
    except json.JSONDecodeError:
        missing_payload = {"raw": missing_text}
    if missing_status != 400:
        raise RuntimeError(
            "idp token-missing contract check failed: expected HTTP 400 for POST /api/session/login without token, "
            f"got HTTP {missing_status}, payload={missing_payload}"
        )
    if str(missing_payload.get("error_code") or "") != "BFF_BAD_REQUEST":
        raise RuntimeError(
            "idp token-missing contract check failed: expected error_code=BFF_BAD_REQUEST, "
            f"payload={missing_payload}"
        )
    if str(missing_payload.get("code") or "") != "BFF_BAD_REQUEST":
        raise RuntimeError(
            "idp token-missing contract check failed: expected code=BFF_BAD_REQUEST, "
            f"payload={missing_payload}"
        )
    if str(missing_payload.get("reason") or "") != "idp_token_missing":
        raise RuntimeError(
            "idp token-missing contract check failed: expected reason=idp_token_missing, "
            f"payload={missing_payload}"
        )
    missing_corr = str(missing_payload.get("correlation_id") or "").strip()
    missing_corr_header = str(missing_headers.get("x-correlation-id", "")).strip()
    if not missing_corr:
        raise RuntimeError(
            f"idp token-missing contract check failed: missing correlation_id in payload={missing_payload}"
        )
    if missing_corr != missing_corr_header:
        raise RuntimeError(
            "idp token-missing contract check failed: payload/header correlation mismatch: "
            f"payload={missing_corr!r}, header={missing_corr_header!r}, full_payload={missing_payload}"
        )


def _require_idp_login_rejected(base_url: str, *, token: str, expected_reason: str, action: str) -> None:
    status, response_text, _, response_headers = _session_login(base_url, {"id_token": token})
    try:
        payload = json.loads(response_text) if response_text else {}
    except json.JSONDecodeError:
        payload = {"raw": response_text}

    if status != 401:
        raise RuntimeError(f"{action} should fail with HTTP 401, got={status}, payload={payload}")
    if str(payload.get("error_code") or "") != "BFF_AUTH_REQUIRED":
        raise RuntimeError(f"{action} should return error_code=BFF_AUTH_REQUIRED, payload={payload}")
    if str(payload.get("code") or "") != "BFF_AUTH_REQUIRED":
        raise RuntimeError(f"{action} should keep code=BFF_AUTH_REQUIRED, payload={payload}")
    if str(payload.get("reason") or "") != expected_reason:
        raise RuntimeError(
            f"{action} should return reason={expected_reason}, got reason={payload.get('reason')!r}, payload={payload}"
        )
    corr = str(payload.get("correlation_id") or "").strip()
    corr_header = str(response_headers.get("x-correlation-id", "")).strip()
    if not corr:
        raise RuntimeError(f"{action} should return non-empty correlation_id, payload={payload}")
    if corr != corr_header:
        raise RuntimeError(
            f"{action} should keep payload/header correlation parity, "
            f"got payload={corr!r}, header={corr_header!r}, payload_json={payload}"
        )


def _require_idp_claim_checks(base_url: str) -> None:
    # Runtime negative checks for IdP claim policy.
    # Can be disabled explicitly in environments where only external pre-signed IdP tokens are available.
    require_negative = str(os.environ.get("ONCO_SMOKE_REQUIRE_IDP_NEGATIVE", "true")).strip().lower()
    if require_negative in {"0", "false", "no", "off"}:
        return
    role_claim, user_claim = _idp_claim_names()

    missing_user_token = _idp_negative_token("ONCO_SMOKE_IDP_NEG_TOKEN_MISSING_USER_ID")
    invalid_user_token = _idp_negative_token("ONCO_SMOKE_IDP_NEG_TOKEN_INVALID_USER_ID")
    invalid_role_token = _idp_negative_token("ONCO_SMOKE_IDP_NEG_TOKEN_INVALID_ROLE")
    issuer_mismatch_token = _idp_negative_token("ONCO_SMOKE_IDP_NEG_TOKEN_ISSUER_MISMATCH")
    audience_mismatch_token = _idp_negative_token("ONCO_SMOKE_IDP_NEG_TOKEN_AUDIENCE_MISMATCH")
    expired_token = _idp_negative_token("ONCO_SMOKE_IDP_NEG_TOKEN_EXPIRED")
    not_yet_valid_token = _idp_negative_token("ONCO_SMOKE_IDP_NEG_TOKEN_NOT_YET_VALID")
    iat_in_future_token = _idp_negative_token("ONCO_SMOKE_IDP_NEG_TOKEN_IAT_IN_FUTURE")
    missing_jti_token = _idp_negative_token("ONCO_SMOKE_IDP_NEG_TOKEN_MISSING_JTI")
    replay_token = _idp_negative_token("ONCO_SMOKE_IDP_NEG_TOKEN_REPLAY")
    malformed_token = _idp_negative_token("ONCO_SMOKE_IDP_NEG_TOKEN_MALFORMED")
    alg_not_allowed_token = _idp_negative_token("ONCO_SMOKE_IDP_NEG_TOKEN_ALG_NOT_ALLOWED")
    invalid_signature_token = _idp_negative_token("ONCO_SMOKE_IDP_NEG_TOKEN_INVALID_SIGNATURE")
    invalid_signature_reason = (
        _idp_negative_token("ONCO_SMOKE_IDP_NEG_TOKEN_INVALID_SIGNATURE_REASON")
        or "idp_signature_invalid_rs256"
    )

    can_build_hs256_negative = bool(_idp_secret())
    if not missing_user_token and can_build_hs256_negative:
        missing_user_token = _build_hs256_idp_token("admin", drop_claims={user_claim})
    if not invalid_user_token and can_build_hs256_negative:
        invalid_user_token = _build_hs256_idp_token("admin", payload_overrides={user_claim: "bad user id !"})
    if not invalid_role_token and can_build_hs256_negative:
        invalid_role_token = _build_hs256_idp_token("admin", payload_overrides={role_claim: "superadmin"})
    if not issuer_mismatch_token and can_build_hs256_negative:
        issuer_mismatch_token = _build_hs256_idp_token("admin", payload_overrides={"iss": "https://idp.invalid/mismatch"})
    if not audience_mismatch_token and can_build_hs256_negative:
        audience_mismatch_token = _build_hs256_idp_token("admin", payload_overrides={"aud": "oncoai-bff-mismatch"})
    if can_build_hs256_negative:
        now = int(time.time())
        if not expired_token:
            expired_token = _build_hs256_idp_token(
                "admin",
                payload_overrides={"iat": now - 1_200, "nbf": now - 1_300, "exp": now - 600},
            )
        if not not_yet_valid_token:
            not_yet_valid_token = _build_hs256_idp_token("admin", payload_overrides={"nbf": now + 3_600})
        if not iat_in_future_token:
            iat_in_future_token = _build_hs256_idp_token(
                "admin",
                payload_overrides={"iat": now + 3_600, "nbf": now - 1, "exp": now + 7_200},
            )
        if not missing_jti_token:
            missing_jti_token = _build_hs256_idp_token("admin", drop_claims={"jti"})
        if not replay_token:
            replay_token = _build_hs256_idp_token("admin")

    allowed_algs = _idp_allowed_algs()
    if not malformed_token:
        malformed_token = "not-a-jwt"
    if not alg_not_allowed_token:
        disallowed_alg = next((alg for alg in ("ES256", "PS256", "HS512", "RS512") if alg not in allowed_algs), "")
        if disallowed_alg:
            alg_not_allowed_token = _build_mock_idp_token(disallowed_alg)
    if not invalid_signature_token:
        if "RS256" in allowed_algs:
            invalid_signature_token = _build_mock_idp_token("RS256")
            invalid_signature_reason = "idp_signature_invalid_rs256"
        elif "HS256" in allowed_algs:
            invalid_signature_token = _build_mock_idp_token("HS256")
            invalid_signature_reason = "idp_signature_invalid_hs256"

    if not (
        missing_user_token
        and invalid_user_token
        and invalid_role_token
        and issuer_mismatch_token
        and audience_mismatch_token
        and expired_token
        and not_yet_valid_token
        and iat_in_future_token
        and missing_jti_token
        and replay_token
        and malformed_token
        and alg_not_allowed_token
        and invalid_signature_token
    ):
        raise RuntimeError(
            "idp negative-claim checks require either HS256 secret "
            "(ONCO_SMOKE_IDP_SECRET/SESSION_IDP_HS256_SECRET) or explicit tokens: "
            "ONCO_SMOKE_IDP_NEG_TOKEN_MISSING_USER_ID, "
            "ONCO_SMOKE_IDP_NEG_TOKEN_INVALID_USER_ID, "
            "ONCO_SMOKE_IDP_NEG_TOKEN_INVALID_ROLE, "
            "ONCO_SMOKE_IDP_NEG_TOKEN_ISSUER_MISMATCH, "
            "ONCO_SMOKE_IDP_NEG_TOKEN_AUDIENCE_MISMATCH, "
            "ONCO_SMOKE_IDP_NEG_TOKEN_EXPIRED, "
            "ONCO_SMOKE_IDP_NEG_TOKEN_NOT_YET_VALID, "
            "ONCO_SMOKE_IDP_NEG_TOKEN_IAT_IN_FUTURE, "
            "ONCO_SMOKE_IDP_NEG_TOKEN_MISSING_JTI, "
            "ONCO_SMOKE_IDP_NEG_TOKEN_REPLAY, "
            "ONCO_SMOKE_IDP_NEG_TOKEN_MALFORMED, "
            "ONCO_SMOKE_IDP_NEG_TOKEN_ALG_NOT_ALLOWED, "
            "ONCO_SMOKE_IDP_NEG_TOKEN_INVALID_SIGNATURE "
            "(or set ONCO_SMOKE_REQUIRE_IDP_NEGATIVE=false to skip)"
        )

    _require_idp_login_rejected(
        base_url,
        token=malformed_token,
        expected_reason="idp_invalid_jwt_format",
        action="idp malformed token check",
    )
    _require_idp_login_rejected(
        base_url,
        token=alg_not_allowed_token,
        expected_reason="idp_alg_not_allowed",
        action="idp alg allowlist check",
    )
    _require_idp_login_rejected(
        base_url,
        token=invalid_signature_token,
        expected_reason=invalid_signature_reason,
        action="idp signature validation check",
    )

    _require_idp_login_rejected(
        base_url,
        token=missing_user_token,
        expected_reason="idp_user_id_missing",
        action="idp missing user-id claim check",
    )
    _require_idp_login_rejected(
        base_url,
        token=invalid_user_token,
        expected_reason="idp_user_id_invalid_format",
        action="idp invalid user-id format check",
    )
    _require_idp_login_rejected(
        base_url,
        token=invalid_role_token,
        expected_reason="idp_claims_missing_identity_or_role_not_allowed",
        action="idp role allowlist check",
    )
    _require_idp_login_rejected(
        base_url,
        token=issuer_mismatch_token,
        expected_reason="idp_issuer_mismatch",
        action="idp issuer mismatch check",
    )
    _require_idp_login_rejected(
        base_url,
        token=audience_mismatch_token,
        expected_reason="idp_audience_mismatch",
        action="idp audience mismatch check",
    )
    _require_idp_login_rejected(
        base_url,
        token=expired_token,
        expected_reason="idp_token_expired",
        action="idp token expired check",
    )
    _require_idp_login_rejected(
        base_url,
        token=not_yet_valid_token,
        expected_reason="idp_token_not_yet_valid",
        action="idp token nbf check",
    )
    _require_idp_login_rejected(
        base_url,
        token=iat_in_future_token,
        expected_reason="idp_iat_in_future",
        action="idp token iat check",
    )
    _require_idp_login_rejected(
        base_url,
        token=missing_jti_token,
        expected_reason="idp_jti_missing",
        action="idp token jti required check",
    )
    replay_status, replay_text, _, _ = _session_login(base_url, {"id_token": replay_token})
    try:
        replay_payload = json.loads(replay_text) if replay_text else {}
    except json.JSONDecodeError:
        replay_payload = {"raw": replay_text}
    if not (200 <= replay_status < 300):
        raise RuntimeError(
            "idp replay setup login should succeed on first try, "
            f"got HTTP {replay_status}, payload={replay_payload}"
        )
    _require_idp_login_rejected(
        base_url,
        token=replay_token,
        expected_reason="idp_token_replay_detected",
        action="idp token replay check",
    )


def _poll_reindex(base_url: str, max_attempts: int) -> dict:
    # Reindex start call can include a full synchronous pass in backend before returning.
    # Keep it more tolerant than generic API requests to avoid false smoke failures on larger doc sets.
    # Real-world local runs can exceed 5 minutes for first full pass under strict_full.
    reindex_start_timeout_sec = max(DEFAULT_HTTP_TIMEOUT_SEC, 600)
    reindex_start_retries = 2
    last_start_error: Exception | None = None
    status = 0
    payload: dict = {}
    for attempt in range(reindex_start_retries):
        try:
            status, payload = _request_json(
                method="POST",
                url=f"{base_url.rstrip('/')}/api/admin/reindex",
                headers=_role_headers("admin", base_url=base_url),
                timeout=reindex_start_timeout_sec,
            )
            last_start_error = None
            break
        except Exception as exc:  # noqa: BLE001
            last_start_error = exc
            if attempt + 1 >= reindex_start_retries:
                raise RuntimeError(
                    "reindex start request failed after retries; "
                    f"timeout_sec={reindex_start_timeout_sec}, retries={reindex_start_retries}, "
                    f"last_error={type(exc).__name__}: {exc}"
                ) from exc
            time.sleep(0.5)
    if last_start_error is not None:
        raise RuntimeError("reindex start request failed with no successful retry")
    _require_ok(status, payload, "reindex start")

    job_id = payload.get("job_id")
    if not job_id:
        raise RuntimeError(f"reindex start returned no job_id: {payload}")

    for _ in range(max_attempts):
        poll_status, poll_payload = _request_json(
            method="GET",
            url=f"{base_url.rstrip('/')}/api/admin/reindex/{job_id}",
            headers=_role_headers("admin", base_url=base_url),
        )
        _require_ok(poll_status, poll_payload, "reindex poll")
        state = str(poll_payload.get("status", ""))
        if state in {"done", "failed"}:
            if state != "done":
                raise RuntimeError(f"reindex job failed: {poll_payload}")
            return poll_payload
        time.sleep(0.5)

    raise RuntimeError(f"reindex did not complete in time for job_id={job_id}")


def _require_audit_export(base_url: str) -> dict[str, int]:
    def _expect_bad_request(url: str, action: str) -> None:
        invalid_status, invalid_payload = _request_json_with_role_retry(
            method="GET",
            url=url,
            base_url=base_url,
            role="admin",
        )
        if invalid_status != 400:
            raise RuntimeError(
                f"{action} should return HTTP 400, got={invalid_status}, payload={invalid_payload}"
            )
        invalid_error_code = str(invalid_payload.get("error_code") or "")
        if invalid_error_code != "BFF_BAD_REQUEST":
            raise RuntimeError(
                f"{action} should return BFF_BAD_REQUEST in error_code, got payload={invalid_payload}"
            )
        if str(invalid_payload.get("code") or "") != "BFF_BAD_REQUEST":
            raise RuntimeError(
                f"{action} should keep backward-compatible code=BFF_BAD_REQUEST, got payload={invalid_payload}"
            )

    formula_user_id = "=smoke_csv_formula_user"
    revoke_status, revoke_payload = _request_json_with_role_retry(
        method="POST",
        url=f"{base_url.rstrip('/')}/api/session/revoke",
        base_url=base_url,
        role="admin",
        payload={"scope": "user", "user_id": formula_user_id},
    )
    _require_ok(revoke_status, revoke_payload, "session revoke user for csv formula guard")

    revoke_status_2, revoke_payload_2 = _request_json_with_role_retry(
        method="POST",
        url=f"{base_url.rstrip('/')}/api/session/revoke",
        base_url=base_url,
        role="admin",
        payload={"scope": "user", "user_id": "smoke_export_truncate_anchor"},
    )
    _require_ok(revoke_status_2, revoke_payload_2, "session revoke user for export truncation check")

    _expect_bad_request(
        f"{base_url.rstrip('/')}/api/session/audit/export?format=json&max_events=abc",
        "session audit export invalid max_events",
    )
    _expect_bad_request(
        f"{base_url.rstrip('/')}/api/session/audit/export?format=json&max_pages=0",
        "session audit export invalid max_pages",
    )
    _expect_bad_request(
        f"{base_url.rstrip('/')}/api/session/audit/export?format=json&limit=-1",
        "session audit export invalid limit",
    )

    json_status, json_text, json_headers = _http_call_with_role_retry(
        method="GET",
        url=f"{base_url.rstrip('/')}/api/session/audit/export?format=json&all=1&limit=50",
        base_url=base_url,
        role="admin",
    )
    try:
        json_payload = json.loads(json_text) if json_text else {}
    except json.JSONDecodeError:
        json_payload = {"raw": json_text}
    _require_ok(json_status, json_payload, "session audit export json")
    content_type = str(json_headers.get("content-type", "")).lower()
    if "application/json" not in content_type:
        raise RuntimeError(f"session audit export json has unexpected content-type: {json_headers.get('content-type')}")
    disposition = str(json_headers.get("content-disposition", "")).lower()
    if "attachment" not in disposition:
        raise RuntimeError(
            f"session audit export json has no attachment disposition: {json_headers.get('content-disposition')}"
        )
    events = json_payload.get("events")
    if not isinstance(events, list):
        raise RuntimeError(f"session audit export json payload has no events list: {json_payload}")

    trunc_status, trunc_text, trunc_headers = _http_call_with_role_retry(
        method="GET",
        url=f"{base_url.rstrip('/')}/api/session/audit/export?format=json&all=1&limit=50&max_events=1",
        base_url=base_url,
        role="admin",
    )
    try:
        trunc_payload = json.loads(trunc_text) if trunc_text else {}
    except json.JSONDecodeError:
        trunc_payload = {"raw": trunc_text}
    _require_ok(trunc_status, trunc_payload, "session audit export json truncation")
    trunc_events = trunc_payload.get("events")
    if not isinstance(trunc_events, list):
        raise RuntimeError(f"session audit export truncation payload has no events list: {trunc_payload}")
    if len(trunc_events) > 1:
        raise RuntimeError(f"session audit export truncation exceeded max_events=1: {len(trunc_events)}")
    trunc_count = int(trunc_payload.get("count", -1))
    if trunc_count > 1:
        raise RuntimeError(f"session audit export truncation count exceeded max_events=1: {trunc_count}")
    if str(trunc_headers.get("x-onco-export-max-events", "")) != "1":
        raise RuntimeError(
            f"session audit export truncation has unexpected x-onco-export-max-events: {trunc_headers.get('x-onco-export-max-events')}"
        )
    if str(trunc_headers.get("x-onco-export-truncated", "")) != "1":
        raise RuntimeError(
            f"session audit export truncation missing x-onco-export-truncated=1: {trunc_headers.get('x-onco-export-truncated')}"
        )
    trunc_reason = str(trunc_headers.get("x-onco-export-truncated-reason", "")).strip()
    if trunc_reason not in {"max_events", "max_pages", "upstream"}:
        raise RuntimeError(
            "session audit export truncation has unexpected x-onco-export-truncated-reason: "
            f"{trunc_headers.get('x-onco-export-truncated-reason')}"
        )

    csv_status, csv_text, csv_headers = _http_call_with_role_retry(
        method="GET",
        url=f"{base_url.rstrip('/')}/api/session/audit/export?format=csv&all=1&limit=50",
        base_url=base_url,
        role="admin",
    )
    if not (200 <= csv_status < 300):
        raise RuntimeError(f"session audit export csv failed: HTTP {csv_status}, body={csv_text!r}")
    csv_content_type = str(csv_headers.get("content-type", "")).lower()
    if "text/csv" not in csv_content_type:
        raise RuntimeError(f"session audit export csv has unexpected content-type: {csv_headers.get('content-type')}")
    csv_disposition = str(csv_headers.get("content-disposition", "")).lower()
    if "attachment" not in csv_disposition:
        raise RuntimeError(
            f"session audit export csv has no attachment disposition: {csv_headers.get('content-disposition')}"
        )
    lines = csv_text.splitlines()
    expected_csv_header = "timestamp,event,outcome,role,user_id,session_id,actor_user_id,correlation_id,reason_group,reason,path"
    if not lines or lines[0].strip() != expected_csv_header:
        raise RuntimeError(f"session audit export csv header mismatch: got={lines[0] if lines else '<empty>'!r}")
    if f"'{formula_user_id}" not in csv_text:
        raise RuntimeError("session audit export csv does not contain spreadsheet-formula guard prefix for user_id")
    return {
        "json_events": len(events),
        "csv_rows": max(0, len(lines) - 1),
        "truncated_events": len(trunc_events),
    }


def _require_audit_summary(base_url: str) -> dict[str, int]:
    status, payload = _request_json_with_role_retry(
        method="GET",
        url=f"{base_url.rstrip('/')}/api/session/audit/summary?window_hours=24",
        base_url=base_url,
        role="admin",
    )
    _require_ok(status, payload, "session audit summary")
    total_events = int(payload.get("total_events") or 0)
    unique_users = int(payload.get("unique_users") or 0)
    outcome_counts = payload.get("outcome_counts")
    if not isinstance(outcome_counts, dict):
        raise RuntimeError(f"session audit summary missing outcome_counts: {payload}")
    for key in ("allow", "deny", "info", "error"):
        if key not in outcome_counts:
            raise RuntimeError(f"session audit summary missing outcome={key}: {payload}")
    top_reasons = payload.get("top_reasons")
    if not isinstance(top_reasons, list):
        raise RuntimeError(f"session audit summary missing top_reasons list: {payload}")
    incident_level = str(payload.get("incident_level") or "").strip().lower()
    if incident_level not in {"none", "low", "medium", "high"}:
        raise RuntimeError(f"session audit summary missing/invalid incident_level: {payload}")
    try:
        incident_score = int(payload.get("incident_score") or 0)
    except (TypeError, ValueError):
        raise RuntimeError(f"session audit summary has invalid incident_score: {payload}") from None
    if incident_score < 0 or incident_score > 100:
        raise RuntimeError(f"session audit summary incident_score out of range [0..100]: {payload}")

    incident_signals = payload.get("incident_signals")
    if not isinstance(incident_signals, dict):
        raise RuntimeError(f"session audit summary missing incident_signals object: {payload}")
    for key in (
        "deny_rate",
        "error_count",
        "replay_detected_count",
        "config_error_count",
        "min_events_for_deny_rate_alert",
    ):
        if key not in incident_signals:
            raise RuntimeError(f"session audit summary missing incident_signals.{key}: {payload}")

    alerts = payload.get("alerts")
    if not isinstance(alerts, list):
        raise RuntimeError(f"session audit summary missing alerts list: {payload}")
    return {
        "total_events": total_events,
        "unique_users": unique_users,
        "incident_level": 1 if incident_level in {"low", "medium", "high"} else 0,
        "alerts_count": len(alerts),
    }


def _require_session_csrf_guard(base_url: str) -> dict[str, str]:
    enabled = str(os.environ.get("ONCO_SMOKE_CHECK_SESSION_CSRF", "false")).strip().lower()
    if enabled in {"0", "false", "no", "off"}:
        return {"checked": "false", "reason": ""}

    headers = _role_headers(
        "admin",
        base_url=base_url,
        extra={
            "origin": "https://attacker.example",
            "sec-fetch-site": "cross-site",
        },
    )
    status, payload = _request_json(
        method="POST",
        url=f"{base_url.rstrip('/')}/api/session/revoke",
        headers=headers,
        payload={"scope": "self"},
    )
    if status != 403:
        raise RuntimeError(f"session csrf check failed: expected HTTP 403, got={status}, payload={payload}")
    code = str(payload.get("error_code") or "")
    if code != "BFF_FORBIDDEN":
        raise RuntimeError(
            "session csrf check failed: expected error_code=BFF_FORBIDDEN, "
            f"got payload={payload}"
        )
    reason = str(payload.get("reason") or "").strip()
    if reason not in {"csrf_origin_mismatch", "csrf_context_missing_or_cross_site"}:
        raise RuntimeError(
            "session csrf check failed: expected reason csrf_origin_mismatch|csrf_context_missing_or_cross_site, "
            f"got payload={payload}"
        )
    return {"checked": "true", "reason": reason}


def main() -> None:
    parser = argparse.ArgumentParser(description="E2E smoke: /admin -> /doctor -> /patient(report)")
    parser.add_argument("--base-url", default="http://localhost:3000")
    parser.add_argument("--pdf", default="")
    parser.add_argument("--skip-upload", action="store_true")
    parser.add_argument("--reindex-polls", type=int, default=20)
    parser.add_argument("--schema-version", choices=["0.1", "0.2"], default="0.1")
    parser.add_argument(
        "--auth-mode",
        choices=["auto", "demo", "credentials", "idp"],
        default=os.environ.get("ONCO_SMOKE_AUTH_MODE", "auto"),
        help="Session bootstrap mode for /api/session/login (default: env ONCO_SMOKE_AUTH_MODE or auto)",
    )
    parser.add_argument(
        "--case-flow",
        action="store_true",
        help="Use case import + analyze(case_id) pack flow (requires schema-version=0.2)",
    )
    parser.add_argument(
        "--gastric-flow",
        action="store_true",
        help="Run gastric e2e flow using payloads from ONCOAI_GASTRIC_PACK_DIR (default: /Users/meledre/Downloads/json_pack)",
    )
    parser.add_argument(
        "--multi-onco-flow",
        action="store_true",
        help="Run multi-oncology e2e flow (C16/C34/C50) using file import + analyze + patient endpoint",
    )
    parser.add_argument(
        "--routing-baseline-candidates",
        type=int,
        default=0,
        help="Baseline candidate chunk count before routing (optional, for performance gate)",
    )
    parser.add_argument(
        "--min-routing-reduction",
        type=float,
        default=0.0,
        help="Require routing candidate reduction ratio vs baseline, e.g. 0.4 for 40%%",
    )
    parser.add_argument(
        "--multi-onco-cases",
        default="",
        help="Optional comma-separated subset for --multi-onco-flow, e.g. C16,C34 (default: all C16,C34,C50)",
    )
    parser.add_argument(
        "--pdf-page-flow",
        action="store_true",
        help="Run additional PDF page-flow via BFF (/api/case/import-file -> /api/analyze -> /api/patient/analyze)",
    )
    parser.add_argument(
        "--skip-pdf-page-flow",
        action="store_true",
        help="Skip PDF page-flow checks even when --pdf-page-flow is provided",
    )
    parser.add_argument(
        "--require-vector-backend",
        default="",
        help="Require run_meta.vector_backend to match value",
    )
    parser.add_argument(
        "--require-embedding-backend",
        default="",
        help="Require run_meta.embedding_backend to match value",
    )
    parser.add_argument(
        "--require-reranker-backend",
        default="",
        help="Require run_meta.reranker_backend to match value",
    )
    parser.add_argument(
        "--require-report-generation-path",
        default="",
        help="Require run_meta.report_generation_path (primary|fallback|deterministic_only)",
    )
    parser.add_argument(
        "--require-reasoning-mode",
        default="",
        help="Require run_meta.reasoning_mode (compat|llm_rag_only)",
    )
    parser.add_argument(
        "--require-llm-path",
        default="",
        help="Require run_meta.llm_path (primary|fallback|deterministic)",
    )
    parser.add_argument(
        "--require-fallback-reason",
        default="",
        help="Require run_meta.fallback_reason (for strict expect none)",
    )
    parser.add_argument(
        "--browser-console-log",
        default="",
        help="Path to browser console log file; fails if hydration mismatch markers are found",
    )
    parser.add_argument(
        "--case-file",
        default="",
        help="Optional local case file path for --pdf-page-flow (PDF/DOCX/TXT/MD)",
    )
    args = parser.parse_args()
    global _SMOKE_AUTH_MODE
    _SMOKE_AUTH_MODE = str(args.auth_mode).strip().lower()
    if args.pdf_page_flow and args.skip_pdf_page_flow:
        raise RuntimeError("--pdf-page-flow and --skip-pdf-page-flow are mutually exclusive")

    selected_case_flows = sum(1 for enabled in (args.case_flow, args.gastric_flow, args.multi_onco_flow) if enabled)
    if selected_case_flows > 1:
        raise RuntimeError("--case-flow, --gastric-flow and --multi-onco-flow are mutually exclusive")

    base_url = args.base_url.rstrip("/")
    _require_session_error_contract(base_url)
    _require_role_spoof_blocked(base_url)
    if _smoke_auth_mode() == "idp":
        _require_idp_login_contract(base_url)
        _require_idp_claim_checks(base_url)
    docs_status, docs_payload = _request_json(
        method="GET",
        url=f"{base_url}/api/admin/docs",
        headers=_role_headers("admin", base_url=base_url),
    )
    _require_ok(docs_status, docs_payload, "admin docs")

    reindex_payload: dict = {}
    case_id = ""
    import_run_id = ""
    flow_citations_count = 0
    flow_sources_used: list[str] = []
    flow_issues_count = 0
    multi_onco_cases: list[dict[str, Any]] = []
    multi_onco_min_ratio = 0.0
    multi_onco_match_strategies: list[str] = []
    pdf_page_flow_stats: dict[str, Any] = {}

    if args.gastric_flow:
        if args.schema_version != "0.2":
            raise RuntimeError("--gastric-flow requires --schema-version 0.2")
        gastric_pack_dir = str(os.environ.get("ONCOAI_GASTRIC_PACK_DIR", DEFAULT_GASTRIC_PACK_DIR)).strip() or DEFAULT_GASTRIC_PACK_DIR
        gastric_result = _run_gastric_flow(
            base_url=base_url,
            max_attempts=args.reindex_polls,
            pack_dir=gastric_pack_dir,
        )
        reindex_payload = gastric_result.get("reindex_payload") if isinstance(gastric_result.get("reindex_payload"), dict) else {}
        case_id = str(gastric_result.get("case_id") or "").strip()
        import_run_id = str(gastric_result.get("import_run_id") or "").strip()
        flow_citations_count = int(gastric_result.get("citations_count") or 0)
        flow_issues_count = int(gastric_result.get("issues_count") or 0)
        flow_sources_used = [str(item) for item in gastric_result.get("sources_used", []) if str(item).strip()]
        analyze_payload = gastric_result.get("analyze_response")
        if not isinstance(analyze_payload, dict):
            raise RuntimeError(f"gastric flow returned invalid analyze payload: {gastric_result}")
    elif args.multi_onco_flow:
        if args.schema_version != "0.2":
            raise RuntimeError("--multi-onco-flow requires --schema-version 0.2")
        selected_multi_cases = [
            token.strip().upper()
            for token in str(args.multi_onco_cases or "").split(",")
            if token.strip()
        ]
        multi_result = _run_multi_onco_flow(
            base_url=base_url,
            max_attempts=args.reindex_polls,
            min_routing_reduction=float(args.min_routing_reduction),
            selected_cases=selected_multi_cases,
        )
        reindex_payload = multi_result.get("reindex_payload") if isinstance(multi_result.get("reindex_payload"), dict) else {}
        case_id = str(multi_result.get("case_id") or "").strip()
        import_run_id = str(multi_result.get("import_run_id") or "").strip()
        flow_citations_count = int(multi_result.get("citations_count") or 0)
        flow_issues_count = int(multi_result.get("issues_count") or 0)
        flow_sources_used = [str(item) for item in multi_result.get("sources_used", []) if str(item).strip()]
        multi_onco_cases = [
            item
            for item in (multi_result.get("cases") if isinstance(multi_result.get("cases"), list) else [])
            if isinstance(item, dict)
        ]
        multi_onco_min_ratio = float(multi_result.get("min_routing_reduction_ratio") or 0.0)
        multi_onco_match_strategies = [
            str(item).strip()
            for item in (multi_result.get("match_strategies") if isinstance(multi_result.get("match_strategies"), list) else [])
            if str(item).strip()
        ]
        analyze_payload = multi_result.get("analyze_response")
        if not isinstance(analyze_payload, dict):
            raise RuntimeError(f"multi-onco flow returned invalid analyze payload: {multi_result}")
    else:
        if not args.skip_upload:
            file_name, file_bytes = _load_pdf(args.pdf or None)
            boundary, multipart_body = _build_multipart_body(
                {
                    "doc_id": "guideline_nsclc_smoke",
                    "doc_version": _default_smoke_doc_version(),
                    "source_set": "minzdrav",
                    "cancer_type": "nsclc_egfr",
                    "language": "ru",
                    "source_url": "https://minzdrav.gov.ru/docs/onco/smoke-guideline-nsclc.pdf",
                },
                file_name=file_name,
                file_bytes=file_bytes,
            )
            upload_status, upload_text = _http_call(
                method="POST",
                url=f"{base_url}/api/admin/upload",
                headers=_role_headers(
                    "admin",
                    base_url=base_url,
                    extra={"content-type": f"multipart/form-data; boundary={boundary}"},
                ),
                body=multipart_body,
            )
            try:
                upload_payload = json.loads(upload_text) if upload_text else {}
            except json.JSONDecodeError:
                upload_payload = {"raw": upload_text}
            _require_ok(upload_status, upload_payload, "admin upload")

            if str(os.getenv("ONCO_SMOKE_EXERCISE_ADMIN_RELEASE_WORKFLOW", "true")).strip().lower() in {"1", "true", "yes", "on"}:
                uploaded_doc_id = str(upload_payload.get("doc_id") or "guideline_nsclc_smoke").strip()
                uploaded_doc_version = str(upload_payload.get("doc_version") or "").strip()
                if not uploaded_doc_version:
                    uploaded_doc_version = _default_smoke_doc_version()
                _run_admin_doc_release_workflow(
                    base_url,
                    doc_id=uploaded_doc_id,
                    doc_version=uploaded_doc_version,
                )

        if _skip_reindex_requested():
            reindex_payload = {
                "status": "skipped",
                "reason": "ONCO_SMOKE_SKIP_REINDEX",
            }
        else:
            reindex_payload = _poll_reindex(base_url, max_attempts=args.reindex_polls)

        if args.case_flow:
            if args.schema_version != "0.2":
                raise RuntimeError("--case-flow requires --schema-version 0.2")

            import_payload = {
                "schema_version": "1.0",
                "import_profile": "FREE_TEXT",
                "language": "ru",
                "free_text": (
                    "Синтетический кейс для e2e smoke case_id flow: "
                    "аденокарцинома легкого (НМРЛ), ICD-10 C34, стадия IV, EGFR L858R. "
                    "Рекомендована системная терапия: осимертиниб 80 мг ежедневно."
                ),
            }
            import_status, import_response = _request_json(
                method="POST",
                url=f"{base_url}/api/case/import",
                headers=_role_headers("clinician", base_url=base_url),
                payload=import_payload,
            )
            _require_ok(import_status, import_response, "case import")
            import_run_id = str(import_response.get("import_run_id", "")).strip()
            if not import_run_id:
                raise RuntimeError(f"case import returned no import_run_id: {import_response}")
            case_id = str(import_response.get("case_id", "")).strip()
            if not case_id:
                raise RuntimeError(f"case import returned no case_id: {import_response}")

            runs_status, runs_payload = _request_json(
                method="GET",
                url=f"{base_url}/api/case/import/runs?limit=1",
                headers=_role_headers("clinician", base_url=base_url),
            )
            _require_ok(runs_status, runs_payload, "case import runs")
            runs = runs_payload.get("runs") if isinstance(runs_payload, dict) else None
            if not isinstance(runs, list) or not runs:
                raise RuntimeError(f"case import runs returned empty payload: {runs_payload}")
            if str(runs[0].get("import_run_id", "")).strip() != import_run_id:
                raise RuntimeError(f"case import runs did not return latest import_run_id: {runs_payload}")

            run_status, run_payload = _request_json(
                method="GET",
                url=f"{base_url}/api/case/import/{import_run_id}",
                headers=_role_headers("clinician", base_url=base_url),
            )
            _require_ok(run_status, run_payload, "case import run get")
            if str(run_payload.get("case_id", "")).strip() != case_id:
                raise RuntimeError(f"case import run payload has unexpected case_id: {run_payload}")

            case_get_status, case_get_payload = _request_json(
                method="GET",
                url=f"{base_url}/api/case/{case_id}",
                headers=_role_headers("clinician", base_url=base_url),
            )
            _require_ok(case_get_status, case_get_payload, "case get")
            if case_get_payload.get("schema_version") != "1.0":
                raise RuntimeError(f"case get returned invalid schema_version: {case_get_payload}")

            analyze_request = {
                "schema_version": "0.2",
                "request_id": str(uuid.uuid4()),
                "query_type": "CHECK_LAST_TREATMENT",
                "sources": {"mode": "SINGLE", "source_ids": ["minzdrav"]},
                "language": "ru",
                "case": {"case_id": case_id},
                "options": {"strict_evidence": True, "max_chunks": 40, "max_citations": 40, "timeout_ms": 120000},
            }
        else:
            if args.schema_version == "0.2":
                inline_case_id = str(uuid.uuid4())
                analyze_request = {
                    "schema_version": "0.2",
                    "request_id": "e2e-smoke-001",
                    "query_type": "CHECK_LAST_TREATMENT",
                    "sources": {"mode": "SINGLE", "source_ids": ["minzdrav"]},
                    "language": "ru",
                    "case": {
                        "case_json": {
                            "schema_version": "1.0",
                            "case_id": inline_case_id,
                            "import_profile": "CUSTOM_TEMPLATE",
                            "patient": {"sex": "female", "birth_year": 1963},
                            "diagnoses": [
                                {
                                    "diagnosis_id": str(uuid.uuid4()),
                                    "disease_id": str(uuid.uuid4()),
                                    "icd10": "C34",
                                    "histology": "adenocarcinoma",
                                    "stage": {"system": "TNM8", "stage_group": "IV"},
                                    "biomarkers": [{"name": "EGFR", "value": "L858R"}],
                                    "timeline": [],
                                    "last_plan": {
                                        "date": "2026-02-20",
                                        "precision": "day",
                                        "regimen": "Осимертиниб 80 мг ежедневно",
                                        "line": 1,
                                        "cycle": 1,
                                    },
                                }
                            ],
                            "attachments": [],
                            "notes": "Синтетический обезличенный кейс для smoke-прогона.",
                        }
                    },
                    "options": {"strict_evidence": True, "max_chunks": 40, "max_citations": 40, "timeout_ms": 120000},
                }
            else:
                analyze_request = {
                    "schema_version": args.schema_version,
                    "request_id": "e2e-smoke-001",
                    "case": {
                        "cancer_type": "nsclc_egfr",
                        "language": "ru",
                        "notes": "Синтетический обезличенный кейс для smoke-прогона.",
                    },
                    "treatment_plan": {
                        "plan_text": "Системная терапия: осимертиниб 80 мг ежедневно",
                    },
                    "kb_filters": {
                        "source_set": "minzdrav",
                    },
                    "return_patient_explain": True,
                }

        analyze_status, analyze_payload = _request_json(
            method="POST",
            url=f"{base_url}/api/analyze",
            headers=_role_headers("clinician", base_url=base_url, extra={"x-client-id": "e2e-smoke"}),
            payload=analyze_request,
        )
        _require_ok(analyze_status, analyze_payload, "doctor analyze")

    if args.pdf_page_flow and not args.skip_pdf_page_flow:
        gastric_pack_dir = str(os.environ.get("ONCOAI_GASTRIC_PACK_DIR", DEFAULT_GASTRIC_PACK_DIR)).strip() or DEFAULT_GASTRIC_PACK_DIR
        pdf_page_flow_stats = _run_pdf_page_flow(
            base_url=base_url,
            pack_dir=gastric_pack_dir,
            case_file=str(args.case_file or "").strip(),
        )

    audit_export_stats = _require_audit_export(base_url)
    audit_summary_stats = _require_audit_summary(base_url)
    csrf_stats = _require_session_csrf_guard(base_url)

    doctor_report = analyze_payload.get("doctor_report") or {}
    patient_explain = analyze_payload.get("patient_explain") or {}
    run_meta_payload = analyze_payload.get("run_meta") if isinstance(analyze_payload.get("run_meta"), dict) else {}
    run_meta_vector_backend = str(run_meta_payload.get("vector_backend") or "").strip()
    run_meta_embedding_backend = str(run_meta_payload.get("embedding_backend") or "").strip()
    run_meta_reranker_backend = str(run_meta_payload.get("reranker_backend") or "").strip()
    run_meta_report_generation_path = str(run_meta_payload.get("report_generation_path") or "").strip()
    run_meta_reasoning_mode = str(run_meta_payload.get("reasoning_mode") or "").strip()
    run_meta_llm_path = str(run_meta_payload.get("llm_path") or "").strip()
    run_meta_fallback_reason = str(run_meta_payload.get("fallback_reason") or "").strip()

    if args.require_vector_backend and run_meta_vector_backend != str(args.require_vector_backend).strip():
        raise RuntimeError(
            "vector backend gate failed: "
            f"expected={args.require_vector_backend}, got={run_meta_vector_backend}, run_meta={run_meta_payload}"
        )
    if args.require_embedding_backend and run_meta_embedding_backend != str(args.require_embedding_backend).strip():
        raise RuntimeError(
            "embedding backend gate failed: "
            f"expected={args.require_embedding_backend}, got={run_meta_embedding_backend}, run_meta={run_meta_payload}"
        )
    if args.require_reranker_backend and run_meta_reranker_backend != str(args.require_reranker_backend).strip():
        raise RuntimeError(
            "reranker backend gate failed: "
            f"expected={args.require_reranker_backend}, got={run_meta_reranker_backend}, run_meta={run_meta_payload}"
        )
    if args.require_report_generation_path and run_meta_report_generation_path != str(args.require_report_generation_path).strip():
        raise RuntimeError(
            "report generation path gate failed: "
            f"expected={args.require_report_generation_path}, got={run_meta_report_generation_path}, "
            f"run_meta={run_meta_payload}"
        )
    if args.require_reasoning_mode and run_meta_reasoning_mode != str(args.require_reasoning_mode).strip():
        raise RuntimeError(
            "reasoning mode gate failed: "
            f"expected={args.require_reasoning_mode}, got={run_meta_reasoning_mode}, run_meta={run_meta_payload}"
        )
    if args.require_llm_path and run_meta_llm_path != str(args.require_llm_path).strip():
        raise RuntimeError(
            "llm path gate failed: "
            f"expected={args.require_llm_path}, got={run_meta_llm_path}, run_meta={run_meta_payload}"
        )
    if args.require_fallback_reason and run_meta_fallback_reason != str(args.require_fallback_reason).strip():
        raise RuntimeError(
            "fallback reason gate failed: "
            f"expected={args.require_fallback_reason}, got={run_meta_fallback_reason}, run_meta={run_meta_payload}"
        )

    routing_meta_payload = (
        run_meta_payload.get("routing_meta")
        if isinstance(run_meta_payload.get("routing_meta"), dict)
        else {}
    )
    routing_candidate_chunks = int(routing_meta_payload.get("candidate_chunks") or 0)
    routing_source_ids = [
        str(item).strip()
        for item in (routing_meta_payload.get("source_ids") if isinstance(routing_meta_payload.get("source_ids"), list) else [])
        if str(item).strip()
    ]
    routing_doc_ids = [
        str(item).strip()
        for item in (routing_meta_payload.get("doc_ids") if isinstance(routing_meta_payload.get("doc_ids"), list) else [])
        if str(item).strip()
    ]
    routing_baseline_candidates = int(routing_meta_payload.get("baseline_candidate_chunks") or 0)
    routing_reduction_ratio = float(routing_meta_payload.get("reduction_ratio") or 0.0)
    if args.routing_baseline_candidates > 0:
        routing_baseline_candidates = max(1, int(args.routing_baseline_candidates))
        routing_reduction_ratio = max(0.0, 1.0 - (float(routing_candidate_chunks) / float(routing_baseline_candidates)))
    elif routing_baseline_candidates > 0 and routing_reduction_ratio <= 0:
        routing_reduction_ratio = max(0.0, 1.0 - (float(routing_candidate_chunks) / float(routing_baseline_candidates)))

    if args.min_routing_reduction > 0 and routing_reduction_ratio < float(args.min_routing_reduction):
        raise RuntimeError(
            "routing reduction gate failed: "
            f"reduction={routing_reduction_ratio:.3f}, "
            f"required={float(args.min_routing_reduction):.3f}, "
            f"baseline={routing_baseline_candidates}, candidate_chunks={routing_candidate_chunks}"
        )
    resolved_cancer_type = str(routing_meta_payload.get("resolved_cancer_type") or "").strip().lower()
    if not resolved_cancer_type or resolved_cancer_type == "unknown":
        raise RuntimeError(f"analyze response has unknown resolved_cancer_type in routing_meta: {routing_meta_payload}")
    report_id = doctor_report.get("report_id")
    if not report_id:
        raise RuntimeError(f"analyze response has no doctor_report.report_id: {analyze_payload}")
    if args.case_flow or args.gastric_flow or args.multi_onco_flow or args.schema_version == "0.2":
        if str(doctor_report.get("schema_version") or "") not in {"1.0", "1.2"}:
            raise RuntimeError(
                "case flow expects pack doctor_report schema_version in {1.0, 1.2}: "
                f"{doctor_report}"
            )
        if not patient_explain.get("safety_notes"):
            raise RuntimeError("case flow analyze response has no patient_explain.safety_notes")
        run_meta = analyze_payload.get("run_meta") or {}
        timings = run_meta.get("timings_ms") if isinstance(run_meta.get("timings_ms"), dict) else {}
        if "total" not in timings:
            raise RuntimeError("case flow analyze response has no run_meta.timings_ms.total")
    else:
        if not patient_explain.get("safety_disclaimer"):
            raise RuntimeError("analyze response has no patient_explain.safety_disclaimer")

    report_json_status, report_json_payload = _request_json(
        method="GET",
        url=f"{base_url}/api/report/{report_id}/json",
        headers=_role_headers("clinician", base_url=base_url),
    )
    _require_ok(report_json_status, report_json_payload, "report json")

    report_html_status, report_html_text = _http_call(
        method="GET",
        url=f"{base_url}/api/report/{report_id}/html",
        headers=_role_headers("clinician", base_url=base_url),
    )
    if not (200 <= report_html_status < 300 and "Doctor Report" in report_html_text):
        raise RuntimeError(f"report html failed: HTTP {report_html_status}")

    _require_login_rate_limit_contract(base_url)

    if not args.gastric_flow and not args.multi_onco_flow:
        flow_citations_count, flow_sources_used, flow_issues_count = _collect_pack_citation_metrics(analyze_payload)

    verification_summary = (
        doctor_report.get("verification_summary")
        if isinstance(doctor_report.get("verification_summary"), dict)
        else {}
    )
    verification_category = str(verification_summary.get("category") or "").strip().upper()
    # In strict LLM+RAG mode a fully compliant plan can legitimately produce zero issues.
    if flow_issues_count < 1 and verification_category != "OK":
        raise RuntimeError(
            "doctor_report quality gate failed: issues_count must be >=1 or verification_summary=OK, "
            f"got issues_count={flow_issues_count}, verification_category={verification_category}"
        )
    if flow_citations_count < 1:
        if not (_skip_reindex_requested() and args.case_flow):
            raise RuntimeError(
                f"doctor_report quality gate failed: citations_count must be >=1, got={flow_citations_count}"
            )
    if not _extract_patient_summary(analyze_payload):
        raise RuntimeError("patient_explain quality gate failed: summary must be non-empty")
    if (args.gastric_flow or args.multi_onco_flow) and not {"minzdrav", "russco"}.issubset(
        {item.strip() for item in flow_sources_used}
    ):
        raise RuntimeError(
            "source coverage gate failed for AUTO demo flow: expected sources minzdrav+russco, "
            f"got={flow_sources_used}"
        )
    if args.pdf_page_flow and not args.skip_pdf_page_flow:
        pdf_sources = [
            str(item).strip()
            for item in (pdf_page_flow_stats.get("doctor_sources_used") if isinstance(pdf_page_flow_stats.get("doctor_sources_used"), list) else [])
            if str(item).strip()
        ]
        if not {"minzdrav", "russco"}.issubset(set(pdf_sources)):
            raise RuntimeError(
                "source coverage gate failed for PDF page-flow: expected sources minzdrav+russco, "
                f"got={pdf_sources}"
            )

    if args.browser_console_log:
        log_path = Path(str(args.browser_console_log).strip())
        if not log_path.exists():
            raise RuntimeError(f"browser console log not found: {log_path}")
        console_text = log_path.read_text(encoding="utf-8", errors="ignore")
        hydration_markers = [
            "hydration mismatch",
            "hydrated but some attributes of the server rendered html didn't match",
            "a tree hydrated but some attributes of the server rendered html didn't match",
        ]
        lowered = console_text.lower()
        for marker in hydration_markers:
            if marker in lowered:
                raise RuntimeError(
                    f"browser console contains hydration mismatch marker: {marker}; log={log_path}"
                )

    summary = {
        "admin_docs_before": len(docs_payload.get("docs", [])),
        "reindex_status": reindex_payload.get("status"),
        "kb_version": doctor_report.get("kb_version"),
        "report_id": report_id,
        "issues": len(doctor_report.get("issues", [])),
        "patient_explain": bool(patient_explain),
        "schema_version": args.schema_version,
        "case_flow": bool(args.case_flow),
        "gastric_flow": bool(args.gastric_flow),
        "multi_onco_flow": bool(args.multi_onco_flow),
        "case_id": case_id or None,
        "import_run_id": import_run_id or None,
        "llm_path": (analyze_payload.get("run_meta") or {}).get("llm_path"),
        "reasoning_mode": run_meta_reasoning_mode or None,
        "report_generation_path": run_meta_report_generation_path or None,
        "fallback_reason": run_meta_fallback_reason or None,
        "vector_backend": run_meta_vector_backend or None,
        "embedding_backend": run_meta_embedding_backend or None,
        "reranker_backend": run_meta_reranker_backend or None,
        "citations_count": flow_citations_count,
        "sources_used": flow_sources_used,
        "issues_count": flow_issues_count,
        "multi_onco_cases": multi_onco_cases,
        "multi_onco_min_routing_reduction_ratio": round(multi_onco_min_ratio, 4),
        "multi_onco_match_strategies": multi_onco_match_strategies,
        "pdf_page_flow_enabled": bool(args.pdf_page_flow and not args.skip_pdf_page_flow),
        "pdf_page_flow": pdf_page_flow_stats,
        "routing_meta_match_strategy": routing_meta_payload.get("match_strategy"),
        "routing_meta_resolved_cancer_type": routing_meta_payload.get("resolved_cancer_type"),
        "routing_meta_sources": routing_source_ids,
        "routing_meta_docs": routing_doc_ids,
        "routing_meta_candidate_chunks": routing_candidate_chunks,
        "routing_meta_baseline_candidate_chunks": routing_baseline_candidates,
        "routing_reduction_ratio": round(routing_reduction_ratio, 4),
        "audit_export_json_events": audit_export_stats.get("json_events", 0),
        "audit_export_csv_rows": audit_export_stats.get("csv_rows", 0),
        "audit_export_truncated_events": audit_export_stats.get("truncated_events", 0),
        "session_audit_summary_total_events": audit_summary_stats.get("total_events", 0),
        "session_audit_summary_unique_users": audit_summary_stats.get("unique_users", 0),
        "session_audit_summary_incident_level_non_none": audit_summary_stats.get("incident_level", 0),
        "session_audit_summary_alerts_count": audit_summary_stats.get("alerts_count", 0),
        "session_csrf_checked": csrf_stats.get("checked", "false"),
        "session_csrf_reason": csrf_stats.get("reason", ""),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
