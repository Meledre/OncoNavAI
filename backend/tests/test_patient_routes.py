from __future__ import annotations

from backend.app.api.routes_patient import patient_analyze_file_base64_handler


class _FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []

    def patient_analyze_file_base64(self, role: str, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(("patient_analyze_file_base64", role, payload))
        return {
            "schema_version": "0.2",
            "request_id": "req-1",
            "case_id": "case-1",
            "import_run_id": "run-1",
            "patient_explain": {"schema_version": "1.0", "summary_plain": "ok"},
            "run_meta": {"schema_version": "0.2"},
        }


def test_patient_analyze_file_base64_route_delegates_to_service() -> None:
    service = _FakeService()
    payload = {
        "filename": "patient_case.pdf",
        "content_base64": "cGRm",
        "query_type": "NEXT_STEPS",
        "sources": {"mode": "AUTO", "source_ids": ["minzdrav", "russco"]},
        "language": "ru",
    }

    response = patient_analyze_file_base64_handler(service, role="patient", payload=payload)
    assert response["schema_version"] == "0.2"
    assert response["case_id"] == "case-1"
    assert ("patient_analyze_file_base64", "patient", payload) in service.calls
