from __future__ import annotations

from typing import Any


def enforce_retrieved_evidence(
    doctor_report: dict[str, Any],
    retrieved_chunk_ids: set[str],
    downgrade_invalid_to_data_quality: bool = True,
    preserve_downgraded_without_evidence: bool = False,
) -> dict[str, Any]:
    sanitized_issues = []
    for issue in doctor_report.get("issues", []):
        valid_evidence = [
            evidence for evidence in issue.get("evidence", []) if evidence.get("chunk_id") in retrieved_chunk_ids
        ]
        if valid_evidence:
            issue = dict(issue)
            issue["evidence"] = valid_evidence
            sanitized_issues.append(issue)
            continue

        if downgrade_invalid_to_data_quality:
            downgraded = dict(issue)
            downgraded["issue_id"] = issue.get("issue_id", "invalid-evidence")
            downgraded["severity"] = "note"
            downgraded["category"] = "data_quality"
            downgraded["title"] = issue.get("title", "Evidence mismatch")
            downgraded["description"] = "Issue was downgraded because citation does not belong to retrieval context."
            downgraded["confidence"] = 0.2
            downgraded["evidence"] = []
            sanitized_issues.append(downgraded)

    doctor_report = dict(doctor_report)
    if preserve_downgraded_without_evidence:
        doctor_report["issues"] = sanitized_issues
    else:
        doctor_report["issues"] = [item for item in sanitized_issues if item.get("evidence")]
    return doctor_report
