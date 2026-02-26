from __future__ import annotations

from backend.app.api.routes_admin import (
    doc_approve_handler,
    doc_index_handler,
    doc_rechunk_handler,
    doc_reject_handler,
    sync_minzdrav_handler,
    sync_russco_handler,
)


class _FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def admin_doc_rechunk(self, *, role: str, doc_id: str, doc_version: str) -> dict[str, object]:
        self.calls.append(("admin_doc_rechunk", (role, doc_id, doc_version), {}))
        return {"status": "PENDING_APPROVAL"}

    def admin_doc_approve(self, *, role: str, doc_id: str, doc_version: str) -> dict[str, object]:
        self.calls.append(("admin_doc_approve", (role, doc_id, doc_version), {}))
        return {"status": "APPROVED"}

    def admin_doc_reject(
        self,
        *,
        role: str,
        doc_id: str,
        doc_version: str,
        reason: str | None = None,
    ) -> dict[str, object]:
        self.calls.append(("admin_doc_reject", (role, doc_id, doc_version), {"reason": reason or ""}))
        return {"status": "REJECTED"}

    def admin_doc_index(self, *, role: str, doc_id: str, doc_version: str) -> dict[str, object]:
        self.calls.append(("admin_doc_index", (role, doc_id, doc_version), {}))
        return {"status": "INDEXED"}

    def admin_sync_russco(self, *, role: str) -> dict[str, object]:
        self.calls.append(("admin_sync_russco", (role,), {}))
        return {"source": "russco", "status": "ok"}

    def admin_sync_minzdrav(self, *, role: str) -> dict[str, object]:
        self.calls.append(("admin_sync_minzdrav", (role,), {}))
        return {"source": "minzdrav", "status": "ok"}


def test_admin_guideline_route_handlers_delegate_to_service() -> None:
    service = _FakeService()

    assert doc_rechunk_handler(service, role="admin", doc_id="d1", doc_version="v1")["status"] == "PENDING_APPROVAL"
    assert doc_approve_handler(service, role="admin", doc_id="d1", doc_version="v1")["status"] == "APPROVED"
    assert doc_reject_handler(service, role="admin", doc_id="d1", doc_version="v1", reason="bad-scan")["status"] == "REJECTED"
    assert doc_index_handler(service, role="admin", doc_id="d1", doc_version="v1")["status"] == "INDEXED"
    assert sync_russco_handler(service, role="admin")["source"] == "russco"
    assert sync_minzdrav_handler(service, role="admin")["source"] == "minzdrav"

    assert ("admin_doc_rechunk", ("admin", "d1", "v1"), {}) in service.calls
    assert ("admin_doc_approve", ("admin", "d1", "v1"), {}) in service.calls
    assert ("admin_doc_reject", ("admin", "d1", "v1"), {"reason": "bad-scan"}) in service.calls
    assert ("admin_doc_index", ("admin", "d1", "v1"), {}) in service.calls
    assert ("admin_sync_russco", ("admin",), {}) in service.calls
    assert ("admin_sync_minzdrav", ("admin",), {}) in service.calls
