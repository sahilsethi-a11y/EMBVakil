"""CLI for the Law Agent example."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .agents import LawReviewManager


def _load_input(input_value: str) -> str:
    maybe_path = Path(input_value)
    if maybe_path.exists() and maybe_path.is_file():
        return maybe_path.read_text(encoding="utf-8")
    return input_value


async def _run_review(args: argparse.Namespace) -> None:
    input_text = _load_input(args.input)
    reference_docs = args.reference_doc or []
    manager = LawReviewManager(
        playbook_path=args.playbook,
        out_dir=args.out,
        cache_path=args.cache,
        reference_doc_paths=reference_docs,
        use_tracing=args.trace,
    )
    report, _markdown, warnings = await manager.review_document(input_text)

    print(f"Review complete. Findings: {len(report.findings)}")
    print(f"Overall risk: {report.overall_risk}")
    print(f"JSON report: {Path(args.out) / 'report.json'}")
    print(f"Markdown report: {Path(args.out) / 'report.md'}")
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"- {warning}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Law Agent example CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    review = subparsers.add_parser("review", help="Review a contract or NDA")
    review.add_argument(
        "--input",
        required=True,
        help="Contract text or path to a .txt file.",
    )
    review.add_argument(
        "--playbook",
        default="examples/law_agent/playbooks/default.yml",
        help="Path to YAML/JSON playbook.",
    )
    review.add_argument(
        "--out",
        default="out",
        help="Output directory for report files.",
    )
    review.add_argument(
        "--cache",
        default=None,
        help="Optional JSON file path for clause-risk cache.",
    )
    review.add_argument(
        "--trace",
        action="store_true",
        help="Enable trace capture for this review run.",
    )
    review.add_argument(
        "--reference-doc",
        action="append",
        default=[],
        help=(
            "Optional path to a reference document for RAG (repeat flag for multiple docs). "
            "Supports .pdf, .txt, .md."
        ),
    )
    review.set_defaults(func=_run_review)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
