"""Agents and orchestration for the Law Agent example."""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from agents import (
    Agent,
    GuardrailFunctionOutput,
    InputGuardrailTripwireTriggered,
    ModelSettings,
    OutputGuardrailTripwireTriggered,
    RunContextWrapper,
    Runner,
    SQLiteSession,
    TResponseInputItem,
    function_tool,
    gen_trace_id,
    input_guardrail,
    output_guardrail,
    trace,
)

from .models import (
    Clause,
    ClauseExtractionResult,
    ClauseRiskReview,
    DraftingInput,
    DraftingSuggestion,
    Finding,
    IntakeResult,
    Playbook,
    Report,
)
from .playbook import format_playbook_for_prompt, load_playbook
from .rag import LawReferenceRAG
from .reporting import render_markdown_report
from .storage import ClauseRiskCache, playbook_signature, save_report_json, save_report_markdown


@dataclass
class ReviewContext:
    """Mutable run context shared with guardrails."""

    warnings: list[str] = field(default_factory=list)
    expected_clause_ids: set[str] = field(default_factory=set)


def _severity_rank(severity: str) -> int:
    ranks = {"low": 1, "med": 2, "high": 3}
    return ranks.get(severity, 1)


@input_guardrail
async def intake_input_guardrail(
    context: RunContextWrapper[ReviewContext],
    agent: Agent,
    input_data: str | list[TResponseInputItem],
) -> GuardrailFunctionOutput:
    """Reject very short inputs and warn if input appears to contain excessive personal data."""
    text = input_data if isinstance(input_data, str) else json.dumps(input_data)
    stripped = text.strip()

    if len(stripped) < 80:
        return GuardrailFunctionOutput(
            output_info={"reason": "Input is too short for meaningful contract review."},
            tripwire_triggered=True,
        )

    emails = len(re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text))
    ssn_like = len(re.findall(r"\b\d{3}-\d{2}-\d{4}\b", text))
    long_numbers = len(re.findall(r"\b\d{12,16}\b", text))
    if emails + ssn_like + long_numbers >= 4:
        context.context.warnings.append(
            "Input may contain concentrated personal data. Review output handling carefully."
        )

    return GuardrailFunctionOutput(
        output_info={
            "pii_indicators": {
                "emails": emails,
                "ssn_like": ssn_like,
                "long_numbers": long_numbers,
            }
        },
        tripwire_triggered=False,
    )


@output_guardrail
async def report_schema_guardrail(
    context: RunContextWrapper[ReviewContext],
    agent: Agent,
    output: Any,
) -> GuardrailFunctionOutput:
    """Ensure report output conforms to schema and references known clause IDs."""
    try:
        report = Report.model_validate(output)
    except ValidationError as exc:
        return GuardrailFunctionOutput(
            output_info={"validation_errors": exc.errors()},
            tripwire_triggered=True,
        )

    invalid_ids = sorted(
        {
            finding.clause_id
            for finding in report.findings
            if finding.clause_id not in context.context.expected_clause_ids
        }
    )
    if invalid_ids:
        return GuardrailFunctionOutput(
            output_info={"invalid_clause_ids": invalid_ids},
            tripwire_triggered=True,
        )

    return GuardrailFunctionOutput(output_info={"ok": True}, tripwire_triggered=False)


@function_tool
async def load_playbook_tool(playbook_path: str) -> dict[str, Any]:
    """Load and validate a playbook from a YAML or JSON file."""
    playbook = load_playbook(playbook_path)
    return playbook.model_dump(mode="json")


@function_tool
async def save_report_tool(out_dir: str, report_json: str, report_md: str) -> list[str]:
    """Save report.json and report.md under the output directory."""
    out_path = Path(out_dir)
    json_path = out_path / "report.json"
    md_path = out_path / "report.md"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(report_json, encoding="utf-8")
    md_path.write_text(report_md, encoding="utf-8")
    return [str(json_path), str(md_path)]


def _fallback_clause_extraction(document_text: str) -> ClauseExtractionResult:
    """Deterministic fallback parser for clauses."""
    chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n", document_text) if chunk.strip()]
    clauses: list[Clause] = []
    cursor = 0
    for index, chunk in enumerate(chunks, start=1):
        heading = chunk.splitlines()[0][:80]
        start = document_text.find(chunk, cursor)
        if start < 0:
            start = max(0, cursor)
        end = start + len(chunk)
        clauses.append(
            Clause(
                id=f"CL-{index:03d}",
                heading=heading,
                text=chunk,
                start_char=start,
                end_char=end,
            )
        )
        cursor = end
    return ClauseExtractionResult(clauses=clauses)


def _normalize_clause_offsets(document_text: str, clauses: list[Clause]) -> list[Clause]:
    """Recompute offsets based on emitted clause text so spans are valid."""
    normalized: list[Clause] = []
    cursor = 0
    for index, clause in enumerate(clauses, start=1):
        text = clause.text.strip()
        if not text:
            continue
        start = document_text.find(text, cursor)
        if start < 0:
            start = document_text.find(text)
        if start < 0:
            continue
        end = start + len(text)
        normalized.append(
            Clause(
                id=f"CL-{index:03d}",
                heading=clause.heading.strip() or f"Clause {index}",
                text=text,
                start_char=start,
                end_char=end,
            )
        )
        cursor = end
    return normalized


def _build_agents() -> dict[str, Agent]:
    intake_agent = Agent(
        name="IntakeAgent",
        instructions=(
            "You normalize contract intake data. Detect doc_type as nda, msa, or unknown. "
            "Extract obvious parties and dates if present. Keep assumptions concise."
        ),
        output_type=IntakeResult,
        input_guardrails=[intake_input_guardrail],
    )

    clause_agent = Agent(
        name="ClauseAgent",
        instructions=(
            "Extract contract clauses in order. Use stable IDs in CL-001 format. "
            "Each clause should include heading, text, and start/end character offsets over the source text. "
            "Prefer fewer, meaningful clauses over fragmented lines."
        ),
        output_type=ClauseExtractionResult,
    )

    drafting_agent = Agent(
        name="DraftingAgent",
        instructions=(
            "You propose clear plain-text contract redlines for risky clauses. "
            "Use the preferred_position and fallback_language. Keep suggestions concise and practical."
        ),
        output_type=DraftingSuggestion,
    )

    risk_agent = Agent(
        name="RiskAgent",
        instructions=(
            "Review ONE clause against the provided playbook rules. "
            "Return findings only when there is a meaningful mismatch with preferred_position. "
            "Use exact clause_id from the prompt and include a short excerpt <= 25 words. "
            "If RAG snippets are provided, incorporate useful context and include source file names in citations. "
            "If a finding needs edited language, call the propose_redline tool and use its output."
        ),
        output_type=ClauseRiskReview,
        tools=[
            drafting_agent.as_tool(
                tool_name="propose_redline",
                tool_description=(
                    "Propose replacement language for a risky clause based on the company playbook."
                ),
                parameters=DraftingInput,
            )
        ],
    )

    final_report_agent = Agent(
        name="FinalReportAgent",
        instructions=(
            "Build a final contract report JSON object with fields: "
            "doc_type, summary, overall_risk, findings, assumptions, missing_info_questions. "
            "Preserve findings exactly as provided unless they are malformed."
        ),
        output_type=Report,
        output_guardrails=[report_schema_guardrail],
    )

    io_agent = Agent(
        name="LawIOToolAgent",
        instructions="Use the required tool with the exact arguments from the user message.",
        tools=[load_playbook_tool, save_report_tool],
        tool_use_behavior="stop_on_first_tool",
    )

    return {
        "intake": intake_agent,
        "clause": clause_agent,
        "risk": risk_agent,
        "final": final_report_agent,
        "io": io_agent,
    }


class LawReviewManager:
    """Coordinates multi-agent legal review flow."""

    def __init__(
        self,
        *,
        playbook_path: str,
        out_dir: str,
        cache_path: str | None = None,
        reference_doc_paths: list[str] | None = None,
        use_tracing: bool = False,
    ) -> None:
        self.playbook_path = playbook_path
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.cache = ClauseRiskCache(cache_path)
        self.reference_rag = LawReferenceRAG(
            out_dir=self.out_dir,
            reference_doc_paths=reference_doc_paths,
        )
        self.last_clauses: list[Clause] = []
        self.use_tracing = use_tracing
        self.agents = _build_agents()

    async def review_document(self, document_text: str) -> tuple[Report, str, list[str]]:
        """Run the end-to-end contract review and return report + markdown + warnings."""
        return await self.review_document_with_progress(document_text)

    async def review_document_with_progress(
        self,
        document_text: str,
        progress_callback: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
    ) -> tuple[Report, str, list[str]]:
        """Run the review with optional progress events."""
        trace_context = (
            trace("Law Agent review", trace_id=gen_trace_id())
            if self.use_tracing
            else nullcontext()
        )
        with trace_context:
            context = ReviewContext()
            session = SQLiteSession(
                session_id="law-agent-review",
                db_path=self.out_dir / "law_agent_session.db",
            )

            await self._emit_progress(
                progress_callback,
                {"stage": "playbook", "message": "Loading playbook and initializing RAG index."},
            )
            playbook = await self._load_playbook_with_tool(session)
            playbook_text = format_playbook_for_prompt(playbook)
            rag_scope_id, rag_warnings = await self.reference_rag.ensure_index()
            if rag_warnings:
                context.warnings.extend(rag_warnings)

            await self._emit_progress(
                progress_callback,
                {"stage": "intake", "message": "Running IntakeAgent."},
            )
            try:
                intake_result = await Runner.run(
                    self.agents["intake"],
                    f"Contract text:\n\n{document_text}",
                    context=context,
                    session=session,
                )
            except InputGuardrailTripwireTriggered as exc:
                reason = exc.guardrail_result.output.output_info
                raise ValueError(f"Input rejected by guardrail: {reason}") from exc

            intake = intake_result.final_output_as(IntakeResult)
            await self._emit_progress(
                progress_callback,
                {"stage": "clause_extraction", "message": "Extracting contract clauses."},
            )
            clause_result = await self._extract_clauses(document_text, session)
            self.last_clauses = clause_result.clauses
            clause_ids = {clause.id for clause in clause_result.clauses}
            context.expected_clause_ids = clause_ids

            await self._emit_progress(
                progress_callback,
                {
                    "stage": "clause_extraction",
                    "message": f"Extracted {len(clause_result.clauses)} clauses.",
                    "total_clauses": len(clause_result.clauses),
                },
            )
            findings = await self._review_clause_risks(
                clauses=clause_result.clauses,
                playbook=playbook,
                playbook_text=playbook_text,
                cache_scope=rag_scope_id or "no-rag",
                session=session,
                progress_callback=progress_callback,
            )

            await self._emit_progress(
                progress_callback,
                {"stage": "final_report", "message": "Synthesizing final report."},
            )
            report = await self._build_final_report(
                intake=intake,
                findings=findings,
                context=context,
                session=session,
            )
            markdown = render_markdown_report(report)

            await self._save_outputs_with_tool(report, markdown, session)

            self.cache.persist()
            await self._emit_progress(
                progress_callback,
                {
                    "stage": "completed",
                    "message": "Review completed successfully.",
                    "findings_count": len(report.findings),
                },
            )
            return report, markdown, context.warnings

    async def _load_playbook_with_tool(self, session: SQLiteSession) -> Playbook:
        io_agent = self.agents["io"].clone(
            model_settings=ModelSettings(tool_choice="load_playbook_tool")
        )
        payload = json.dumps({"playbook_path": self.playbook_path})
        try:
            result = await Runner.run(
                io_agent,
                f"Load playbook using these args: {payload}",
                session=session,
            )
            return Playbook.model_validate(result.final_output)
        except Exception:
            return load_playbook(self.playbook_path)

    async def _extract_clauses(
        self,
        document_text: str,
        session: SQLiteSession,
    ) -> ClauseExtractionResult:
        prompt = (
            "Extract clauses from this contract and return ClauseExtractionResult JSON. "
            "Use stable ids CL-001, CL-002, ... in source order."
            f"\n\nContract:\n{document_text}"
        )
        try:
            result = await Runner.run(self.agents["clause"], prompt, session=session)
            extracted = result.final_output_as(ClauseExtractionResult)
        except Exception:
            return _fallback_clause_extraction(document_text)

        normalized = _normalize_clause_offsets(document_text, extracted.clauses)
        if not normalized:
            return _fallback_clause_extraction(document_text)
        return ClauseExtractionResult(clauses=normalized)

    async def _review_clause_risks(
        self,
        *,
        clauses: list[Clause],
        playbook: Playbook,
        playbook_text: str,
        cache_scope: str,
        session: SQLiteSession,
        progress_callback: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
    ) -> list[Finding]:
        findings: list[Finding] = []
        signature = playbook_signature(
            {
                "playbook": playbook.model_dump(mode="json"),
                "cache_scope": cache_scope,
            }
        )

        for index, clause in enumerate(clauses, start=1):
            await self._emit_progress(
                progress_callback,
                {
                    "stage": "risk_review",
                    "message": f"Reviewing {clause.id} ({index}/{len(clauses)}).",
                    "clause_id": clause.id,
                    "clause_heading": clause.heading,
                    "processed_clauses": index - 1,
                    "total_clauses": len(clauses),
                    "state": "processing",
                },
            )
            cache_key = ClauseRiskCache.make_key(
                clause_text=clause.text,
                playbook_signature=signature,
            )
            cached = self.cache.get(cache_key)
            if cached is not None:
                findings.extend(cached)
                await self._emit_progress(
                    progress_callback,
                    {
                        "stage": "risk_review",
                        "message": f"{clause.id} loaded from cache.",
                        "clause_id": clause.id,
                        "findings_for_clause": len(cached),
                        "processed_clauses": index,
                        "total_clauses": len(clauses),
                        "state": "cached",
                    },
                )
                continue

            snippets_text = "No reference snippets retrieved."
            citations: list[str] = []
            if self.reference_rag.enabled:
                try:
                    snippets = await self.reference_rag.retrieve_snippets(
                        clause_heading=clause.heading,
                        clause_text=clause.text,
                    )
                    snippets_text = self.reference_rag.format_for_prompt(snippets)
                    citations = sorted({snippet.source for snippet in snippets})
                except Exception:
                    snippets_text = "Reference retrieval unavailable for this clause."

            prompt = (
                "Review this clause against the playbook. "
                "Return zero findings if compliant."
                f"\n\nClause ID: {clause.id}"
                f"\nClause Heading: {clause.heading}"
                f"\nClause Text:\n{clause.text}"
                f"\n\nPlaybook:\n{playbook_text}"
                f"\n\nReference snippets (RAG):\n{snippets_text}"
            )
            result = await Runner.run(self.agents["risk"], prompt, session=session)
            review = result.final_output_as(ClauseRiskReview)
            normalized = [
                Finding(
                    clause_id=clause.id,
                    issue=item.issue,
                    severity=item.severity,
                    why=item.why,
                    excerpt=item.excerpt,
                    recommendation=item.recommendation,
                    suggested_redline=item.suggested_redline,
                    citations=item.citations or citations,
                )
                for item in review.findings
                if item.issue.strip() and item.excerpt.strip()
            ]
            self.cache.set(cache_key, normalized)
            findings.extend(normalized)
            await self._emit_progress(
                progress_callback,
                {
                    "stage": "risk_review",
                    "message": f"{clause.id} reviewed with {len(normalized)} findings.",
                    "clause_id": clause.id,
                    "findings_for_clause": len(normalized),
                    "processed_clauses": index,
                    "total_clauses": len(clauses),
                    "state": "completed",
                },
            )

        # Prefer highest-severity findings first.
        findings.sort(key=lambda item: _severity_rank(item.severity), reverse=True)
        return findings

    async def _emit_progress(
        self,
        callback: Callable[[dict[str, Any]], Awaitable[None] | None] | None,
        event: dict[str, Any],
    ) -> None:
        """Emit progress events to caller when provided."""
        if callback is None:
            return
        maybe_awaitable = callback(event)
        if maybe_awaitable is not None:
            await maybe_awaitable

    async def _build_final_report(
        self,
        *,
        intake: IntakeResult,
        findings: list[Finding],
        context: ReviewContext,
        session: SQLiteSession,
    ) -> Report:
        assumptions = list(intake.assumptions)
        if context.warnings:
            assumptions.extend(context.warnings)

        payload = {
            "doc_type": intake.doc_type,
            "intake_summary": intake.short_summary,
            "findings": [item.model_dump(mode="json") for item in findings],
            "assumptions": assumptions,
            "missing_info_questions": [
                "Are there any side letters or amendments not included in this text?",
                "Is this agreement intended to be mutual or one-way for confidentiality and indemnity obligations?",
            ],
        }
        prompt = (
            "Build the final report object. Use this payload as the source of truth:\n"
            f"{json.dumps(payload, indent=2)}"
        )

        try:
            result = await Runner.run(
                self.agents["final"],
                prompt,
                context=context,
                session=session,
            )
            return Report.model_validate(result.final_output)
        except OutputGuardrailTripwireTriggered as exc:
            fix_prompt = (
                f"{prompt}\n\n"
                "Fix to schema: your previous output failed validation. "
                f"Validation detail: {json.dumps(exc.guardrail_result.output.output_info)}"
            )
            result = await Runner.run(
                self.agents["final"],
                fix_prompt,
                context=context,
                session=session,
            )
            return Report.model_validate(result.final_output)

    async def _save_outputs_with_tool(
        self,
        report: Report,
        markdown: str,
        session: SQLiteSession,
    ) -> None:
        io_agent = self.agents["io"].clone(
            model_settings=ModelSettings(tool_choice="save_report_tool")
        )
        prompt = "Save outputs with this JSON payload:\n" + json.dumps(
            {
                "out_dir": str(self.out_dir),
                "report_json": report.model_dump_json(indent=2),
                "report_md": markdown,
            }
        )

        try:
            await Runner.run(io_agent, prompt, session=session)
        except Exception:
            save_report_json(self.out_dir / "report.json", report)
            save_report_markdown(self.out_dir / "report.md", markdown)
