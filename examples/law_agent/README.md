# Law Agent Example

This example builds a multi-agent contract reviewer for NDAs/MSAs. It ingests contract text, extracts clauses, reviews risks against a configurable playbook, proposes edits, and writes both JSON and Markdown reports.

## Setup

From the repository root:

```bash
make sync
```

If your environment does not already include PyYAML and you want to use `.yml` playbooks:

```bash
uv add pyyaml
```

For local PDF RAG ingestion:

```bash
uv add pypdf
```

For OCR fallback on scanned/image PDFs:

```bash
uv add pypdfium2 pytesseract
```

Also install the Tesseract OCR system binary (for example `brew install tesseract` on macOS).

Set your API key:

```bash
export OPENAI_API_KEY=<your_key>
```

## Run CLI

Using the bundled sample:

```bash
uv run python -m examples.law_agent.cli review \
  --input examples/law_agent/samples/sample_nda.txt \
  --playbook examples/law_agent/playbooks/default.yml \
  --reference-doc examples/law_agent/samples/sample_nda.txt \
  --reference-doc /absolute/path/to/precedent_nda.pdf \
  --out out/
```

You can also pass raw contract text directly to `--input`.

Outputs:

- `out/report.json`
- `out/report.md`

## Run Web Platform (React UI + Multi-tenant)

The web platform uses FastAPI backend + React frontend (served from `examples/law_agent/frontend`).

Install/add web dependencies if needed:

```bash
uv add fastapi uvicorn
```

Start:

```bash
uv run python -m examples.law_agent.web --host 127.0.0.1 --port 8001
```

Open:

```text
http://127.0.0.1:8001
```

Platform capabilities:

- Sign up and login (multi-tenant).
- Manage tenant playbook JSON rules.
- Upload reference docs (`.pdf`, `.txt`, `.md`, `.docx`) for local RAG.
- Rebuild local RAG index.
- Run contract review from pasted text or a direct contract file upload (`.pdf`, `.txt`, `.md`, `.docx`).
- While reviewing, a progress window shows agent stages and clause-by-clause processing updates.
- After completion, a document view highlights risky clauses and shows suggested redline text.
- Inspect local vector/chunk index view.

## Customize the playbook

Edit `examples/law_agent/playbooks/default.yml` or provide your own YAML/JSON file via `--playbook`.
Each rule supports:

- `name`
- `risk`
- `severity` (`low`, `med`, `high`)
- `check_guidance`
- `preferred_position`
- `fallback_language`

## Notes

- The example uses input/output guardrails and a retry-on-schema-failure path.
- A small optional JSON cache can be enabled with `--cache`.
- RAG is local. For web tenants, each tenant stores its own index under:
  `out/law_agent_platform/tenants/tenant_<id>/law_agent_local_rag_index.json`.
- Web platform state (users, tenants, sessions, docs metadata) is stored in:
  `out/law_agent_platform/law_agent_platform.db`.
- This output is not legal advice.
