from __future__ import annotations

from backend.app.service import OncoService


def report_json_handler(service: OncoService, role: str, report_id: str) -> dict:
    return service.report_json(role=role, report_id=report_id)


def report_html_handler(service: OncoService, role: str, report_id: str) -> str:
    return service.report_html(role=role, report_id=report_id)


def report_pdf_handler(service: OncoService, role: str, report_id: str) -> bytes:
    return service.report_pdf(role=role, report_id=report_id)


def report_docx_handler(service: OncoService, role: str, report_id: str) -> bytes:
    return service.report_docx(role=role, report_id=report_id)


try:
    from fastapi import APIRouter, Header
    from fastapi.responses import HTMLResponse, Response

    from backend.app.security.demo_token import ensure_demo_token

    router = APIRouter(prefix="/report")

    @router.get("/{report_id}.json")
    def report_json_fastapi(
        report_id: str,
        x_role: str = Header(default="clinician"),
        x_demo_token: str = Header(default=""),
    ):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        return report_json_handler(service, role=x_role, report_id=report_id)

    @router.get("/{report_id}.html", response_class=HTMLResponse)
    def report_html_fastapi(
        report_id: str,
        x_role: str = Header(default="clinician"),
        x_demo_token: str = Header(default=""),
    ):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        return report_html_handler(service, role=x_role, report_id=report_id)

    @router.get("/{report_id}.pdf")
    def report_pdf_fastapi(
        report_id: str,
        x_role: str = Header(default="clinician"),
        x_demo_token: str = Header(default=""),
    ):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        payload = report_pdf_handler(service, role=x_role, report_id=report_id)
        return Response(
            content=payload,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{report_id}.pdf"'},
        )

    @router.get("/{report_id}.docx")
    def report_docx_fastapi(
        report_id: str,
        x_role: str = Header(default="clinician"),
        x_demo_token: str = Header(default=""),
    ):
        from backend.app.main import get_service

        service = get_service()
        ensure_demo_token(x_demo_token, service.settings.demo_token)
        payload = report_docx_handler(service, role=x_role, report_id=report_id)
        return Response(
            content=payload,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{report_id}.docx"'},
        )

except ModuleNotFoundError:  # pragma: no cover
    router = None
