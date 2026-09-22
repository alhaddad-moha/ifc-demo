"""Machine-readable output. This is the contract a web UI or CI job consumes."""

from __future__ import annotations

import json
from typing import Any, Optional

from ..issues import AuditResult


def write(result: AuditResult, path: str,
          ids_summary: Optional[dict[str, Any]] = None) -> str:
    payload = result.to_dict()
    if ids_summary:
        payload["ids"] = ids_summary
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False, default=str)
    return path
