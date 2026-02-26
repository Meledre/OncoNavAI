from __future__ import annotations

from backend.app.api.routes_admin import routing_rebuild_handler, routing_routes_handler


class _FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []

    def admin_routing_routes(self, role: str, language: str | None = None) -> dict[str, object]:
        self.calls.append(("admin_routing_routes", role, language))
        return {"routes": [{"route_id": "route-1"}], "count": 1}

    def admin_routing_rebuild(self, role: str) -> dict[str, object]:
        self.calls.append(("admin_routing_rebuild", role, None))
        return {"status": "ok", "routes_total": 3}


def test_admin_routing_route_handlers_delegate_to_service() -> None:
    service = _FakeService()

    routes_payload = routing_routes_handler(service, role="admin", language="ru")
    rebuild_payload = routing_rebuild_handler(service, role="admin")

    assert routes_payload["count"] == 1
    assert rebuild_payload["status"] == "ok"
    assert ("admin_routing_routes", "admin", "ru") in service.calls
    assert ("admin_routing_rebuild", "admin", None) in service.calls
