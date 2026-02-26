from __future__ import annotations

import re
from typing import Any

from backend.app.casefacts.extractor import extract_case_metrics
from backend.app.clinical_calcs import cockcroft_gault_crcl_ml_min, umol_l_to_mg_dl


def _contains_plan_token(plan_sections: list[dict[str, Any]], pattern: str) -> bool:
    regex = re.compile(pattern, flags=re.IGNORECASE)
    for section in plan_sections:
        if not isinstance(section, dict):
            continue
        steps = section.get("steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, dict):
                continue
            step_text = str(step.get("text") or step.get("name") or "").strip()
            if step_text and regex.search(step_text):
                return True
    return False


def _is_metastatic(case_facts: dict[str, Any], disease_context: dict[str, Any], case_text: str) -> bool:
    setting = str(disease_context.get("setting") or "").strip().lower()
    if setting == "metastatic":
        return True
    metastases = case_facts.get("metastases")
    if isinstance(metastases, list) and metastases:
        return True
    return bool(re.search(r"\bM1\b|\bIV\b|метастаз", case_text, flags=re.IGNORECASE))


def _is_her2_positive(case_facts: dict[str, Any]) -> bool:
    biomarkers = case_facts.get("biomarkers") if isinstance(case_facts.get("biomarkers"), dict) else {}
    if str(biomarkers.get("her2_interpretation") or "").strip().lower() == "positive":
        return True
    her2_value = str(biomarkers.get("her2") or "").strip().lower()
    return her2_value in {"3+", "positive", "pos"}


def _has_text(pattern: str, text: str) -> bool:
    return bool(re.search(pattern, str(text or ""), flags=re.IGNORECASE))


def _has_anticoagulant(text: str) -> bool:
    return _has_text(r"варфарин|warfarin|апиксабан|apixaban|ривароксабан|rivaroxaban|дабигатран|dabigatran|гепарин", text)


def _has_antiplatelet(text: str) -> bool:
    return _has_text(r"клопидогрел|аспирин|ацетилсалицил|ticagrelor|prasugrel", text)


def _has_antiviral_prophylaxis(text: str) -> bool:
    for match in re.finditer(r"энтекавир|тенофовир|противовирус\w*", str(text or ""), flags=re.IGNORECASE):
        left = str(text or "")[max(0, match.start() - 24): match.start()]
        if re.search(r"\b(без|не)\b", left, flags=re.IGNORECASE):
            continue
        return True
    return False


def _clinical_scope_text(case_text: str) -> str:
    text = str(case_text or "")
    if not text:
        return ""
    lowered = text.lower()
    markers = [
        "рекомендация ai-помощника",
        "для врача (краткое обоснование",
        "что нужно сделать:",
    ]
    cut_positions = [lowered.find(marker) for marker in markers if lowered.find(marker) >= 0]
    cutoff = min(cut_positions) if cut_positions else len(text)
    return text[:cutoff].strip()[:6000]


def apply_gastric_rules(
    *,
    case_facts: dict[str, Any],
    disease_context: dict[str, Any],
    case_text: str,
    plan_sections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    scoped_case_text = _clinical_scope_text(case_text)
    issues: list[dict[str, Any]] = []
    metrics = extract_case_metrics(case_text=scoped_case_text)
    has_error_signal = _has_text(r"ошибк\w*|несоответств\w*|неправильн\w*|противопоказ\w*", scoped_case_text)

    line = disease_context.get("line")
    line_value = int(line) if isinstance(line, int) else 1

    creatinine_mg_dl: float | None = None
    if isinstance(metrics.get("creatinine_value"), (int, float)):
        value = float(metrics.get("creatinine_value"))
        units = str(metrics.get("creatinine_units") or "").lower()
        if "мкмоль" in units or "умоль" in units:
            creatinine_mg_dl = umol_l_to_mg_dl(value)
        elif value > 15.0:
            # Missing units but value scale suggests umol/L.
            creatinine_mg_dl = umol_l_to_mg_dl(value)
        else:
            creatinine_mg_dl = value
    crcl_ml_min = cockcroft_gault_crcl_ml_min(
        age=metrics.get("age") if isinstance(metrics.get("age"), int) else None,
        weight_kg=metrics.get("weight_kg") if isinstance(metrics.get("weight_kg"), (int, float)) else None,
        serum_creatinine_mg_dl=creatinine_mg_dl,
        sex=str(metrics.get("sex") or ""),
    )

    if _is_her2_positive(case_facts) and _is_metastatic(case_facts, disease_context, case_text) and line_value <= 1:
        if not _contains_plan_token(plan_sections, r"trastuzumab|трастузумаб"):
            issues.append(
                {
                    "severity": "critical",
                    "kind": "deviation",
                    "summary": "В 1-й линии HER2-положительного метастатического процесса отсутствует трастузумаб.",
                    "details": "Для HER2-положительного метастатического рака желудка в 1-й линии требуется проверить добавление трастузумаба.",
                    "field_path": "plan.treatment",
                }
            )

    if _contains_plan_token(plan_sections, r"\bcisplatin\b|\bцисплатин\b"):
        has_creatinine = bool(metrics.get("has_creatinine"))
        has_egfr = bool(metrics.get("has_egfr"))
        if not (has_creatinine and has_egfr):
            issues.append(
                {
                    "severity": "warning",
                    "kind": "missing_data",
                    "summary": "Перед цисплатином нет подтверждения функции почек.",
                    "details": "Требуются креатинин и eGFR (CKD-EPI) до назначения цисплатина.",
                    "field_path": "case.labs.renal",
                }
            )
        elif isinstance(crcl_ml_min, (int, float)) and float(crcl_ml_min) < 50.0:
            issues.append(
                {
                    "severity": "warning",
                    "kind": "contraindication",
                    "summary": "Назначение цисплатина при сниженной функции почек требует пересмотра.",
                    "details": f"Расчетный CrCl по Cockcroft-Gault ~{float(crcl_ml_min):.1f} мл/мин; рассмотрите альтернативу/коррекцию.",
                    "field_path": "case.labs.renal",
                }
            )
        elif creatinine_mg_dl is None or metrics.get("age") is None or metrics.get("weight_kg") is None:
            issues.append(
                {
                    "severity": "warning",
                    "kind": "missing_data",
                    "summary": "Не хватает данных для расчета клиренса креатинина перед цисплатином.",
                    "details": "Нужны возраст, масса тела и числовой креатинин для Cockcroft-Gault.",
                    "field_path": "case.labs.renal",
                }
            )

    if _contains_plan_token(plan_sections, r"\bbiopsy\b|биопси"):
        inr_max = metrics.get("inr_max")
        if isinstance(inr_max, (int, float)) and float(inr_max) >= 1.5:
            issues.append(
                {
                    "severity": "critical",
                    "kind": "contraindication",
                    "summary": "Повышенный INR/МНО перед инвазивной процедурой.",
                    "details": "Перед биопсией требуется коррекция коагуляции и повторный контроль INR.",
                    "field_path": "case.labs.coagulation",
                }
            )

    if _contains_plan_token(plan_sections, r"oxaliplatin|оксалиплатин"):
        neuropathy_grade = metrics.get("neuropathy_grade")
        if isinstance(neuropathy_grade, int) and neuropathy_grade >= 2:
            issues.append(
                {
                    "severity": "warning",
                    "kind": "contraindication",
                    "summary": "Продолжение оксалиплатина при нейропатии >=2 требует пересмотра.",
                    "details": "Рассмотрите деэскалацию/смену схемы и поддерживающую терапию нейропатии.",
                    "field_path": "case.toxicity.neuropathy",
                }
            )

    if _contains_plan_token(plan_sections, r"ramucirumab|рамуцирумаб|bevacizumab|бевацизумаб"):
        if _has_anticoagulant(scoped_case_text) or _has_antiplatelet(scoped_case_text):
            issues.append(
                {
                    "severity": "warning",
                    "kind": "contraindication",
                    "summary": "Антикоагулянт/антиагрегант на фоне анти-VEGF-терапии требует усиленного контроля кровотечений.",
                    "details": "Проверьте коагуляцию, риск кровотечений и показания к продолжению антикоагулянта перед анти-VEGF-терапией.",
                    "field_path": "case.labs.coagulation",
                }
            )

    if _contains_plan_token(plan_sections, r"капецитабин|capecitabine"):
        if _has_anticoagulant(scoped_case_text):
            issues.append(
                {
                    "severity": "warning",
                    "kind": "contraindication",
                    "summary": "Капецитабин и варфарин/антикоагулянт: риск клинически значимого взаимодействия.",
                    "details": "Нужен частый контроль INR/кровотечений и рассмотрение безопасной схемы антикоагуляции.",
                    "field_path": "case.labs.coagulation",
                }
            )

    if _contains_plan_token(plan_sections, r"pembrolizumab|nivolumab|иммунотерап|ингибитор\w*\s+pd-1|pd-1") or _has_text(
        r"пембролизумаб|ниволумаб|иммунотерап|ингибитор\w*\s+pd-1|pd-1", scoped_case_text
    ):
        if _has_text(r"ревматоид\w*\s+артрит|аутоиммун\w*|das28|аццп|ревматоидн\w*\s+фактор", scoped_case_text):
            issues.append(
                {
                    "severity": "critical",
                    "kind": "contraindication",
                    "summary": "Иммунотерапия при активном аутоиммунном заболевании требует отдельного консилиума.",
                    "details": "Нужна оценка риска тяжелых иммуноопосредованных осложнений и совместное решение с профильным специалистом.",
                    "field_path": "case.comorbidity.autoimmune",
                }
            )

    if has_error_signal and _has_text(r"метотрексат", scoped_case_text) and _has_text(r"хбп|ckd|рскф|egfr", scoped_case_text):
        issues.append(
            {
                "severity": "critical",
                "kind": "contraindication",
                "summary": "Высокодозный метотрексат при почечной дисфункции противопоказан без строгой коррекции.",
                "details": "Нужна оценка клиренса, коррекция дозы/альтернатива и мониторинг токсичности до старта терапии.",
                "field_path": "case.labs.renal",
            }
        )

    if has_error_signal and _has_text(r"\becf\b|эпирубицин|антрациклин", scoped_case_text) and _has_text(
        r"хсн|сердечн\w*\s+недостаточ|фв\s*(?:4[0-9]|[0-3][0-9])", scoped_case_text
    ):
        issues.append(
            {
                "severity": "critical",
                "kind": "contraindication",
                "summary": "Кардиотоксичная схема при сниженной ФВ/ХСН требует пересмотра.",
                "details": "Перед антрациклинами обязательна кардиооценка и выбор безопасной альтернативы при высоком риске.",
                "field_path": "case.cardiac_function",
            }
        )

    if has_error_signal and _has_text(
        r"her2[^.\n\r]{0,40}(positive|позитив|положител\w*|fish\+)|fish\+[^.\n\r]{0,40}her2",
        scoped_case_text,
    ):
        if not _contains_plan_token(plan_sections, r"trastuzumab|трастузумаб"):
            issues.append(
                {
                    "severity": "critical",
                    "kind": "deviation",
                    "summary": "HER2-положительный контекст без анти-HER2 ветки в плане.",
                    "details": "Нужно рассмотреть анти-HER2 компонент при подтвержденной HER2-позитивности.",
                    "field_path": "plan.treatment",
                }
            )

    if has_error_signal and _has_text(r"колит[^.\n\r]{0,30}(grade\s*3|grade\s*4|3-4)|жизнеугрож\w*\s+колит", scoped_case_text):
        if _contains_plan_token(plan_sections, r"pembrolizumab|nivolumab|иммунотерап|ингибитор\w*\s+pd-1|pd-1") or _has_text(
            r"пембролизумаб|ниволумаб|возобновлени\w*\s+иммунотерап", scoped_case_text
        ):
            issues.append(
                {
                    "severity": "critical",
                    "kind": "contraindication",
                    "summary": "Реинтродукция PD-1 терапии после тяжелого иммуно-колита требует запрета/консилиума.",
                    "details": "После Grade 3-4 иммуноопосредованного колита повторный старт PD-1 обычно противопоказан.",
                    "field_path": "case.toxicity.immune_colitis",
                }
            )

    if has_error_signal and _has_text(r"трастузумаб|trastuzumab", scoped_case_text) and _has_text(
        r"хсн|сердечн\w*\s+недостаточ|фв\s*(?:4[0-9]|[0-3][0-9])",
        scoped_case_text,
    ):
        issues.append(
            {
                "severity": "warning",
                "kind": "contraindication",
                "summary": "Анти-HER2 терапия при сниженной ФВ требует кардиопротекции и контроля.",
                "details": "Нужны Эхо-КГ до старта и в динамике, а также коррекция кардиорисков до продолжения трастузумаба.",
                "field_path": "case.cardiac_function",
            }
        )

    if has_error_signal and _has_text(r"нпвп|кеторолак|диклофенак|ибупрофен", scoped_case_text) and _has_text(
        r"хбп|рскф|egfr|язвенн\w*\s+анамнез",
        scoped_case_text,
    ):
        issues.append(
            {
                "severity": "critical",
                "kind": "contraindication",
                "summary": "НПВП-нагрузка при ХБП/язвенном риске требует отмены и безопасной анальгезии.",
                "details": "Нужна деэскалация НПВП, гастропротекция и мониторинг почечной функции.",
                "field_path": "case.supportive.pain_management",
            }
        )

    if has_error_signal and _has_text(r"khorana\s*[34]|высок\w*\s+риск\s+тэл|тромбоэмбол", scoped_case_text):
        if _has_text(r"без\s+профилактик\w*|отсутств\w*[^.\n\r]{0,30}профилактик\w*", scoped_case_text):
            issues.append(
                {
                    "severity": "warning",
                    "kind": "deviation",
                    "summary": "Высокий тромботический риск без профилактики ТЭО.",
                    "details": "Нужно рассмотреть первичную тромбопрофилактику при высоком VTE-риске.",
                    "field_path": "case.thrombosis_risk",
                }
            )

    if has_error_signal and _has_text(r"стади\w*\s*iii|ct3n1m0|местнораспространенн", scoped_case_text) and _has_text(
        r"первичн\w*\s+хирург\w*|сразу\s+операци\w*",
        scoped_case_text,
    ):
        issues.append(
            {
                "severity": "warning",
                "kind": "deviation",
                "summary": "Для местнораспространенного процесса нужна проверка периоперационной системной терапии.",
                "details": "Перед первичной операцией необходимо оценить соответствие тактики актуальным клинрекомендациям.",
                "field_path": "plan.treatment",
            }
        )

    if has_error_signal and not any(
        item.get("kind") in {"deviation", "contraindication", "inconsistency", "missing_data"} for item in issues
    ):
        issues.append(
            {
                "severity": "warning",
                "kind": "inconsistency",
                "summary": "В кейсе указан сигнал клинического несоответствия; требуется разбор тактики.",
                "details": "Текст кейса содержит явный индикатор ошибки/несоответствия, но детализированное правило не сработало.",
                "field_path": "case.validation",
            }
        )

    if _has_text(r"hbsag\+?|hbv\s*dna|гепатит\s*b", scoped_case_text) and _contains_plan_token(
        plan_sections, r"flot|химиотерап|цитотоксич"
    ):
        if not _has_antiviral_prophylaxis(scoped_case_text):
            issues.append(
                {
                    "severity": "critical",
                    "kind": "contraindication",
                    "summary": "HBV-реактивация: нужна противовирусная профилактика до химиотерапии.",
                    "details": "При HBsAg+ / HBV DNA+ требуется старт противовирусной профилактики и мониторинг печеночных тестов.",
                    "field_path": "case.infection.hbv",
                }
            )

    if _has_text(r"беремен\w*|беременность", scoped_case_text) and _contains_plan_token(
        plan_sections, r"flot|доцетаксел|оксалиплатин|5-фу|химиотерап"
    ):
        issues.append(
            {
                "severity": "critical",
                "kind": "contraindication",
                "summary": "Беременность и системная терапия: требуется мультидисциплинарный консилиум.",
                "details": "Тактика должна согласовываться с онкологом, акушером-гинекологом и перинатальной командой до старта терапии.",
                "field_path": "case.special_conditions.pregnancy",
            }
        )

    if _has_text(r"пиелонефрит|бактериур\w*|лейкоцитур\w*|уросепс\w*|сепсис", scoped_case_text) and _contains_plan_token(
        plan_sections, r"лучев\w*|химиолуч\w*|химиотерап|цитотоксич"
    ):
        issues.append(
            {
                "severity": "critical",
                "kind": "contraindication",
                "summary": "Активная инфекция: сначала санация, затем противоопухолевое лечение.",
                "details": "Перед химио-/лучевой терапией требуется контроль очага инфекции и подтверждение клинико-лабораторной стабилизации.",
                "field_path": "case.infection.active",
            }
        )

    if _has_text(r"золедрон\w*|zoledron", scoped_case_text) and _has_text(
        r"гипокальци\w*|гипопаратире\w*|дефицит\w*\s+витамин\w*\s*d", scoped_case_text
    ):
        issues.append(
            {
                "severity": "critical",
                "kind": "contraindication",
                "summary": "Бисфосфонат при гипокальциемии без коррекции повышает риск жизнеугрожающих осложнений.",
                "details": "Нужна коррекция кальция/витамина D, оценка функции почек и стоматологический осмотр до введения препарата.",
                "field_path": "case.supportive.bone",
            }
        )

    return issues
