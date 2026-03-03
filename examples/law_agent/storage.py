"""Storage helpers for output files and optional local cache."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .models import Finding, Report


class ClauseRiskCache:
    """Tiny JSON-backed cache for clause-level findings."""

    def __init__(self, path: str | Path | None) -> None:
        self.path = Path(path) if path else None
        self._data: dict[str, list[dict[str, Any]]] = {}
        if self.path and self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self._data = loaded
            except json.JSONDecodeError:
                self._data = {}

    @staticmethod
    def make_key(*, clause_text: str, playbook_signature: str) -> str:
        payload = f"{playbook_signature}\n{clause_text}".encode()
        return hashlib.sha256(payload).hexdigest()

    def get(self, key: str) -> list[Finding] | None:
        raw = self._data.get(key)
        if raw is None:
            return None
        return [Finding.model_validate(item) for item in raw]

    def set(self, key: str, findings: list[Finding]) -> None:
        self._data[key] = [item.model_dump(mode="json") for item in findings]

    def persist(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")


def playbook_signature(playbook_data: dict[str, Any]) -> str:
    """Stable digest used by the cache."""
    encoded = json.dumps(playbook_data, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def save_report_json(path: str | Path, report: Report) -> Path:
    """Write report JSON to disk."""
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return out_path


def save_report_markdown(path: str | Path, markdown: str) -> Path:
    """Write markdown report to disk."""
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown, encoding="utf-8")
    return out_path
