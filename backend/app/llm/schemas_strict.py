from __future__ import annotations

from typing import TypedDict

from typing_extensions import NotRequired


class StrictIssue(TypedDict):
    issue_id: str
    severity: str
    category: str
    title: str
    description: str
    confidence: float
    chunk_ids: list[str]


class DoctorReportLLMStrict(TypedDict):
    schema_version: str
    report_id: str
    kb_version: str
    summary: str
    issues: list[StrictIssue]
    missing_data: list[dict[str, str]]
    notes: str
    drug_safety: NotRequired[dict[str, object]]


class PatientExplainLLMStrict(TypedDict):
    schema_version: str
    kb_version: str
    based_on_report_id: str
    summary: str
    key_points: list[str]
    questions_to_ask_doctor: list[str]
    safety_disclaimer: str
    drug_safety: NotRequired[dict[str, object]]
