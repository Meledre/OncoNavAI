from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.app.drugs.models import DrugSafetyProfile, DrugSafetyStatus, DrugSafetyWarning
from backend.app.drugs.openfda_client import fetch_openfda_drug_label
from backend.app.drugs.translator_ru import translate_safety_lines_to_ru
from backend.app.storage import SQLiteStore


def _parse_utc(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass
class DrugSafetyFetchResult:
    status: DrugSafetyStatus
    profiles: list[DrugSafetyProfile]
    warnings: list[DrugSafetyWarning]


class DrugSafetyProvider:
    def __init__(
        self,
        *,
        store: SQLiteStore,
        cache_ttl_hours: int = 24 * 14,
        request_timeout_sec: int = 12,
        openfda_base_url: str = "https://api.fda.gov",
    ) -> None:
        self.store = store
        self.cache_ttl_hours = max(1, int(cache_ttl_hours))
        self.request_timeout_sec = max(3, int(request_timeout_sec))
        self.openfda_base_url = str(openfda_base_url or "https://api.fda.gov").strip()

    def _cache_valid(self, payload: dict[str, Any]) -> bool:
        expires_at = _parse_utc(str(payload.get("expires_at") or ""))
        if expires_at is None:
            return False
        now = datetime.now(timezone.utc)
        return expires_at >= now

    def _from_cache(self, inn: str) -> DrugSafetyProfile | None:
        cache = self.store.get_drug_safety_cache(inn)
        if not isinstance(cache, dict):
            return None
        if not self._cache_valid(cache):
            return None
        return DrugSafetyProfile(
            inn=str(cache.get("inn") or inn).strip().lower(),
            source=str(cache.get("source") or "cache"),
            contraindications_ru=[str(item) for item in (cache.get("contraindications") or []) if str(item).strip()],
            warnings_ru=[str(item) for item in (cache.get("warnings") or []) if str(item).strip()],
            interactions_ru=[str(item) for item in (cache.get("interactions") or []) if str(item).strip()],
            adverse_reactions_ru=[str(item) for item in (cache.get("adverse_reactions") or []) if str(item).strip()],
            updated_at=str(cache.get("source_updated_at") or cache.get("fetched_at") or datetime.now(timezone.utc).isoformat()),
        )

    def _fetch_and_cache(self, inn: str) -> tuple[DrugSafetyProfile | None, DrugSafetyWarning | None]:
        result = fetch_openfda_drug_label(
            inn=inn,
            timeout_sec=self.request_timeout_sec,
            base_url=self.openfda_base_url,
        )
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=self.cache_ttl_hours)
        contraindications_ru = translate_safety_lines_to_ru(result.contraindications)
        warnings_ru = translate_safety_lines_to_ru(result.warnings)
        interactions_ru = translate_safety_lines_to_ru(result.interactions)
        adverse_reactions_ru = translate_safety_lines_to_ru(result.adverse_reactions)
        status = "ok" if result.status in {"ok", "empty"} else "error"
        self.store.upsert_drug_safety_cache(
            {
                "inn": inn,
                "source": "openfda",
                "contraindications": contraindications_ru,
                "warnings": warnings_ru,
                "interactions": interactions_ru,
                "adverse_reactions": adverse_reactions_ru,
                "source_updated_at": result.source_updated_at,
                "fetched_at": now.isoformat(),
                "expires_at": expires_at.isoformat(),
                "raw_hash": result.raw_hash,
                "status": status,
                "error_code": result.error_code,
            }
        )
        if result.status in {"ok", "empty"}:
            profile = DrugSafetyProfile(
                inn=inn,
                source="openfda",
                contraindications_ru=contraindications_ru,
                warnings_ru=warnings_ru,
                interactions_ru=interactions_ru,
                adverse_reactions_ru=adverse_reactions_ru,
                updated_at=result.source_updated_at or now.isoformat(),
            )
            return profile, None
        warning = DrugSafetyWarning(
            code=f"OPENFDA_{result.error_code or 'ERROR'}".upper(),
            message=f"Не удалось обновить справочную safety-информацию для {inn}: {result.error_code or 'unknown_error'}",
        )
        return None, warning

    def get_profiles(self, inns: list[str]) -> DrugSafetyFetchResult:
        unique_inns = sorted({str(item).strip().lower() for item in inns if str(item).strip()})
        profiles: list[DrugSafetyProfile] = []
        warnings: list[DrugSafetyWarning] = []
        failures = 0

        for inn in unique_inns:
            cached = self._from_cache(inn)
            if cached is not None:
                profiles.append(cached)
                continue
            fetched, warning = self._fetch_and_cache(inn)
            if fetched is not None:
                profiles.append(fetched)
            else:
                failures += 1
            if warning is not None:
                warnings.append(warning)
                stale_cache = self.store.get_drug_safety_cache(inn)
                if isinstance(stale_cache, dict):
                    profiles.append(
                        DrugSafetyProfile(
                            inn=inn,
                            source="cache_stale",
                            contraindications_ru=[str(item) for item in (stale_cache.get("contraindications") or []) if str(item).strip()],
                            warnings_ru=[str(item) for item in (stale_cache.get("warnings") or []) if str(item).strip()],
                            interactions_ru=[str(item) for item in (stale_cache.get("interactions") or []) if str(item).strip()],
                            adverse_reactions_ru=[str(item) for item in (stale_cache.get("adverse_reactions") or []) if str(item).strip()],
                            updated_at=str(stale_cache.get("source_updated_at") or stale_cache.get("fetched_at") or ""),
                        )
                    )

        if not unique_inns:
            status: DrugSafetyStatus = "unavailable"
        elif failures == 0:
            status = "ok"
        elif len(profiles) > 0:
            status = "partial"
        else:
            status = "unavailable"

        return DrugSafetyFetchResult(status=status, profiles=profiles, warnings=warnings)

    def warmup_cache(self, inns: list[str]) -> dict[str, Any]:
        result = self.get_profiles(inns)
        return {
            "status": result.status,
            "requested": len({str(item).strip().lower() for item in inns if str(item).strip()}),
            "profiles": len(result.profiles),
            "warnings": [warning.__dict__ for warning in result.warnings],
        }

