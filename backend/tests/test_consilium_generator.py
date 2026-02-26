from __future__ import annotations

from pathlib import Path

from backend.app.config import Settings
from backend.app.service import OncoService


def make_settings(root: Path) -> Settings:
    data = root / "data"
    return Settings(
        project_root=root,
        data_dir=data,
        docs_dir=data / "docs",
        reports_dir=data / "reports",
        db_path=data / "oncoai.sqlite3",
        local_core_base_url="http://localhost:8000",
        demo_token="demo-token",
        rate_limit_per_minute=100,
        llm_primary_url="",
        llm_primary_model="gpt-4o-mini",
        llm_primary_api_key="",
        llm_fallback_url="",
        llm_fallback_model="qwen2.5-7b-instruct",
        llm_fallback_api_key="",
        reasoning_mode="compat",
    )


def _pack_request(
    *,
    request_id: str,
    notes: str,
    plan_text: str,
    source_ids: list[str] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "0.2",
        "request_id": request_id,
        "query_type": "NEXT_STEPS",
        "sources": {"mode": "SINGLE", "source_ids": source_ids or ["minzdrav"]},
        "language": "ru",
        "case": {
            "case_json": {
                "schema_version": "1.0",
                "case_id": f"case-{request_id}",
                "import_profile": "FREE_TEXT",
                "patient": {"sex": "female", "birth_year": 1970},
                "diagnoses": [
                    {
                        "diagnosis_id": f"diag-{request_id}",
                        "disease_id": f"disease-{request_id}",
                        "icd10": "C16",
                        "stage": {"system": "TNM8", "stage_group": "IV"},
                        "biomarkers": [],
                        "timeline": [],
                        "last_plan": {
                            "date": "2026-02-21",
                            "precision": "day",
                            "regimen": plan_text,
                            "line": 1,
                            "cycle": 1,
                        },
                    }
                ],
                "attachments": [],
                "notes": notes,
            }
        },
        "options": {"strict_evidence": True, "max_chunks": 20, "max_citations": 20, "timeout_ms": 120000},
    }


def test_consilium_uses_not_found_phrase_when_retrieval_has_no_real_evidence(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    payload = _pack_request(
        request_id="consilium-no-evidence",
        notes="Синтетический кейс без загруженных рекомендаций.",
        plan_text="Рассмотреть последующие шаги лечения.",
    )

    response = service.analyze(payload=payload, role="clinician", client_id="consilium-test")
    consilium_md = str(response["doctor_report"]["consilium_md"])
    assert "Не найдено в предоставленных рекомендациях" in consilium_md


def test_consilium_does_not_propose_immunotherapy_by_default_for_mss_low_cps(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    payload = _pack_request(
        request_id="consilium-immuno-guard",
        notes="Биомаркеры: PD-L1 CPS=0, MSS.",
        plan_text="Предложить иммунотерапию как дефолтную опцию.",
    )

    response = service.analyze(payload=payload, role="clinician", client_id="consilium-test")
    consilium_md = str(response["doctor_report"]["consilium_md"])
    assert "Иммунотерапия не предлагается по умолчанию" in consilium_md
    assert "Предложить иммунотерапию как дефолтную опцию." not in consilium_md


def test_consilium_includes_reconciled_timeline_for_n5_like_case(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    payload = _pack_request(
        request_id="consilium-n5-timeline",
        notes=(
            "Аденокарцинома пищеводно-желудочного перехода (ПЖП), стадия III, cT3N2M0, pT3N2M0. "
            "HER2 1+, PD-L1 CPS 8/3, MSS. "
            "Периоперационная XELOX 4 курса, операция Льюиса, R1, D2. "
            "Адъювант капецитабин. Затем рамуцирумаб + паклитаксел, далее прогрессирование."
        ),
        plan_text="Выбрать следующую линию лечения после прогрессирования.",
        source_ids=["minzdrav", "russco"],
    )

    response = service.analyze(payload=payload, role="clinician", client_id="consilium-test")
    consilium_md = str(response["doctor_report"]["consilium_md"])
    timeline = response["doctor_report"]["timeline"]
    assert isinstance(timeline, list)
    assert len(timeline) >= 3
    timeline_labels = [str(item.get("label") or "") for item in timeline if isinstance(item, dict)]
    assert any("XELOX/CAPOX" in label for label in timeline_labels)
    assert any("R1/D2/Льюис" in label for label in timeline_labels)
    assert any("рамуцирумаб + паклитаксел" in label for label in timeline_labels)
    assert "Клиническая последовательность" in consilium_md
    assert "XELOX/CAPOX" in consilium_md
    assert "R1/D2/Льюис" in consilium_md
    assert "рамуцирумаб + паклитаксел" in consilium_md
    assert "пищеводно-желудоч" in consilium_md.lower()
    assert "пжп" in consilium_md.lower()
    assert "стадия III" in consilium_md
    assert "cT3N2M0" in consilium_md
    assert "pT3N2M0" in consilium_md
    assert "HER2 1+" in consilium_md
    assert "1+ HER2" in consilium_md
    # In fail-closed mode without retrieved evidence, therapeutic suggestions are withheld.
    assert "не найдено в предоставленных рекомендациях" in consilium_md.lower()
    assert "иринотек" not in consilium_md.lower()
    assert "минздрав" in consilium_md.lower()
    assert "russco" in consilium_md.lower()


def test_consilium_includes_minzdrav_russco_basis_without_n5_profile(tmp_path: Path) -> None:
    service = OncoService(make_settings(tmp_path))
    payload = _pack_request(
        request_id="consilium-general-source-basis",
        notes="Синтетический кейс: стадия III, HER2 1+, MSS. Без детального N5-таймлайна.",
        plan_text="Выбрать последующий этап лечения.",
        source_ids=["minzdrav", "russco"],
    )

    response = service.analyze(payload=payload, role="clinician", client_id="consilium-test")
    consilium_md = str(response["doctor_report"]["consilium_md"]).lower()
    assert "минздрав: первичная валидация тактики" in consilium_md
    assert "russco: дополнительная проверка" in consilium_md
