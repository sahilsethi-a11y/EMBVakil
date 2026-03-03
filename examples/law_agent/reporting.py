"""Report rendering helpers."""

from __future__ import annotations

from collections import Counter

from .models import Report


def render_markdown_report(report: Report) -> str:
    """Render a human-readable markdown report."""
    severity_counts = Counter(item.severity for item in report.findings)

    lines = [
        "# Law Agent Contract Review",
        "",
        f"- **Document type:** `{report.doc_type}`",
        f"- **Overall risk:** `{report.overall_risk}`",
        (
            "- **Findings by severity:** "
            f"high={severity_counts.get('high', 0)}, "
            f"med={severity_counts.get('med', 0)}, "
            f"low={severity_counts.get('low', 0)}"
        ),
        "",
        "## Summary",
        "",
        report.summary,
        "",
        "## Findings",
        "",
    ]

    if not report.findings:
        lines.extend(["No material risks found based on the selected playbook.", ""])

    for finding in report.findings:
        lines.extend(
            [
                (f"- **{finding.clause_id} | {finding.severity.upper()} | {finding.issue}**"),
                f"  - Why: {finding.why}",
                f"  - Excerpt: `{finding.excerpt}`",
                f"  - Recommendation: {finding.recommendation}",
            ]
        )
        if finding.citations:
            lines.append(f"  - Citations: {', '.join(finding.citations)}")
        if finding.suggested_redline:
            lines.append(f"  - Suggested edit: {finding.suggested_redline}")

    lines.extend(["", "## Assumptions", ""])
    if report.assumptions:
        for assumption in report.assumptions:
            lines.append(f"- {assumption}")
    else:
        lines.append("- None.")

    lines.extend(["", "## Missing Information Questions", ""])
    if report.missing_info_questions:
        for question in report.missing_info_questions:
            lines.append(f"- {question}")
    else:
        lines.append("- None.")

    lines.extend(
        ["", "## Disclaimer", "", "This output is an AI-assisted review and is not legal advice."]
    )
    return "\n".join(lines).strip() + "\n"
