from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class OpenFDASafetyResult:
    inn: str
    contraindications: list[str]
    warnings: list[str]
    interactions: list[str]
    adverse_reactions: list[str]
    source_updated_at: str
    raw_hash: str
    status: str
    error_code: str


def _slice_lines(value: Any, *, max_items: int = 8, max_chars: int = 900) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if not text:
            continue
        text = " ".join(text.split())
        out.append(text[:max_chars])
        if len(out) >= max_items:
            break
    return out


def fetch_openfda_drug_label(
    *,
    inn: str,
    timeout_sec: int = 12,
    base_url: str = "https://api.fda.gov",
) -> OpenFDASafetyResult:
    normalized_inn = str(inn or "").strip().lower()
    if not normalized_inn:
        return OpenFDASafetyResult(
            inn="",
            contraindications=[],
            warnings=[],
            interactions=[],
            adverse_reactions=[],
            source_updated_at="",
            raw_hash="",
            status="error",
            error_code="invalid_inn",
        )
    search_expr = f'openfda.generic_name:"{normalized_inn}"'
    query = urllib.parse.urlencode({"search": search_expr, "limit": 1})
    url = f"{base_url.rstrip('/')}/drug/label.json?{query}"
    request = urllib.request.Request(url, headers={"accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            raw_bytes = response.read()
            payload = json.loads(raw_bytes.decode("utf-8"))
    except TimeoutError:
        return OpenFDASafetyResult(
            inn=normalized_inn,
            contraindications=[],
            warnings=[],
            interactions=[],
            adverse_reactions=[],
            source_updated_at="",
            raw_hash="",
            status="error",
            error_code="timeout",
        )
    except urllib.error.URLError:
        return OpenFDASafetyResult(
            inn=normalized_inn,
            contraindications=[],
            warnings=[],
            interactions=[],
            adverse_reactions=[],
            source_updated_at="",
            raw_hash="",
            status="error",
            error_code="network_error",
        )
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return OpenFDASafetyResult(
            inn=normalized_inn,
            contraindications=[],
            warnings=[],
            interactions=[],
            adverse_reactions=[],
            source_updated_at="",
            raw_hash="",
            status="error",
            error_code="invalid_response",
        )

    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list) or not results:
        return OpenFDASafetyResult(
            inn=normalized_inn,
            contraindications=[],
            warnings=[],
            interactions=[],
            adverse_reactions=[],
            source_updated_at="",
            raw_hash="",
            status="empty",
            error_code="not_found",
        )

    row = results[0] if isinstance(results[0], dict) else {}
    contraindications = _slice_lines(row.get("contraindications"))
    warnings = _slice_lines(row.get("warnings")) or _slice_lines(row.get("warnings_and_cautions"))
    interactions = _slice_lines(row.get("drug_interactions"))
    adverse_reactions = _slice_lines(row.get("adverse_reactions"))

    meta = payload.get("meta") if isinstance(payload, dict) else {}
    source_updated_at = ""
    if isinstance(meta, dict):
        source_updated_at = str(meta.get("last_updated") or "").strip()
    if not source_updated_at:
        source_updated_at = datetime.now(timezone.utc).isoformat()

    raw_hash = str(abs(hash(json.dumps(row, ensure_ascii=False, sort_keys=True))))
    return OpenFDASafetyResult(
        inn=normalized_inn,
        contraindications=contraindications,
        warnings=warnings,
        interactions=interactions,
        adverse_reactions=adverse_reactions,
        source_updated_at=source_updated_at,
        raw_hash=raw_hash,
        status="ok",
        error_code="",
    )

