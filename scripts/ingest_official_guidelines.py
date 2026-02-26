#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SOURCE_SET_ALIASES: dict[str, str] = {
    "pdq": "nci_pdq",
}


def _request_timeout_sec() -> float:
    raw = str(os.getenv("ONCO_INGEST_HTTP_TIMEOUT_SEC", "60")).strip()
    try:
        parsed = float(raw)
    except ValueError:
        parsed = 60.0
    return max(1.0, min(parsed, 900.0))


def normalize_source_set_id(value: str) -> str:
    token = str(value or "").strip().lower()
    return SOURCE_SET_ALIASES.get(token, token)


@dataclass(frozen=True)
class UploadDoc:
    local_path: Path
    doc_id: str
    doc_version: str
    source_set: str
    source_page_url: str
    source_pdf_url: str
    doc_kind: str
    cancer_type: str
    icd10_prefixes: list[str]
    language: str = "ru"

    @property
    def source_url(self) -> str:
        pdf = str(self.source_pdf_url or "").strip()
        if pdf:
            return pdf
        return str(self.source_page_url or "").strip()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request_json(
    *,
    base_url: str,
    endpoint: str,
    method: str,
    token: str,
    role: str,
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    timeout_sec = _request_timeout_sec()
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url=f"{base_url.rstrip('/')}{endpoint}",
        method=method,
        data=data,
        headers={
            "content-type": "application/json",
            "x-demo-token": token,
            "x-role": role,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            raw = response.read().decode("utf-8")
            body = json.loads(raw) if raw.strip() else {}
            return int(response.status), body if isinstance(body, dict) else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="ignore")
        try:
            body = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            body = {"error": raw or str(exc)}
        return int(exc.code), body if isinstance(body, dict) else {"error": str(exc)}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, {"error": str(exc)}


def _upload_doc(base_url: str, token: str, role: str, item: UploadDoc) -> tuple[int, dict[str, Any]]:
    payload = {
        "filename": item.local_path.name,
        "content_base64": base64.b64encode(item.local_path.read_bytes()).decode("ascii"),
        "doc_id": item.doc_id,
        "doc_version": item.doc_version,
        "source_set": item.source_set,
        "source_url": item.source_url,
        "source_page_url": item.source_page_url,
        "source_pdf_url": item.source_pdf_url,
        "doc_kind": item.doc_kind,
        "cancer_type": item.cancer_type,
        "icd10_prefixes": item.icd10_prefixes,
        "language": item.language,
    }
    return _request_json(
        base_url=base_url,
        endpoint="/admin/upload",
        method="POST",
        token=token,
        role=role,
        payload=payload,
    )


def _run_doc_workflow(
    *,
    base_url: str,
    token: str,
    role: str,
    item: UploadDoc,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "doc_id": item.doc_id,
        "doc_version": item.doc_version,
        "doc_kind": item.doc_kind,
        "source_set": item.source_set,
        "source_url": item.source_url,
        "source_page_url": item.source_page_url,
        "source_pdf_url": item.source_pdf_url,
        "local_path": str(item.local_path),
        "steps": [],
    }
    upload_status, upload_body = _upload_doc(base_url, token, role, item)
    result["steps"].append({"step": "upload", "http_status": upload_status, "payload": upload_body})
    if upload_status >= 400:
        result["status"] = "failed"
        return result

    effective_doc_id = str(upload_body.get("doc_id") or item.doc_id)
    effective_doc_version = str(upload_body.get("doc_version") or item.doc_version)
    result["effective_doc_id"] = effective_doc_id
    result["effective_doc_version"] = effective_doc_version
    if str(upload_body.get("status") or "").lower() == "duplicate_skipped":
        result["status"] = "duplicate_skipped"
        return result

    for action in ("rechunk", "approve", "index"):
        status, body = _request_json(
            base_url=base_url,
            endpoint=f"/admin/docs/{effective_doc_id}/{effective_doc_version}/{action}",
            method="POST",
            token=token,
            role=role,
            payload=None,
        )
        result["steps"].append({"step": action, "http_status": status, "payload": body})
        if status >= 400:
            result["status"] = "failed"
            return result

    verify_status, verify_payload = _request_json(
        base_url=base_url,
        endpoint=f"/admin/docs/{effective_doc_id}/{effective_doc_version}/verify-index",
        method="POST",
        token=token,
        role=role,
        payload=None,
    )
    result["steps"].append({"step": "verify-index", "http_status": verify_status, "payload": verify_payload})
    result["status"] = "ok" if verify_status < 400 and str(verify_payload.get("status") or "").lower() == "ok" else "failed"
    return result


def _read_admin_audit_snapshot(db_path: Path, since_iso: str) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT created_at, role, action, doc_id, doc_version, payload_json
            FROM admin_audit_events
            WHERE created_at >= ?
            ORDER BY created_at ASC, event_id ASC
            """,
            (since_iso,),
        ).fetchall()
    events: list[dict[str, Any]] = []
    for row in rows:
        payload_json = str(row["payload_json"] or "")
        try:
            payload = json.loads(payload_json) if payload_json else {}
        except json.JSONDecodeError:
            payload = {"raw": payload_json}
        events.append(
            {
                "created_at": str(row["created_at"] or ""),
                "role": str(row["role"] or ""),
                "action": str(row["action"] or ""),
                "doc_id": str(row["doc_id"] or ""),
                "doc_version": str(row["doc_version"] or ""),
                "payload": payload,
            }
        )
    return events


def _read_sql_doc_chunk_snapshot(db_path: Path, doc_keys: set[tuple[str, str]]) -> dict[str, Any]:
    if not db_path.exists():
        return {"db_exists": False, "docs": [], "total_docs": 0, "total_chunks": 0}

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        docs_rows = conn.execute(
            """
            SELECT doc_id, doc_version, source_set, language, cancer_type, uploaded_at
            FROM docs
            ORDER BY uploaded_at DESC
            """
        ).fetchall()
        chunk_rows = conn.execute(
            """
            SELECT doc_id, doc_version, COUNT(*) AS chunk_count
            FROM chunks
            GROUP BY doc_id, doc_version
            """
        ).fetchall()

    chunk_count_by_key: dict[tuple[str, str], int] = {
        (str(row["doc_id"]), str(row["doc_version"])): int(row["chunk_count"])
        for row in chunk_rows
    }
    selected: list[dict[str, Any]] = []
    for row in docs_rows:
        key = (str(row["doc_id"]), str(row["doc_version"]))
        if doc_keys and key not in doc_keys:
            continue
        selected.append(
            {
                "doc_id": key[0],
                "doc_version": key[1],
                "source_set": str(row["source_set"] or ""),
                "language": str(row["language"] or ""),
                "cancer_type": str(row["cancer_type"] or ""),
                "uploaded_at": str(row["uploaded_at"] or ""),
                "chunk_count": int(chunk_count_by_key.get(key, 0)),
            }
        )

    return {
        "db_exists": True,
        "docs": selected,
        "total_docs": len(selected),
        "total_chunks": sum(int(item["chunk_count"]) for item in selected),
    }


def _resolve_defaults() -> dict[str, Path]:
    downloads = Path.home() / "Downloads"
    return {
        "russco_13": downloads / "2025-1-1-13.pdf",
        "russco_12": downloads / "2025-1-1-12.pdf",
        "russco_19": downloads / "2025-1-1-19.pdf",
        "minzdrav_237_6": downloads / "КР237_6.pdf",
        "mkb10": downloads / "2025-mkb10.pdf",
    }


def _resolve_source_urls(entry: dict[str, Any]) -> tuple[str, str]:
    source_page_url = str(entry.get("source_page_url") or "").strip()
    source_pdf_url = str(entry.get("source_pdf_url") or "").strip()
    legacy_source_url = str(entry.get("source_url") or "").strip()
    if legacy_source_url and not source_page_url and not source_pdf_url:
        if ".pdf" in legacy_source_url.lower():
            source_pdf_url = legacy_source_url
        else:
            source_page_url = legacy_source_url
    return source_page_url, source_pdf_url


def _build_manifest_docs(*, manifest_payload: Any, base_dir: Path | None) -> list[UploadDoc]:
    if isinstance(manifest_payload, dict):
        defaults = manifest_payload.get("defaults") if isinstance(manifest_payload.get("defaults"), dict) else {}
        docs_raw = manifest_payload.get("documents")
    else:
        defaults = {}
        docs_raw = manifest_payload

    if not isinstance(docs_raw, list):
        raise ValueError("Manifest must contain documents[]")

    docs: list[UploadDoc] = []
    for index, raw in enumerate(docs_raw, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"Manifest document #{index} must be object")
        merged = dict(defaults)
        merged.update(raw)

        source_set = normalize_source_set_id(str(merged.get("source_set") or ""))
        doc_id = str(merged.get("doc_id") or "").strip()
        doc_version = str(merged.get("doc_version") or "").strip()
        cancer_type = str(merged.get("cancer_type") or "").strip()
        if not source_set or not doc_id or not doc_version or not cancer_type:
            raise ValueError(
                f"Manifest document #{index} missing required fields: source_set/doc_id/doc_version/cancer_type"
            )

        raw_path = str(merged.get("local_path") or merged.get("path") or merged.get("filename") or "").strip()
        if not raw_path:
            raise ValueError(f"Manifest document #{index} missing local_path/path/filename")
        local_path = Path(raw_path)
        if not local_path.is_absolute() and base_dir is not None:
            local_path = (base_dir / local_path).resolve()

        source_page_url, source_pdf_url = _resolve_source_urls(merged)

        icd10_prefixes_raw = merged.get("icd10_prefixes")
        icd10_prefixes = []
        if isinstance(icd10_prefixes_raw, list):
            icd10_prefixes = [str(item).strip() for item in icd10_prefixes_raw if str(item).strip()]

        docs.append(
            UploadDoc(
                local_path=local_path,
                doc_id=doc_id,
                doc_version=doc_version,
                source_set=source_set,
                source_page_url=source_page_url,
                source_pdf_url=source_pdf_url,
                doc_kind=str(merged.get("doc_kind") or "guideline").strip().lower() or "guideline",
                cancer_type=cancer_type,
                icd10_prefixes=icd10_prefixes,
                language=str(merged.get("language") or "ru").strip().lower() or "ru",
            )
        )
    return docs


def _legacy_docs_from_args(args: argparse.Namespace) -> list[UploadDoc]:
    return [
        UploadDoc(
            local_path=Path(args.russco_13),
            doc_id="russco_2025_1_1_13",
            doc_version="2025",
            source_set="russco",
            source_page_url="https://www.rosoncoweb.ru/standarts/RUSSCO/2025/2025-1-1-13.pdf",
            source_pdf_url="https://www.rosoncoweb.ru/standarts/RUSSCO/2025/2025-1-1-13.pdf",
            doc_kind="guideline",
            cancer_type="gastric_cancer",
            icd10_prefixes=["C16"],
        ),
        UploadDoc(
            local_path=Path(args.russco_12),
            doc_id="russco_2025_1_1_12",
            doc_version="2025",
            source_set="russco",
            source_page_url="https://www.rosoncoweb.ru/standarts/RUSSCO/2025/2025-1-1-12.pdf",
            source_pdf_url="https://www.rosoncoweb.ru/standarts/RUSSCO/2025/2025-1-1-12.pdf",
            doc_kind="guideline",
            cancer_type="esophagogastric_junction_cancer",
            icd10_prefixes=["C15", "C16"],
        ),
        UploadDoc(
            local_path=Path(args.russco_19),
            doc_id="russco_2025_1_1_19",
            doc_version="2025",
            source_set="russco",
            source_page_url="https://www.rosoncoweb.ru/standarts/RUSSCO/2025/2025-1-1-19.pdf",
            source_pdf_url="https://www.rosoncoweb.ru/standarts/RUSSCO/2025/2025-1-1-19.pdf",
            doc_kind="guideline",
            cancer_type="gist",
            icd10_prefixes=["C49"],
        ),
        UploadDoc(
            local_path=Path(args.minzdrav_237_6),
            doc_id="minzdrav_237_6",
            doc_version="237.6",
            source_set="minzdrav",
            source_page_url="https://cr.minzdrav.gov.ru/preview-cr/237_6",
            source_pdf_url="",
            doc_kind="guideline",
            cancer_type="gastric_cancer",
            icd10_prefixes=["C16"],
        ),
        UploadDoc(
            local_path=Path(args.mkb10),
            doc_id="russco_2025_mkb10",
            doc_version="2025",
            source_set="russco",
            source_page_url="https://www.rosoncoweb.ru/standarts/RUSSCO/2025/2025-mkb10.pdf",
            source_pdf_url="https://www.rosoncoweb.ru/standarts/RUSSCO/2025/2025-mkb10.pdf",
            doc_kind="reference",
            cancer_type="reference_icd10",
            icd10_prefixes=[],
        ),
    ]


def _load_docs_from_inputs(args: argparse.Namespace) -> tuple[list[UploadDoc], str | None]:
    if not args.manifest:
        return _legacy_docs_from_args(args), None

    manifest_path = Path(args.manifest).expanduser().resolve()
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    extracted_tmp_dir: str | None = None
    base_dir: Path | None = manifest_path.parent
    if args.input_zip:
        zip_path = Path(args.input_zip).expanduser().resolve()
        extracted_tmp_dir = tempfile.mkdtemp(prefix="oncoai_guidelines_zip_")
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(extracted_tmp_dir)
        base_dir = Path(extracted_tmp_dir)
    elif args.input_dir:
        base_dir = Path(args.input_dir).expanduser().resolve()

    docs = _build_manifest_docs(manifest_payload=manifest_payload, base_dir=base_dir)
    return docs, extracted_tmp_dir


def _build_ingest_audit(report: dict[str, Any]) -> dict[str, Any]:
    docs = report.get("documents") if isinstance(report.get("documents"), list) else []
    ok = 0
    duplicates = 0
    failed = 0
    verify_ok = 0
    for item in docs:
        status = str(item.get("status") or "").strip().lower()
        if status == "ok":
            ok += 1
        elif status == "duplicate_skipped":
            duplicates += 1
        else:
            failed += 1
        steps = item.get("steps") if isinstance(item.get("steps"), list) else []
        if any(
            isinstance(step, dict)
            and str(step.get("step") or "") == "verify-index"
            and str((step.get("payload") if isinstance(step.get("payload"), dict) else {}).get("status") or "").lower() == "ok"
            for step in steps
        ):
            verify_ok += 1
    return {
        "documents_total": len(docs),
        "documents_ok": ok,
        "documents_duplicate": duplicates,
        "documents_failed": failed,
        "verify_index_ok": verify_ok,
    }


def main() -> int:
    defaults = _resolve_defaults()
    parser = argparse.ArgumentParser(description="Batch ingest official guidelines into OncoAI admin workflow")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--token", default=os.getenv("ONCOAI_DEMO_TOKEN", "demo-token"))
    parser.add_argument("--role", default="admin")
    parser.add_argument("--db-path", default="data/oncoai.sqlite3")
    parser.add_argument("--manifest", default="", help="Path to manifest JSON (recommended)")
    parser.add_argument("--input-dir", default="", help="Base directory for manifest relative paths")
    parser.add_argument("--input-zip", default="", help="Zip archive with files referenced by manifest")
    parser.add_argument("--cleanup-apply", action="store_true", help="Apply cleanup-invalid before ingest (disabled by default)")
    parser.add_argument("--cleanup-reason-allowlist", default="", help="Comma-separated validity reasons for cleanup apply")

    # Legacy defaults, kept for backward compatibility when --manifest is not provided.
    parser.add_argument("--russco-13", default=str(defaults["russco_13"]))
    parser.add_argument("--russco-12", default=str(defaults["russco_12"]))
    parser.add_argument("--russco-19", default=str(defaults["russco_19"]))
    parser.add_argument("--minzdrav-237-6", default=str(defaults["minzdrav_237_6"]))
    parser.add_argument("--mkb10", default=str(defaults["mkb10"]))

    parser.add_argument("--output", default=f"/tmp/oncoai_official_ingest_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    args = parser.parse_args()

    docs: list[UploadDoc] = []
    extracted_tmp_dir: str | None = None
    try:
        docs, extracted_tmp_dir = _load_docs_from_inputs(args)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": "manifest_load_failed", "details": str(exc)}, ensure_ascii=False, indent=2))
        return 2

    if not docs:
        print(json.dumps({"error": "no_documents"}, ensure_ascii=False, indent=2))
        return 2

    missing_files = [str(item.local_path) for item in docs if not item.local_path.exists()]
    if missing_files:
        print(json.dumps({"error": "missing_input_files", "files": missing_files}, ensure_ascii=False, indent=2))
        if extracted_tmp_dir:
            shutil.rmtree(extracted_tmp_dir, ignore_errors=True)
        return 2

    started_at = _utc_now()
    report: dict[str, Any] = {
        "started_at": started_at,
        "base_url": args.base_url,
        "db_path": str(Path(args.db_path).resolve()),
        "input": {
            "manifest": str(args.manifest or ""),
            "input_dir": str(args.input_dir or ""),
            "input_zip": str(args.input_zip or ""),
            "documents_total": len(docs),
        },
        "cleanup": {},
        "documents": [],
        "status": "running",
    }

    reason_allowlist = [item.strip() for item in str(args.cleanup_reason_allowlist or "").split(",") if item.strip()]

    dry_status, dry_payload = _request_json(
        base_url=args.base_url,
        endpoint="/admin/docs/cleanup-invalid",
        method="POST",
        token=args.token,
        role=args.role,
        payload={"dry_run": True, "apply": False},
    )
    report["cleanup"]["dry_run"] = {"http_status": dry_status, "payload": dry_payload}

    apply_status = 0
    apply_payload: dict[str, Any] = {"skipped": True, "reason": "cleanup_apply_disabled"}
    if args.cleanup_apply:
        payload: dict[str, Any] = {"dry_run": False, "apply": True}
        if reason_allowlist:
            payload["reason_allowlist"] = reason_allowlist
        apply_status, apply_payload = _request_json(
            base_url=args.base_url,
            endpoint="/admin/docs/cleanup-invalid",
            method="POST",
            token=args.token,
            role=args.role,
            payload=payload,
        )
    report["cleanup"]["apply"] = {"http_status": apply_status, "payload": apply_payload}

    for item in docs:
        report["documents"].append(
            _run_doc_workflow(
                base_url=args.base_url,
                token=args.token,
                role=args.role,
                item=item,
            )
        )

    docs_status, docs_payload = _request_json(
        base_url=args.base_url,
        endpoint="/admin/docs?valid_only=false&kind=guideline",
        method="GET",
        token=args.token,
        role=args.role,
    )
    refs_status, refs_payload = _request_json(
        base_url=args.base_url,
        endpoint="/admin/docs?valid_only=false&kind=reference",
        method="GET",
        token=args.token,
        role=args.role,
    )
    report["catalog_snapshot"] = {
        "guidelines": {"http_status": docs_status, "payload": docs_payload},
        "references": {"http_status": refs_status, "payload": refs_payload},
    }

    doc_keys = {
        (str(item.get("effective_doc_id") or item.get("doc_id") or ""), str(item.get("effective_doc_version") or item.get("doc_version") or ""))
        for item in report["documents"]
        if str(item.get("effective_doc_id") or item.get("doc_id") or "").strip()
        and str(item.get("effective_doc_version") or item.get("doc_version") or "").strip()
    }
    report["sql_snapshot"] = _read_sql_doc_chunk_snapshot(Path(args.db_path), doc_keys)
    report["ingest_audit"] = _build_ingest_audit(report)
    report["admin_audit_events"] = _read_admin_audit_snapshot(Path(args.db_path), started_at)
    report["finished_at"] = _utc_now()

    failures = [
        item
        for item in report["documents"]
        if str(item.get("status") or "").lower() not in {"ok", "duplicate_skipped"}
    ]

    cleanup_ok = dry_status < 400
    if args.cleanup_apply:
        cleanup_ok = cleanup_ok and apply_status < 400

    report["status"] = "ok" if not failures and cleanup_ok else "partial"

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(output_path)}, ensure_ascii=False))

    if extracted_tmp_dir:
        shutil.rmtree(extracted_tmp_dir, ignore_errors=True)
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
