from __future__ import annotations

from backend.app.api.routes_case_import import (
    case_get_handler,
    case_import_handler,
    case_import_file_base64_handler,
    case_import_run_get_handler,
    case_import_runs_list_handler,
)


class _FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []

    def case_import(self, role: str, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(("case_import", role, payload))
        return {"ok": True, "import_run_id": "run-1", "case_id": "case-1"}

    def case_import_file_base64(self, role: str, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(("case_import_file_base64", role, payload))
        return {"ok": True, "import_run_id": "run-file-1", "case_id": "case-file-1"}

    def get_case(self, role: str, case_id: str) -> dict[str, object]:
        self.calls.append(("get_case", role, case_id))
        return {"case_id": case_id, "schema_version": "1.0"}

    def get_case_import_run(self, role: str, import_run_id: str) -> dict[str, object]:
        self.calls.append(("get_case_import_run", role, import_run_id))
        return {"import_run_id": import_run_id, "schema_version": "1.0"}

    def list_case_import_runs(self, role: str, limit: int) -> list[dict[str, object]]:
        self.calls.append(("list_case_import_runs", role, limit))
        return [{"import_run_id": "run-1"}, {"import_run_id": "run-2"}][:limit]


def test_case_import_routes_delegate_to_service() -> None:
    service = _FakeService()

    import_payload = case_import_handler(service, role="clinician", payload={"import_profile": "FREE_TEXT"})
    import_file_payload = case_import_file_base64_handler(
        service,
        role="clinician",
        payload={"filename": "case.pdf", "content_base64": "cGRm"},
    )
    case_payload = case_get_handler(service, role="clinician", case_id="case-123")
    run_payload = case_import_run_get_handler(service, role="admin", import_run_id="run-123")
    runs_payload = case_import_runs_list_handler(service, role="admin", limit=1)

    assert import_payload["ok"] is True
    assert import_file_payload["ok"] is True
    assert case_payload["case_id"] == "case-123"
    assert run_payload["import_run_id"] == "run-123"
    assert runs_payload["count"] == 1
    assert runs_payload["limit"] == 1
    assert runs_payload["runs"][0]["import_run_id"] == "run-1"

    assert ("case_import", "clinician", {"import_profile": "FREE_TEXT"}) in service.calls
    assert ("case_import_file_base64", "clinician", {"filename": "case.pdf", "content_base64": "cGRm"}) in service.calls
    assert ("get_case", "clinician", "case-123") in service.calls
    assert ("get_case_import_run", "admin", "run-123") in service.calls
    assert ("list_case_import_runs", "admin", 1) in service.calls
