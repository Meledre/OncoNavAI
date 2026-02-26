from __future__ import annotations

from backend.app.casefacts.extractor import extract_case_facts
from backend.app.service import OncoService


def _iter_evidence_spans(node: object) -> list[dict[str, object]]:
    spans: list[dict[str, object]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "evidence_spans" and isinstance(value, list):
                spans.extend(item for item in value if isinstance(item, dict))
            else:
                spans.extend(_iter_evidence_spans(value))
    elif isinstance(node, list):
        for item in node:
            spans.extend(_iter_evidence_spans(item))
    return spans


def test_build_case_text_for_casefacts_prefers_case_json_notes() -> None:
    case_notes = "Стадия pT3N2M0. PD-L1 CPS=8. HER2 1+. MSS."
    normalized_payload = {
        "case": {"notes": case_notes},
        "treatment_plan": {"plan_text": f"Last plan regimen: XELOX\n{case_notes}\n{case_notes}"},
    }
    case_json = {"notes": case_notes}

    built = OncoService._build_case_text_for_casefacts(normalized_payload=normalized_payload, case_json=case_json)

    assert built == case_notes


def test_casefacts_evidence_spans_are_bounded_by_selected_case_notes() -> None:
    case_notes = (
        "Пациент с аденокарциномой ПЖП. Стадия pT3N2M0. "
        "HER2/neu IHC 1+. PD-L1 (CPS): 8. MSS. "
        "2 линия: рамуцирумаб + паклитаксел, прогрессирование."
    )
    normalized_payload = {
        "case": {"notes": case_notes},
        "treatment_plan": {"plan_text": f"План: XELOX\\n{case_notes}\\n{case_notes}"},
    }
    case_json = {"notes": case_notes}

    built = OncoService._build_case_text_for_casefacts(normalized_payload=normalized_payload, case_json=case_json)
    payload = extract_case_facts(case_text=built, case_json=case_json).model_dump()
    spans = _iter_evidence_spans(payload)

    assert spans
    assert all(int(item.get("char_start") or 0) >= 0 for item in spans)
    assert all(int(item.get("char_end") or 0) <= len(case_notes) for item in spans)
