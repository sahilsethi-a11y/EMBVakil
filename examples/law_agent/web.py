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
from typing import Annotated, Any
from uuid import uuid4
from xml.etree import ElementTree as ET

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
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

    return {
        "report": report.model_dump(mode="json"),
        "markdown": markdown,
        "warnings": warnings,
        "clauses": [clause.model_dump(mode="json") for clause in manager.last_clauses],
        "paths": {
            "report_json": str(run_dir / "report.json"),
            "report_md": str(run_dir / "report.md"),
            "run_dir": str(run_dir),
        },
    }


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

            report, markdown, warnings = await manager.review_document_with_progress(
                contract_text,
                progress_callback=on_progress,
            )
            REVIEW_JOBS[job_id]["status"] = "completed"
            REVIEW_JOBS[job_id]["result"] = {
                "report": report.model_dump(mode="json"),
                "markdown": markdown,
                "warnings": warnings,
                "clauses": [clause.model_dump(mode="json") for clause in manager.last_clauses],
                "paths": {
                    "report_json": str(run_dir / "report.json"),
                    "report_md": str(run_dir / "report.md"),
                    "run_dir": str(run_dir),
                },
            }
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
