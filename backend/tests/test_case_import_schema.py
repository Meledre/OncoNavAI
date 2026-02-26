from __future__ import annotations

import uuid

import pytest

from backend.app.exceptions import ValidationError
from backend.app.schemas.case_import import normalize_case_import_payload


def test_normalize_case_import_payload_uppercases_profile() -> None:
    payload = normalize_case_import_payload(
        {
            "schema_version": "1.0",
            "import_profile": "free_text",
            "case_id": str(uuid.uuid4()),
            "free_text": "synthetic case text",
        }
    )
    assert payload["schema_version"] == "1.0"
    assert payload["import_profile"] == "FREE_TEXT"


def test_normalize_case_import_payload_requires_fhir_bundle_for_fhir_profile() -> None:
    with pytest.raises(ValidationError, match="FHIR_BUNDLE requires `fhir_bundle` object payload"):
        normalize_case_import_payload(
            {
                "schema_version": "1.0",
                "import_profile": "FHIR_BUNDLE",
            }
        )


def test_normalize_case_import_payload_requires_kin_text_or_kin_payload_for_kin_profile() -> None:
    with pytest.raises(ValidationError, match="KIN_PDF requires `kin_pdf_text` or `kin_pdf` payload"):
        normalize_case_import_payload(
            {
                "schema_version": "1.0",
                "import_profile": "KIN_PDF",
            }
        )
