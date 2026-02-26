from __future__ import annotations

from typing import Any

from backend.app.service import OncoService


def health_handler(service: OncoService) -> dict[str, Any]:
    return service.health()


try:
    from fastapi import APIRouter

    router = APIRouter()

    @router.get("/health")
    def health_fastapi():
        from backend.app.main import get_service

        return health_handler(get_service())

except ModuleNotFoundError:  # pragma: no cover
    router = None
