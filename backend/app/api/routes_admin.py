from __future__ import annotations

import base64
from typing import Any

from backend.app.exceptions import ValidationError
from backend.app.service import OncoService


def upload_handler(
    service: OncoService,
    role: str,
    filename: str,
    content: bytes,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return service.admin_upload(role=role, filename=filename, content=content, metadata=metadata)


def docs_handler(
    service: OncoService,
    role: str,
    valid_only: bool = True,
    kind: str = "guideline",
) -> dict[str, Any]:
    return service.admin_docs(role=role, valid_only=valid_only, kind=kind)


def drug_dictionary_load_handler(service: OncoService, role: str, payload: dict[str, Any]) -> dict[str, Any]:
    return service.admin_drug_dictionary_load(role=role, payload=payload)


def drug_safety_cache_warmup_handler(
    service: OncoService,
    role: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return service.admin_drug_safety_cache_warmup(role=role, payload=payload)


def drug_safety_cache_handler(service: OncoService, role: str, limit: int = 200) -> dict[str, Any]:
    return service.admin_drug_safety_cache(role=role, limit=limit)


def reindex_handler(service: OncoService, role: str) -> dict[str, Any]:
    return service.admin_reindex(role=role)


def reindex_status_handler(service: OncoService, role: str, job_id: str) -> dict[str, Any]:
    return service.admin_reindex_status(role=role, job_id=job_id)


def doc_pdf_handler(service: OncoService, role: str, doc_id: str, doc_version: str) -> tuple[bytes, str]:
    return service.admin_doc_pdf(role=role, doc_id=doc_id, doc_version=doc_version)


def doc_rechunk_handler(service: OncoService, role: str, doc_id: str, doc_version: str) -> dict[str, Any]:
    return service.admin_doc_rechunk(role=role, doc_id=doc_id, doc_version=doc_version)


def doc_approve_handler(service: OncoService, role: str, doc_id: str, doc_version: str) -> dict[str, Any]:
    return service.admin_doc_approve(role=role, doc_id=doc_id, doc_version=doc_version)


def doc_reject_handler(
    service: OncoService,
    role: str,
    doc_id: str,
    doc_version: str,
    reason: str | None = None,
) -> dict[str, Any]:
    return service.admin_doc_reject(role=role, doc_id=doc_id, doc_version=doc_version, reason=reason)


def doc_index_handler(service: OncoService, role: str, doc_id: str, doc_version: str) -> dict[str, Any]:
    return service.admin_doc_index(role=role, doc_id=doc_id, doc_version=doc_version)


def doc_verify_index_handler(service: OncoService, role: str, doc_id: str, doc_version: str) -> dict[str, Any]:
    return service.admin_doc_verify_index(role=role, doc_id=doc_id, doc_version=doc_version)


def sync_russco_handler(service: OncoService, role: str) -> dict[str, Any]:
    return service.admin_sync_russco(role=role)


def sync_minzdrav_handler(service: OncoService, role: str) -> dict[str, Any]:
    return service.admin_sync_minzdrav(role=role)


def cleanup_invalid_docs_handler(
    service: OncoService,
    role: str,
    *,
    dry_run: bool,
    apply: bool,
    reason_allowlist: list[str] | None = None,
) -> dict[str, Any]:
    return service.admin_docs_cleanup_invalid(
        role=role,
        dry_run=dry_run,
        apply=apply,
        reason_allowlist=reason_allowlist,
    )


def validate_contract_projections_handler(
    service: OncoService,
    role: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return service.admin_validate_contract_projections(role=role, payload=payload)


def routing_routes_handler(service: OncoService, role: str, language: str | None = None) -> dict[str, Any]:
    return service.admin_routing_routes(role=role, language=language)


def routing_rebuild_handler(service: OncoService, role: str) -> dict[str, Any]:
    return service.admin_routing_rebuild(role=role)


try:
    from fastapi import APIRouter, Header, Query, Request
    from fastapi.concurrency import run_in_threadpool
    from fastapi.responses import Response

    from backend.app.security.demo_token import ensure_demo_token

    router = APIRouter(prefix="/admin")

    @router.post("/upload")
    async def upload_fastapi(
        request: Request,
        x_role: str = Header(default="clinician"),
        x_demo_token: str = Header(default=""),
    ):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        payload = await request.json()

        required = [
            "filename",
            "content_base64",
            "doc_id",
            "doc_version",
            "source_set",
            "cancer_type",
            "language",
        ]
        missing = [field for field in required if not payload.get(field)]
        if missing:
            raise ValidationError(f"Missing upload fields: {', '.join(missing)}")

        try:
            content = base64.b64decode(payload["content_base64"])
        except Exception as exc:  # noqa: BLE001
            raise ValidationError("Invalid content_base64 payload") from exc

        filename = str(payload.get("filename", "upload.pdf"))
        icd10_prefixes = payload.get("icd10_prefixes")
        nosology_keywords = payload.get("nosology_keywords")
        if icd10_prefixes is not None and not isinstance(icd10_prefixes, list):
            raise ValidationError("icd10_prefixes must be an array of strings")
        if nosology_keywords is not None and not isinstance(nosology_keywords, list):
            raise ValidationError("nosology_keywords must be an array of strings")
        metadata = {
            "doc_id": payload["doc_id"],
            "doc_version": payload["doc_version"],
            "source_set": payload["source_set"],
            "cancer_type": payload["cancer_type"],
            "language": payload["language"],
            "source_url": str(payload.get("source_url") or "").strip(),
            "source_page_url": str(payload.get("source_page_url") or "").strip(),
            "source_pdf_url": str(payload.get("source_pdf_url") or "").strip(),
            "doc_kind": str(payload.get("doc_kind") or "guideline").strip().lower() or "guideline",
            "disease_id": str(payload.get("disease_id") or "").strip(),
            "icd10_prefixes": [str(item).strip() for item in (icd10_prefixes or []) if str(item).strip()],
            "nosology_keywords": [str(item).strip() for item in (nosology_keywords or []) if str(item).strip()],
        }
        return await run_in_threadpool(
            upload_handler,
            service,
            role=x_role,
            filename=filename,
            content=content,
            metadata=metadata,
        )

    @router.get("/docs")
    def docs_fastapi(
        valid_only: bool = Query(default=True),
        kind: str = Query(default="guideline"),
        x_role: str = Header(default="clinician"),
        x_demo_token: str = Header(default=""),
    ):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        normalized_kind = str(kind or "guideline").strip().lower()
        if normalized_kind not in {"guideline", "reference", "all"}:
            raise ValidationError("kind must be one of guideline|reference|all")
        return docs_handler(service, role=x_role, valid_only=valid_only, kind=normalized_kind)

    @router.post("/references/drug-dictionary/load")
    async def drug_dictionary_load_fastapi(
        request: Request,
        x_role: str = Header(default="clinician"),
        x_demo_token: str = Header(default=""),
    ):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        payload: dict[str, Any] = {}
        try:
            raw_payload = await request.json()
            if isinstance(raw_payload, dict):
                payload = raw_payload
        except Exception:  # noqa: BLE001
            payload = {}
        return await run_in_threadpool(
            drug_dictionary_load_handler,
            service,
            role=x_role,
            payload=payload,
        )

    @router.get("/drug-safety/cache")
    def drug_safety_cache_fastapi(
        limit: int = Query(default=200),
        x_role: str = Header(default="clinician"),
        x_demo_token: str = Header(default=""),
    ):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        safe_limit = max(1, min(int(limit), 5000))
        return drug_safety_cache_handler(service, role=x_role, limit=safe_limit)

    @router.post("/drug-safety/cache/warmup")
    async def drug_safety_cache_warmup_fastapi(
        request: Request,
        x_role: str = Header(default="clinician"),
        x_demo_token: str = Header(default=""),
    ):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        payload: dict[str, Any] = {}
        try:
            raw_payload = await request.json()
            if isinstance(raw_payload, dict):
                payload = raw_payload
        except Exception:  # noqa: BLE001
            payload = {}
        return await run_in_threadpool(
            drug_safety_cache_warmup_handler,
            service,
            role=x_role,
            payload=payload,
        )

    @router.post("/reindex")
    def reindex_fastapi(x_role: str = Header(default="clinician"), x_demo_token: str = Header(default="")):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        return reindex_handler(service, role=x_role)

    @router.get("/reindex/{job_id}")
    def reindex_status_fastapi(job_id: str, x_role: str = Header(default="clinician"), x_demo_token: str = Header(default="")):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        return reindex_status_handler(service, role=x_role, job_id=job_id)

    @router.get("/docs/{doc_id}/{doc_version}/pdf")
    def doc_pdf_fastapi(
        doc_id: str,
        doc_version: str,
        x_role: str = Header(default="clinician"),
        x_demo_token: str = Header(default=""),
    ):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        payload, filename = doc_pdf_handler(service, role=x_role, doc_id=doc_id, doc_version=doc_version)
        return Response(
            content=payload,
            media_type="application/pdf",
            headers={"content-disposition": f'inline; filename="{filename}"'},
        )

    @router.post("/docs/{doc_id}/{doc_version}/rechunk")
    def doc_rechunk_fastapi(
        doc_id: str,
        doc_version: str,
        x_role: str = Header(default="clinician"),
        x_demo_token: str = Header(default=""),
    ):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        return doc_rechunk_handler(service, role=x_role, doc_id=doc_id, doc_version=doc_version)

    @router.post("/docs/{doc_id}/{doc_version}/approve")
    def doc_approve_fastapi(
        doc_id: str,
        doc_version: str,
        x_role: str = Header(default="clinician"),
        x_demo_token: str = Header(default=""),
    ):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        return doc_approve_handler(service, role=x_role, doc_id=doc_id, doc_version=doc_version)

    @router.post("/docs/{doc_id}/{doc_version}/reject")
    async def doc_reject_fastapi(
        request: Request,
        doc_id: str,
        doc_version: str,
        x_role: str = Header(default="clinician"),
        x_demo_token: str = Header(default=""),
    ):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        payload: dict[str, Any] = {}
        try:
            maybe_payload = await request.json()
            if isinstance(maybe_payload, dict):
                payload = maybe_payload
        except Exception:  # noqa: BLE001
            payload = {}
        reason_raw = payload.get("reason") if isinstance(payload, dict) else None
        reason = str(reason_raw).strip() if reason_raw is not None else None
        return await run_in_threadpool(
            doc_reject_handler,
            service,
            role=x_role,
            doc_id=doc_id,
            doc_version=doc_version,
            reason=reason or None,
        )

    @router.post("/docs/{doc_id}/{doc_version}/index")
    def doc_index_fastapi(
        doc_id: str,
        doc_version: str,
        x_role: str = Header(default="clinician"),
        x_demo_token: str = Header(default=""),
    ):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        return doc_index_handler(service, role=x_role, doc_id=doc_id, doc_version=doc_version)

    @router.post("/docs/{doc_id}/{doc_version}/verify-index")
    def doc_verify_index_fastapi(
        doc_id: str,
        doc_version: str,
        x_role: str = Header(default="clinician"),
        x_demo_token: str = Header(default=""),
    ):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        return doc_verify_index_handler(service, role=x_role, doc_id=doc_id, doc_version=doc_version)

    @router.post("/sync/russco")
    def sync_russco_fastapi(x_role: str = Header(default="clinician"), x_demo_token: str = Header(default="")):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        return sync_russco_handler(service, role=x_role)

    @router.post("/sync/minzdrav")
    def sync_minzdrav_fastapi(x_role: str = Header(default="clinician"), x_demo_token: str = Header(default="")):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        return sync_minzdrav_handler(service, role=x_role)

    @router.post("/docs/cleanup-invalid")
    async def cleanup_invalid_docs_fastapi(
        request: Request,
        x_role: str = Header(default="clinician"),
        x_demo_token: str = Header(default=""),
    ):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        payload: dict[str, Any] = {}
        try:
            raw_payload = await request.json()
            if isinstance(raw_payload, dict):
                payload = raw_payload
        except Exception:  # noqa: BLE001
            payload = {}

        dry_run = bool(payload.get("dry_run", True))
        apply = bool(payload.get("apply", False))
        reason_allowlist_raw = payload.get("reason_allowlist")
        reason_allowlist: list[str] | None = None
        if reason_allowlist_raw is not None:
            if not isinstance(reason_allowlist_raw, list):
                raise ValidationError("reason_allowlist must be an array of strings")
            reason_allowlist = [str(item).strip() for item in reason_allowlist_raw if str(item).strip()]
        return await run_in_threadpool(
            cleanup_invalid_docs_handler,
            service,
            role=x_role,
            dry_run=dry_run,
            apply=apply,
            reason_allowlist=reason_allowlist,
        )

    @router.post("/contracts/validate-projections")
    async def validate_contract_projections_fastapi(
        request: Request,
        x_role: str = Header(default="clinician"),
        x_demo_token: str = Header(default=""),
    ):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        payload: dict[str, Any] = {}
        try:
            raw_payload = await request.json()
            if isinstance(raw_payload, dict):
                payload = raw_payload
        except Exception:  # noqa: BLE001
            payload = {}
        return await run_in_threadpool(
            validate_contract_projections_handler,
            service,
            role=x_role,
            payload=payload,
        )

    @router.get("/routing/routes")
    def routing_routes_fastapi(
        language: str | None = Query(default=None),
        x_role: str = Header(default="clinician"),
        x_demo_token: str = Header(default=""),
    ):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        normalized_language = str(language or "").strip().lower()
        if normalized_language and normalized_language not in {"ru", "en"}:
            raise ValidationError("language must be ru or en")
        return routing_routes_handler(service, role=x_role, language=normalized_language or None)

    @router.post("/routing/rebuild")
    def routing_rebuild_fastapi(x_role: str = Header(default="clinician"), x_demo_token: str = Header(default="")):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        return routing_rebuild_handler(service, role=x_role)

except ModuleNotFoundError:  # pragma: no cover
    router = None
