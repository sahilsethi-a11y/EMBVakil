"""Playbook loading and formatting helpers."""

from __future__ import annotations

import json
from pathlib import Path

from .models import Playbook, PlaybookRule


def load_playbook(playbook_path: str | Path) -> Playbook:
    """Load a playbook from YAML or JSON."""
    path = Path(playbook_path)
    if not path.exists():
        raise FileNotFoundError(f"Playbook file not found: {path}")

    if path.suffix.lower() == ".json":
        raw_data = json.loads(path.read_text(encoding="utf-8"))
    else:
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError(
                "YAML playbooks require PyYAML. Install it with `uv add pyyaml` or use JSON."
            ) from exc
        raw_data = yaml.safe_load(path.read_text(encoding="utf-8"))

    if not isinstance(raw_data, dict):
        raise ValueError("Playbook must be an object with `rules`.")

    rules_raw = raw_data.get("rules", [])
    if not isinstance(rules_raw, list):
        raise ValueError("Playbook `rules` must be a list.")

    rules = [PlaybookRule.model_validate(item) for item in rules_raw]
    return Playbook(name=raw_data.get("name", "Company Playbook"), rules=rules)


def format_playbook_for_prompt(playbook: Playbook) -> str:
    """Render playbook rules in a compact prompt-friendly format."""
    blocks: list[str] = []
    for idx, rule in enumerate(playbook.rules, start=1):
        blocks.append(
            "\n".join(
                [
                    f"Rule {idx}: {rule.name}",
                    f"Risk: {rule.risk}",
                    f"Severity: {rule.severity}",
                    f"Check guidance: {rule.check_guidance}",
                    f"Preferred position: {rule.preferred_position}",
                    f"Fallback language: {rule.fallback_language}",
                ]
            )
        )
    return "\n\n".join(blocks)
