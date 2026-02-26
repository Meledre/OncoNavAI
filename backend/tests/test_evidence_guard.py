from __future__ import annotations

from backend.app.rules.evidence_guard import enforce_retrieved_evidence


def test_evidence_guard_drops_unknown_chunk_ids():
    report = {
        "issues": [
            {
                "issue_id": "1",
                "severity": "important",
                "title": "Issue",
                "description": "Desc",
                "evidence": [{"chunk_id": "unknown"}],
            }
        ]
    }
    guarded = enforce_retrieved_evidence(report, retrieved_chunk_ids={"known"})
    assert guarded["issues"] == []
