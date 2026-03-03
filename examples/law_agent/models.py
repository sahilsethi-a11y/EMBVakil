"""Pydantic models for the Law Agent example."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["low", "med", "high"]
DocType = Literal["nda", "msa", "unknown"]


class Clause(BaseModel):
    """A normalized contract clause."""

    id: str = Field(description="Stable clause identifier such as CL-001.")
    heading: str = Field(description="Short heading for the clause.")
    text: str = Field(description="Full clause text.")
    start_char: int = Field(description="Inclusive starting character index in source doc.")
    end_char: int = Field(description="Exclusive ending character index in source doc.")


class IntakeResult(BaseModel):
    """Document-level metadata from the intake step."""

    doc_type: DocType = Field(description="Best guess document type.")
    short_summary: str = Field(description="Very brief description of what the contract covers.")
    parties: list[str] = Field(description="Detected party names if available.")
    dates: list[str] = Field(description="Detected dates if available.")
    assumptions: list[str] = Field(description="Assumptions made during intake.")


class ClauseExtractionResult(BaseModel):
    """Structured clause extraction output."""

    clauses: list[Clause] = Field(description="Clauses extracted from the contract.")


class PlaybookRule(BaseModel):
    """A single playbook policy rule."""

    name: str
    risk: str
    severity: Severity
    check_guidance: str
    preferred_position: str
    fallback_language: str


class Playbook(BaseModel):
    """Collection of policy rules used for review."""

    name: str = "Company Playbook"
    rules: list[PlaybookRule]


class DraftingInput(BaseModel):
    """Structured prompt for drafting redlines."""

    rule_name: str
    issue: str
    clause_text: str
    preferred_position: str
    fallback_language: str


class DraftingSuggestion(BaseModel):
    """Suggested replacement language for a risky clause."""

    suggested_redline: str
    explanation: str


class Finding(BaseModel):
    """Risk finding for a clause."""

    clause_id: str
    issue: str
    severity: Severity
    why: str
    excerpt: str
    recommendation: str
    suggested_redline: str | None = None
    citations: list[str] = Field(default_factory=list)


class ClauseRiskReview(BaseModel):
    """Risk review output for a single clause."""

    findings: list[Finding]


class Report(BaseModel):
    """Final contract review report."""

    doc_type: DocType
    summary: str
    overall_risk: Severity
    findings: list[Finding]
    assumptions: list[str]
    missing_info_questions: list[str]
