"""FastAPI web platform for multi-tenant Law Agent usage."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import re
import secrets
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import uuid4
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agents import LawReviewManager
from .ocr import extract_pdf_text_with_ocr_diagnostics, extract_pdf_text_with_ocr_fallback
from .playbook import load_playbook
from .tenant_store import AuthSession, TenantStore

LAW_AGENT_DIR = Path(__file__).resolve().parent
DEFAULT_PLAYBOOK_PATH = LAW_AGENT_DIR / "playbooks" / "default.yml"
BASE_OUT_DIR = Path("out/law_agent_platform")
DB_PATH = BASE_OUT_DIR / "law_agent_platform.db"
UI_DIR = LAW_AGENT_DIR / "frontend"

app = FastAPI(title="EMB Vakil", version="0.2.0")
app.mount("/ui", StaticFiles(directory=str(UI_DIR)), name="ui")
store = TenantStore(DB_PATH)
REVIEW_JOBS: dict[str, dict[str, Any]] = {}


class SignupRequest(BaseModel):
    """Signup payload."""

    company: str
    email: str
    password: str


class LoginRequest(BaseModel):
    """Login payload."""

    email: str
    password: str


class PlaybookRequest(BaseModel):
    """Tenant playbook update payload."""

    playbook: dict[str, Any]


class UploadedDocument(BaseModel):
    """Base64-encoded uploaded document payload."""

    filename: str
    content_type: str = "application/octet-stream"
    base64_data: str


class RagUploadRequest(BaseModel):
    """Batch document upload payload."""

    documents: list[UploadedDocument] = Field(default_factory=list)


class ReviewRequest(BaseModel):
    """Review request payload."""

    contract_text: str = ""
    contract_filename: str = ""
    contract_content_type: str = "application/octet-stream"
    contract_base64_data: str = ""
    trace: bool = False


class ReviewStartResponse(BaseModel):
    """Review start response."""

    job_id: str


class ExportClause(BaseModel):
    """Editable clause payload for export."""

    id: str
    heading: str
    text: str
    comments: list[str] = Field(default_factory=list)


class ExportRequest(BaseModel):
    """Export payload for edited review output."""

    filename: str = "contract_review"
    format: Literal["docx", "pdf"]
    title: str = "Contract Review"
    clauses: list[ExportClause] = Field(default_factory=list)


def _tenant_root(tenant_id: int) -> Path:
    path = BASE_OUT_DIR / "tenants" / f"tenant_{tenant_id}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _tenant_playbook_path(tenant_id: int) -> Path:
    return _tenant_root(tenant_id) / "playbook.json"


def _tenant_docs_dir(tenant_id: int) -> Path:
    path = _tenant_root(tenant_id) / "docs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _tenant_runs_dir(tenant_id: int) -> Path:
    path = _tenant_root(tenant_id) / "runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _slug_export_filename(filename: str) -> str:
    stem = re.sub(r"[^a-zA-Z0-9._-]", "_", filename.strip())
    return stem or "contract_review"


def _write_review_result_file(
    *,
    run_dir: Path,
    result: dict[str, Any],
    input_name: str,
    run_id: str,
) -> None:
    """Persist enriched review output for history/detail APIs."""
    from datetime import UTC, datetime

    payload = {
        **result,
        "run_id": run_id,
        "input_name": input_name,
        "completed_at": datetime.now(UTC).isoformat(),
    }
    (run_dir / "review_result.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


def _load_review_result_file(run_dir: Path) -> dict[str, Any]:
    """Load enriched result, falling back to report files for older runs."""
    enriched = run_dir / "review_result.json"
    if enriched.exists():
        try:
            raw = json.loads(enriched.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
        except json.JSONDecodeError:
            pass

    report_json_path = run_dir / "report.json"
    report_md_path = run_dir / "report.md"
    report: dict[str, Any] = {}
    markdown = ""
    if report_json_path.exists():
        try:
            report = json.loads(report_json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            report = {}
    if report_md_path.exists():
        markdown = report_md_path.read_text(encoding="utf-8")

    return {
        "report": report,
        "markdown": markdown,
        "warnings": [],
        "clauses": [],
        "paths": {
            "report_json": str(report_json_path),
            "report_md": str(report_md_path),
            "run_dir": str(run_dir),
        },
        "run_id": run_dir.name,
        "input_name": "Unknown document",
        "completed_at": run_dir.name,
        "source_file_name": "",
        "source_file_path": "",
        "source_content_type": "",
    }


def _persist_review_source(
    *,
    run_dir: Path,
    contract_text: str,
    contract_filename: str,
    contract_content_type: str,
    contract_base64_data: str,
) -> tuple[str, str, str]:
    """Persist original review source and return (name, path, content_type)."""
    if contract_base64_data.strip():
        source_name = _slug_filename(contract_filename or "uploaded_contract.bin")
        source_path = run_dir / f"source_{source_name}"
        try:
            source_bytes = base64.b64decode(contract_base64_data)
        except Exception:
            source_bytes = b""
        source_path.write_bytes(source_bytes)
        return source_name, str(source_path), contract_content_type or "application/octet-stream"

    source_name = "pasted_contract.txt"
    source_path = run_dir / source_name
    source_path.write_text(contract_text, encoding="utf-8")
    return source_name, str(source_path), "text/plain"


def _build_docx_bytes(title: str, clauses: list[ExportClause]) -> bytes:
    """Create a minimal DOCX file with clause text and comments."""

    def para(text: str) -> str:
        safe = escape(text or "")
        return f'<w:p><w:r><w:t xml:space="preserve">{safe}</w:t></w:r></w:p>'

    lines = [title, ""]
    for clause in clauses:
        lines.append(f"{clause.id} - {clause.heading}")
        lines.append(clause.text)
        for comment in clause.comments:
            lines.append(f"Comment: {comment}")
        lines.append("")

    body = "".join(para(line) for line in lines)
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas" '
        'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
        'xmlns:o="urn:schemas-microsoft-com:office:office" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math" '
        'xmlns:v="urn:schemas-microsoft-com:vml" '
        'xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:w10="urn:schemas-microsoft-com:office:word" '
        'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
        'xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup" '
        'xmlns:wpi="http://schemas.microsoft.com/office/word/2010/wordprocessingInk" '
        'xmlns:wne="http://schemas.microsoft.com/office/word/2006/wordml" '
        'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
        'mc:Ignorable="w14 wp14">'
        f"<w:body>{body}<w:sectPr/></w:body></w:document>"
    )
    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        "</Relationships>"
    )

    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml)
        archive.writestr("_rels/.rels", rels_xml)
        archive.writestr("word/document.xml", document_xml)
    return output.getvalue()


def _build_pdf_bytes(title: str, clauses: list[ExportClause]) -> bytes:
    """Create a simple multi-page PDF for edited clauses."""

    def _escape_pdf_text(text: str) -> str:
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    lines: list[str] = [title, ""]
    for clause in clauses:
        lines.append(f"{clause.id} - {clause.heading}")
        lines.extend((clause.text or "").splitlines() or [""])
        for comment in clause.comments:
            lines.append(f"Comment: {comment}")
        lines.append("")

    page_height = 792
    top = 760
    line_gap = 14
    max_lines = 50
    chunks = [lines[i : i + max_lines] for i in range(0, len(lines), max_lines)] or [[]]

    objects: list[bytes] = []
    pages_refs: list[int] = []
    font_id = 3

    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [] /Count 0 >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    for chunk in chunks:
        content_lines = ["BT", "/F1 11 Tf"]
        y = top
        for line in chunk:
            text = _escape_pdf_text(line[:1500])
            content_lines.append(f"1 0 0 1 40 {y} Tm ({text}) Tj")
            y -= line_gap
        content_lines.append("ET")
        stream = "\n".join(content_lines).encode("latin-1", errors="ignore")
        content_obj = len(objects) + 1
        objects.append(
            f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream + b"\nendstream"
        )
        page_obj = len(objects) + 1
        pages_refs.append(page_obj)
        objects.append(
            (
                "<< /Type /Page /Parent 2 0 R "
                f"/MediaBox [0 0 612 {page_height}] "
                f"/Contents {content_obj} 0 R "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>"
            ).encode("latin-1")
        )

    kids = " ".join(f"{ref} 0 R" for ref in pages_refs)
    objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(pages_refs)} >>".encode("latin-1")

    pdf = BytesIO()
    pdf.write(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(pdf.tell())
        pdf.write(f"{index} 0 obj\n".encode("latin-1"))
        pdf.write(body)
        pdf.write(b"\nendobj\n")
    xref_pos = pdf.tell()
    pdf.write(f"xref\n0 {len(objects) + 1}\n".encode("latin-1"))
    pdf.write(b"0000000000 65535 f \n")
    for pos in offsets[1:]:
        pdf.write(f"{pos:010d} 00000 n \n".encode("latin-1"))
    pdf.write(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF"
        ).encode("latin-1")
    )
    return pdf.getvalue()


def _slug_filename(filename: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]", "_", filename.strip())
    return cleaned or "upload.bin"


def _default_playbook_json() -> str:
    playbook = load_playbook(DEFAULT_PLAYBOOK_PATH)
    return playbook.model_dump_json(indent=2)


def _ensure_tenant_playbook(tenant_id: int) -> Path:
    target = _tenant_playbook_path(tenant_id)
    if target.exists():
        return target

    playbook_json = store.get_playbook_json(tenant_id=tenant_id) or _default_playbook_json()
    target.write_text(playbook_json, encoding="utf-8")
    return target


def _extract_contract_text_from_upload(
    *,
    filename: str,
    content_type: str,
    base64_data: str,
) -> str:
    """Decode and extract contract text from uploaded review file payload."""
    del content_type
    cleaned_name = _slug_filename(filename)
    suffix = Path(cleaned_name).suffix.lower()
    if not base64_data.strip():
        raise ValueError("Uploaded file content is empty.")

    try:
        file_bytes = base64.b64decode(base64_data)
    except Exception as exc:
        raise ValueError(f"Invalid file payload: {exc}") from exc

    if suffix in {".txt", ".md"}:
        try:
            return file_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"Could not decode text file as UTF-8: {exc}") from exc

    if suffix == ".pdf":
        try:
            return extract_pdf_text_with_ocr_fallback(file_bytes)
        except RuntimeError as exc:
            raise ValueError(str(exc)) from exc

    if suffix == ".docx":
        try:
            with zipfile.ZipFile(BytesIO(file_bytes), "r") as archive:
                xml_bytes = archive.read("word/document.xml")
        except Exception as exc:
            raise ValueError(f"Unable to parse DOCX file: {exc}") from exc

        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError as exc:
            raise ValueError(f"DOCX XML parse failed: {exc}") from exc

        namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paragraphs: list[str] = []
        for paragraph in root.findall(".//w:p", namespace):
            texts = [node.text or "" for node in paragraph.findall(".//w:t", namespace)]
            joined = "".join(texts).strip()
            if joined:
                paragraphs.append(joined)
        return "\n\n".join(paragraphs)

    raise ValueError(f"Unsupported review file type: {suffix or 'unknown'}")


def _extract_contract_text_from_upload_details(
    *,
    filename: str,
    content_type: str,
    base64_data: str,
) -> tuple[str, bool]:
    """Extract contract text and return whether OCR fallback was used."""
    del content_type
    cleaned_name = _slug_filename(filename)
    suffix = Path(cleaned_name).suffix.lower()
    if not base64_data.strip():
        raise ValueError("Uploaded file content is empty.")

    try:
        file_bytes = base64.b64decode(base64_data)
    except Exception as exc:
        raise ValueError(f"Invalid file payload: {exc}") from exc

    if suffix in {".txt", ".md"}:
        try:
            return file_bytes.decode("utf-8"), False
        except UnicodeDecodeError as exc:
            raise ValueError(f"Could not decode text file as UTF-8: {exc}") from exc

    if suffix == ".pdf":
        try:
            return extract_pdf_text_with_ocr_diagnostics(file_bytes)
        except RuntimeError as exc:
            raise ValueError(str(exc)) from exc

    if suffix == ".docx":
        try:
            with zipfile.ZipFile(BytesIO(file_bytes), "r") as archive:
                xml_bytes = archive.read("word/document.xml")
        except Exception as exc:
            raise ValueError(f"Unable to parse DOCX file: {exc}") from exc

        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError as exc:
            raise ValueError(f"DOCX XML parse failed: {exc}") from exc

        namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paragraphs: list[str] = []
        for paragraph in root.findall(".//w:p", namespace):
            texts = [node.text or "" for node in paragraph.findall(".//w:t", namespace)]
            joined = "".join(texts).strip()
            if joined:
                paragraphs.append(joined)
        return "\n\n".join(paragraphs), False

    raise ValueError(f"Unsupported review file type: {suffix or 'unknown'}")


def _extract_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header.")
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authorization must be a Bearer token.")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token.")
    return token


def _get_auth_session(authorization: str | None = Header(default=None)) -> AuthSession:
    token = _extract_token(authorization)
    try:
        return store.resolve_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


SessionDep = Annotated[AuthSession, Depends(_get_auth_session)]


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(UI_DIR / "index.html")


@app.post("/api/auth/signup")
async def signup(payload: SignupRequest) -> dict[str, Any]:
    try:
        session = store.signup(
            company=payload.company,
            email=payload.email,
            password=payload.password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _ensure_tenant_playbook(session.tenant_id)
    return {
        "token": session.token,
        "email": session.email,
        "tenant_id": session.tenant_id,
        "tenant_name": session.tenant_name,
    }


@app.post("/api/auth/login")
async def login(payload: LoginRequest) -> dict[str, Any]:
    try:
        session = store.login(email=payload.email, password=payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    _ensure_tenant_playbook(session.tenant_id)
    return {
        "token": session.token,
        "email": session.email,
        "tenant_id": session.tenant_id,
        "tenant_name": session.tenant_name,
    }


@app.get("/api/me")
async def me(auth: SessionDep) -> dict[str, Any]:
    return {
        "email": auth.email,
        "tenant_id": auth.tenant_id,
        "tenant_name": auth.tenant_name,
    }


@app.get("/api/playbook")
async def get_playbook(auth: SessionDep) -> dict[str, Any]:
    path = _ensure_tenant_playbook(auth.tenant_id)
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500, detail=f"Stored playbook is invalid JSON: {exc}"
        ) from exc
    return {"playbook": parsed}


@app.put("/api/playbook")
async def put_playbook(
    payload: PlaybookRequest,
    auth: SessionDep,
) -> dict[str, Any]:
    try:
        # Validate shape through existing playbook loader path by writing temp JSON.
        candidate = json.dumps(payload.playbook)
        temp_path = _tenant_root(auth.tenant_id) / f"_playbook_check_{secrets.token_hex(8)}.json"
        temp_path.write_text(candidate, encoding="utf-8")
        load_playbook(temp_path)
        temp_path.unlink(missing_ok=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid playbook format: {exc}") from exc

    playbook_json = json.dumps(payload.playbook, indent=2)
    store.upsert_playbook_json(tenant_id=auth.tenant_id, playbook_json=playbook_json)
    path = _tenant_playbook_path(auth.tenant_id)
    path.write_text(playbook_json, encoding="utf-8")
    return {"ok": True, "path": str(path)}


@app.post("/api/rag/documents")
async def upload_documents(
    payload: RagUploadRequest,
    auth: SessionDep,
) -> dict[str, Any]:
    docs_dir = _tenant_docs_dir(auth.tenant_id)
    saved: list[dict[str, Any]] = []

    for item in payload.documents:
        filename = _slug_filename(item.filename)
        if not item.base64_data.strip():
            continue
        try:
            content = base64.b64decode(item.base64_data)
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"Invalid base64 for {filename}: {exc}"
            ) from exc

        unique_name = f"{secrets.token_hex(6)}_{filename}"
        path = docs_dir / unique_name
        path.write_bytes(content)
        doc_id = store.add_document(
            tenant_id=auth.tenant_id,
            filename=filename,
            saved_path=str(path),
            content_type=item.content_type,
        )
        saved.append({"id": doc_id, "filename": filename, "saved_path": str(path)})

    return {"saved": saved, "count": len(saved)}


@app.get("/api/rag/documents")
async def list_documents(auth: SessionDep) -> dict[str, Any]:
    return {"documents": store.list_documents(tenant_id=auth.tenant_id)}


@app.post("/api/rag/reindex")
async def reindex(auth: SessionDep) -> dict[str, Any]:
    playbook_path = _ensure_tenant_playbook(auth.tenant_id)
    run_dir = _tenant_root(auth.tenant_id)
    rag_paths = store.list_document_paths(tenant_id=auth.tenant_id)
    manager = LawReviewManager(
        playbook_path=str(playbook_path),
        out_dir=str(run_dir),
        reference_doc_paths=rag_paths,
        use_tracing=False,
    )
    scope, warnings = await manager.reference_rag.ensure_index()
    return {"scope": scope, "warnings": warnings}


@app.get("/api/rag/index")
async def rag_index(auth: SessionDep) -> dict[str, Any]:
    index_path = _tenant_root(auth.tenant_id) / "law_agent_local_rag_index.json"
    if not index_path.exists():
        return {"chunk_count": 0, "files": [], "chunks": []}

    try:
        raw = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"Invalid index JSON: {exc}") from exc

    chunks = raw.get("chunks", []) if isinstance(raw, dict) else []
    rows = []
    for chunk in chunks[:250]:
        if not isinstance(chunk, dict):
            continue
        text = str(chunk.get("text", ""))
        rows.append(
            {
                "chunk_id": str(chunk.get("chunk_id", "")),
                "source": str(chunk.get("source", "")),
                "token_count": len(chunk.get("tokens", []))
                if isinstance(chunk.get("tokens"), list)
                else 0,
                "preview": (text[:160] + "...") if len(text) > 160 else text,
            }
        )

    return {
        "chunk_count": len(chunks),
        "files": raw.get("files", []) if isinstance(raw, dict) else [],
        "chunks": rows,
    }


@app.post("/api/review")
async def review_contract(
    payload: ReviewRequest,
    auth: SessionDep,
) -> dict[str, Any]:
    contract_text = payload.contract_text.strip()
    used_uploaded_file = False
    if not contract_text and payload.contract_base64_data.strip():
        used_uploaded_file = True
        try:
            contract_text = _extract_contract_text_from_upload(
                filename=payload.contract_filename,
                content_type=payload.contract_content_type,
                base64_data=payload.contract_base64_data,
            ).strip()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if len(contract_text) < 80:
        if used_uploaded_file:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Could not extract enough text from the uploaded file. "
                    "If this is a scanned/image PDF, OCR is required. "
                    "Try a text-based PDF/DOCX/TXT, or paste the contract text directly."
                ),
            )
        raise HTTPException(
            status_code=400,
            detail="Contract text must be at least 80 characters.",
        )

    playbook_path = _ensure_tenant_playbook(auth.tenant_id)
    run_id = datetime_run_id()
    run_dir = _tenant_runs_dir(auth.tenant_id) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    source_name, source_path, source_content_type = _persist_review_source(
        run_dir=run_dir,
        contract_text=contract_text,
        contract_filename=payload.contract_filename,
        contract_content_type=payload.contract_content_type,
        contract_base64_data=payload.contract_base64_data,
    )

    manager = LawReviewManager(
        playbook_path=str(playbook_path),
        out_dir=str(run_dir),
        cache_path=str(_tenant_root(auth.tenant_id) / "risk_cache.json"),
        reference_doc_paths=store.list_document_paths(tenant_id=auth.tenant_id),
        use_tracing=payload.trace,
    )

    try:
        report, markdown, warnings = await manager.review_document(contract_text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Review failed: {exc}") from exc

    result_payload = {
        "report": report.model_dump(mode="json"),
        "markdown": markdown,
        "warnings": warnings,
        "clauses": [clause.model_dump(mode="json") for clause in manager.last_clauses],
        "paths": {
            "report_json": str(run_dir / "report.json"),
            "report_md": str(run_dir / "report.md"),
            "run_dir": str(run_dir),
        },
        "run_id": run_id,
        "input_name": payload.contract_filename or "Pasted contract text",
        "source_file_name": source_name,
        "source_file_path": source_path,
        "source_content_type": source_content_type,
    }
    _write_review_result_file(
        run_dir=run_dir,
        result=result_payload,
        input_name=payload.contract_filename or "Pasted contract text",
        run_id=run_id,
    )
    return result_payload


@app.post("/api/review/start")
async def start_review_contract(
    payload: ReviewRequest,
    auth: SessionDep,
) -> ReviewStartResponse:
    if not payload.contract_text.strip() and not payload.contract_base64_data.strip():
        raise HTTPException(
            status_code=400,
            detail="Paste contract text or upload a review file before starting.",
        )

    job_id = uuid4().hex
    REVIEW_JOBS[job_id] = {
        "tenant_id": auth.tenant_id,
        "status": "queued",
        "progress_events": [],
        "result": None,
        "error": None,
    }

    async def _run_job() -> None:
        playbook_path = _ensure_tenant_playbook(auth.tenant_id)
        run_id = datetime_run_id()
        run_dir = _tenant_runs_dir(auth.tenant_id) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        manager = LawReviewManager(
            playbook_path=str(playbook_path),
            out_dir=str(run_dir),
            cache_path=str(_tenant_root(auth.tenant_id) / "risk_cache.json"),
            reference_doc_paths=store.list_document_paths(tenant_id=auth.tenant_id),
            use_tracing=payload.trace,
        )

        async def on_progress(event: dict[str, Any]) -> None:
            state = REVIEW_JOBS.get(job_id)
            if state is None:
                return
            state["progress_events"].append(event)
            # Keep memory bounded.
            if len(state["progress_events"]) > 300:
                state["progress_events"] = state["progress_events"][-300:]

        try:
            REVIEW_JOBS[job_id]["status"] = "running"
            contract_text = payload.contract_text.strip()
            used_uploaded_file = False
            used_ocr = False
            if not contract_text and payload.contract_base64_data.strip():
                used_uploaded_file = True
                await on_progress(
                    {
                        "stage": "input_parse",
                        "message": "Reading uploaded contract file.",
                    }
                )
                contract_text, used_ocr = _extract_contract_text_from_upload_details(
                    filename=payload.contract_filename,
                    content_type=payload.contract_content_type,
                    base64_data=payload.contract_base64_data,
                )
                contract_text = contract_text.strip()
                await on_progress(
                    {
                        "stage": "input_parse",
                        "message": (
                            f"Extracted {len(contract_text)} characters from uploaded contract."
                        ),
                    }
                )
                if used_ocr:
                    await on_progress(
                        {
                            "stage": "ocr",
                            "message": "OCR fallback engaged for scanned/image PDF.",
                        }
                    )

            if len(contract_text) < 80:
                if used_uploaded_file:
                    raise ValueError(
                        "Could not extract enough text from the uploaded file. "
                        "If this is a scanned/image PDF, OCR is required. "
                        "Try a text-based PDF/DOCX/TXT, or paste the contract text directly."
                    )
                raise ValueError("Contract text must be at least 80 characters.")

            source_name, source_path, source_content_type = _persist_review_source(
                run_dir=run_dir,
                contract_text=contract_text,
                contract_filename=payload.contract_filename,
                contract_content_type=payload.contract_content_type,
                contract_base64_data=payload.contract_base64_data,
            )

            report, markdown, warnings = await manager.review_document_with_progress(
                contract_text,
                progress_callback=on_progress,
            )
            REVIEW_JOBS[job_id]["status"] = "completed"
            result_payload = {
                "report": report.model_dump(mode="json"),
                "markdown": markdown,
                "warnings": warnings,
                "clauses": [clause.model_dump(mode="json") for clause in manager.last_clauses],
                "paths": {
                    "report_json": str(run_dir / "report.json"),
                    "report_md": str(run_dir / "report.md"),
                    "run_dir": str(run_dir),
                },
                "run_id": run_id,
                "input_name": payload.contract_filename or "Pasted contract text",
                "source_file_name": source_name,
                "source_file_path": source_path,
                "source_content_type": source_content_type,
            }
            _write_review_result_file(
                run_dir=run_dir,
                result=result_payload,
                input_name=payload.contract_filename or "Pasted contract text",
                run_id=run_id,
            )
            REVIEW_JOBS[job_id]["result"] = result_payload
        except Exception as exc:
            REVIEW_JOBS[job_id]["status"] = "failed"
            REVIEW_JOBS[job_id]["error"] = str(exc)

    asyncio.create_task(_run_job())
    return ReviewStartResponse(job_id=job_id)


@app.get("/api/review/status/{job_id}")
async def get_review_status(job_id: str, auth: SessionDep) -> dict[str, Any]:
    state = REVIEW_JOBS.get(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Review job not found.")
    if state.get("tenant_id") != auth.tenant_id:
        raise HTTPException(status_code=403, detail="Forbidden for this tenant.")
    return state


@app.get("/api/review/history")
async def list_review_history(auth: SessionDep) -> dict[str, Any]:
    """Return completed review runs for tenant."""
    runs_dir = _tenant_runs_dir(auth.tenant_id)
    items: list[dict[str, Any]] = []
    for run_dir in sorted([path for path in runs_dir.iterdir() if path.is_dir()], reverse=True):
        result = _load_review_result_file(run_dir)
        report = result.get("report", {}) if isinstance(result, dict) else {}
        findings = report.get("findings", []) if isinstance(report, dict) else []
        citations = sorted(
            {
                citation
                for finding in findings
                if isinstance(finding, dict)
                for citation in (finding.get("citations") or [])
                if isinstance(citation, str) and citation.strip()
            }
        )
        items.append(
            {
                "run_id": str(result.get("run_id") or run_dir.name),
                "input_name": str(result.get("input_name") or "Unknown document"),
                "completed_at": str(result.get("completed_at") or run_dir.name),
                "overall_risk": str(report.get("overall_risk") or "unknown"),
                "findings_count": len(findings) if isinstance(findings, list) else 0,
                "docs_checked": citations,
                "source_content_type": str(result.get("source_content_type") or ""),
            }
        )
    return {"history": items}


@app.get("/api/review/history/{run_id}")
async def get_review_history_item(run_id: str, auth: SessionDep) -> dict[str, Any]:
    """Return one review result by run id."""
    run_dir = _tenant_runs_dir(auth.tenant_id) / run_id
    if not run_dir.exists() or not run_dir.is_dir():
        raise HTTPException(status_code=404, detail="Review run not found.")
    return _load_review_result_file(run_dir)


@app.get("/api/review/history/{run_id}/source")
async def get_review_history_source(run_id: str, auth: SessionDep) -> FileResponse:
    """Return original uploaded source file for a review run."""
    run_dir = _tenant_runs_dir(auth.tenant_id) / run_id
    if not run_dir.exists() or not run_dir.is_dir():
        raise HTTPException(status_code=404, detail="Review run not found.")

    result = _load_review_result_file(run_dir)
    source_path_raw = str(result.get("source_file_path") or "")
    source_name = str(result.get("source_file_name") or "source.bin")
    content_type = str(result.get("source_content_type") or "application/octet-stream")
    if not source_path_raw:
        raise HTTPException(status_code=404, detail="Source file is not available for this run.")

    source_path = Path(source_path_raw).resolve()
    run_root = run_dir.resolve()
    if run_root not in source_path.parents and source_path != run_root:
        raise HTTPException(status_code=403, detail="Invalid source file path.")
    if not source_path.exists():
        raise HTTPException(status_code=404, detail="Source file not found.")
    return FileResponse(path=source_path, filename=source_name, media_type=content_type)


@app.post("/api/review/export")
async def export_review(payload: ExportRequest, auth: SessionDep) -> Response:
    """Export edited review document to DOCX or PDF."""
    del auth
    safe_name = _slug_export_filename(payload.filename)
    if payload.format == "docx":
        body = _build_docx_bytes(payload.title, payload.clauses)
        filename = f"{safe_name}.docx"
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        body = _build_pdf_bytes(payload.title, payload.clauses)
        filename = f"{safe_name}.pdf"
        media_type = "application/pdf"

    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def datetime_run_id() -> str:
    """Generate a stable review run id for output directories."""
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def main() -> None:
    """Run the web platform server."""
    parser = argparse.ArgumentParser(description="EMB Vakil web platform")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()

    import uvicorn

    uvicorn.run("examples.law_agent.web:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
