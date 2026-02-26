from __future__ import annotations

import re

from backend.app.drugs.models import DrugExtractedInn, DrugSafetyProfile, DrugSafetySignal, DrugUnresolvedCandidate


def _has_anticoagulant(text: str) -> bool:
    return bool(
        re.search(
            r"варфарин|warfarin|апиксабан|apixaban|ривароксабан|rivaroxaban|дабигатран|dabigatran|гепарин",
            str(text or ""),
            flags=re.IGNORECASE,
        )
    )


def _contains_inn(extracted: list[DrugExtractedInn], inn: str) -> bool:
    target = str(inn or "").strip().lower()
    if not target:
        return False
    return any(str(item.inn or "").strip().lower() == target for item in extracted)


def _profiles_by_inn(profiles: list[DrugSafetyProfile]) -> dict[str, DrugSafetyProfile]:
    return {str(item.inn or "").strip().lower(): item for item in profiles if str(item.inn or "").strip()}


def build_drug_safety_signals(
    *,
    extracted: list[DrugExtractedInn],
    profiles: list[DrugSafetyProfile],
    unresolved: list[DrugUnresolvedCandidate],
    case_text: str,
) -> list[DrugSafetySignal]:
    signals: list[DrugSafetySignal] = []
    profile_map = _profiles_by_inn(profiles)
    text = str(case_text or "")

    if _contains_inn(extracted, "capecitabine") and _has_anticoagulant(text):
        signals.append(
            DrugSafetySignal(
                severity="warning",
                kind="contraindication",
                summary="Капецитабин и антикоагулянты: риск клинически значимого взаимодействия.",
                details="Нужен усиленный контроль коагуляции и оценка риска кровотечений до продолжения терапии.",
                linked_inn=["capecitabine"],
                source_origin="guideline_heuristic",
            )
        )

    if _contains_inn(extracted, "ramucirumab") and _has_anticoagulant(text):
        signals.append(
            DrugSafetySignal(
                severity="warning",
                kind="contraindication",
                summary="Анти-VEGF терапия на фоне антикоагулянтов требует усиленного контроля безопасности.",
                details="Перед продолжением схемы проверьте коагуляцию и риск кровотечений.",
                linked_inn=["ramucirumab"],
                source_origin="guideline_heuristic",
            )
        )

    for inn, profile in profile_map.items():
        if profile.contraindications_ru:
            signals.append(
                DrugSafetySignal(
                    severity="info",
                    kind="inconsistency",
                    summary=f"Для {inn} найдены справочные противопоказания, требуется клиническая сверка с текущим кейсом.",
                    details=profile.contraindications_ru[0],
                    linked_inn=[inn],
                    source_origin="api_derived",
                )
            )

    if unresolved:
        mentions = ", ".join(item.mention for item in unresolved[:4])
        signals.append(
            DrugSafetySignal(
                severity="info",
                kind="missing_data",
                summary="Часть упоминаний препаратов не распознана словарем.",
                details=f"Требуется ручная верификация названий: {mentions}",
                linked_inn=[],
                source_origin="rule_engine",
            )
        )

    dedup: list[DrugSafetySignal] = []
    seen: set[tuple[str, str]] = set()
    for signal in signals:
        key = (signal.kind, signal.summary)
        if key in seen:
            continue
        seen.add(key)
        dedup.append(signal)
    return dedup[:12]
