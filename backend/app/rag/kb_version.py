from __future__ import annotations

import hashlib
from typing import Any


def compute_kb_version(docs: list[dict[str, Any]]) -> str:
    if not docs:
        return "kb_empty"

    joined = "|".join(
        f"{item['doc_id']}:{item['doc_version']}:{item['sha256']}" for item in sorted(docs, key=lambda x: (x["doc_id"], x["doc_version"]))
    )
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]
    return f"kb_{digest}"
