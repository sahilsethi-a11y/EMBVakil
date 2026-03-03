"""Local reference-document RAG helpers for the Law Agent example."""

from __future__ import annotations

import hashlib
import json
import math
import re
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

from pydantic import BaseModel, Field

from .ocr import extract_pdf_text_with_ocr_fallback


class RagSnippet(BaseModel):
    """A retrieved precedent snippet."""

    source: str = Field(description="Source file name for the snippet.")
    quote: str = Field(description="Quoted snippet from the source.")
    relevance: str = Field(description="Why this snippet is relevant to the current clause.")


class RagSnippets(BaseModel):
    """Snippet bundle retrieved for a clause."""

    snippets: list[RagSnippet]


class _IndexedChunk(BaseModel):
    """A single indexed text chunk."""

    source: str
    chunk_id: str
    text: str
    tokens: list[str]


class _LocalRagIndex(BaseModel):
    """Persisted local index for reference docs."""

    fingerprint: str
    files: list[str]
    chunks: list[_IndexedChunk]


class LawReferenceRAG:
    """Ingest and retrieve from local reference docs without hosted vector stores."""

    def __init__(self, *, out_dir: str | Path, reference_doc_paths: list[str] | None) -> None:
        self._out_dir = Path(out_dir)
        self._index_path = self._out_dir / "law_agent_local_rag_index.json"
        self._reference_paths = [Path(path) for path in (reference_doc_paths or []) if path.strip()]
        self._index: _LocalRagIndex | None = None

    @property
    def enabled(self) -> bool:
        """Whether RAG has reference docs configured."""
        return bool(self._reference_paths)

    async def ensure_index(self) -> tuple[str | None, list[str]]:
        """Create or reuse a local chunk index for configured reference documents."""
        warnings: list[str] = []
        if not self.enabled:
            return None, warnings

        missing = [str(path) for path in self._reference_paths if not path.exists()]
        if missing:
            warnings.append(f"Skipping missing reference docs: {', '.join(missing)}")
            self._reference_paths = [path for path in self._reference_paths if path.exists()]

        if not self._reference_paths:
            return None, warnings

        fingerprint = self._compute_fingerprint(self._reference_paths)
        loaded = self._load_existing_index()
        if loaded and loaded.fingerprint == fingerprint:
            self._index = loaded
            return "local", warnings

        chunks: list[_IndexedChunk] = []
        for path in self._reference_paths:
            try:
                text = self._extract_text(path)
            except Exception as exc:
                warnings.append(f"Skipping {path}: {exc}")
                continue

            for chunk_num, chunk_text in enumerate(self._chunk_text(text), start=1):
                tokens = self._tokenize(chunk_text)
                if not tokens:
                    continue
                chunks.append(
                    _IndexedChunk(
                        source=path.name,
                        chunk_id=f"{path.name}:{chunk_num}",
                        text=chunk_text,
                        tokens=tokens,
                    )
                )

        if not chunks:
            warnings.append("No usable text chunks were extracted from reference docs.")
            self._index = None
            return None, warnings

        self._index = _LocalRagIndex(
            fingerprint=fingerprint,
            files=[str(path) for path in self._reference_paths],
            chunks=chunks,
        )
        self._save_index(self._index)
        return "local", warnings

    async def retrieve_snippets(self, clause_heading: str, clause_text: str) -> list[RagSnippet]:
        """Retrieve precedent snippets relevant to a clause using local lexical scoring."""
        if not self._index or not self._index.chunks:
            return []

        query_tokens = self._tokenize(f"{clause_heading}\n{clause_text}")
        if not query_tokens:
            return []

        ranked = self._rank_chunks(query_tokens)
        snippets: list[RagSnippet] = []
        for score, chunk in ranked[:3]:
            overlap_terms = sorted(set(query_tokens).intersection(chunk.tokens))[:6]
            snippets.append(
                RagSnippet(
                    source=chunk.source,
                    quote=self._compact_text(chunk.text, max_chars=220),
                    relevance=(
                        f"Lexical similarity score {score:.2f}; overlap terms: "
                        f"{', '.join(overlap_terms) if overlap_terms else 'n/a'}"
                    ),
                )
            )
        return snippets

    @staticmethod
    def format_for_prompt(snippets: list[RagSnippet]) -> str:
        """Render snippets for inclusion in model prompts."""
        if not snippets:
            return "No reference snippets retrieved."
        lines: list[str] = []
        for index, snippet in enumerate(snippets, start=1):
            lines.append(
                f"Snippet {index} | Source: {snippet.source}\n"
                f"Quote: {snippet.quote}\n"
                f"Relevance: {snippet.relevance}"
            )
        return "\n\n".join(lines)

    def _rank_chunks(self, query_tokens: list[str]) -> list[tuple[float, _IndexedChunk]]:
        """Rank chunks with a simple TF-IDF cosine-like score."""
        assert self._index is not None
        chunks = self._index.chunks
        total_docs = len(chunks)

        df: Counter[str] = Counter()
        for chunk in chunks:
            df.update(set(chunk.tokens))

        query_tf = Counter(query_tokens)
        query_weights = {
            term: self._idf(term, df.get(term, 0), total_docs) * float(freq)
            for term, freq in query_tf.items()
        }
        query_norm = math.sqrt(sum(weight * weight for weight in query_weights.values())) or 1.0

        scored: list[tuple[float, _IndexedChunk]] = []
        for chunk in chunks:
            chunk_tf = Counter(chunk.tokens)
            chunk_weights = {
                term: self._idf(term, df.get(term, 0), total_docs) * float(freq)
                for term, freq in chunk_tf.items()
            }
            chunk_norm = math.sqrt(sum(weight * weight for weight in chunk_weights.values())) or 1.0

            dot = 0.0
            for term, q_weight in query_weights.items():
                dot += q_weight * chunk_weights.get(term, 0.0)

            score = dot / (query_norm * chunk_norm)
            if score > 0.0:
                scored.append((score, chunk))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return scored

    @staticmethod
    def _idf(term: str, doc_freq: int, total_docs: int) -> float:
        """Inverse-document-frequency term weight."""
        del term
        return math.log((total_docs + 1) / (doc_freq + 1)) + 1.0

    @staticmethod
    def _extract_text(path: Path) -> str:
        """Extract text from supported local document formats."""
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            try:
                return extract_pdf_text_with_ocr_fallback(path.read_bytes())
            except RuntimeError as exc:
                raise RuntimeError(
                    f"PDF ingestion failed. {exc} For OCR install `uv add pypdfium2 pytesseract` "
                    "and the Tesseract binary."
                ) from exc

        if suffix == ".docx":
            try:
                with zipfile.ZipFile(path, "r") as archive:
                    xml_bytes = archive.read("word/document.xml")
            except Exception as exc:
                raise RuntimeError(f"Unable to parse DOCX file: {exc}") from exc

            try:
                root = ET.fromstring(xml_bytes)
            except ET.ParseError as exc:
                raise RuntimeError(f"DOCX XML parse failed: {exc}") from exc

            namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            paragraphs: list[str] = []
            for paragraph in root.findall(".//w:p", namespace):
                texts = [node.text or "" for node in paragraph.findall(".//w:t", namespace)]
                joined = "".join(texts).strip()
                if joined:
                    paragraphs.append(joined)
            return "\n\n".join(paragraphs)

        if suffix in {".txt", ".md"}:
            return path.read_text(encoding="utf-8")

        raise RuntimeError(f"Unsupported reference doc type: {path.suffix}")

    @staticmethod
    def _chunk_text(text: str, *, chunk_size: int = 900, overlap: int = 150) -> list[str]:
        """Chunk document text with overlap for retrieval continuity."""
        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized:
            return []

        chunks: list[str] = []
        start = 0
        text_len = len(normalized)
        while start < text_len:
            end = min(start + chunk_size, text_len)
            chunks.append(normalized[start:end].strip())
            if end >= text_len:
                break
            start = max(0, end - overlap)
        return [chunk for chunk in chunks if chunk]

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Tokenize for lexical retrieval scoring."""
        return re.findall(r"[a-z0-9]{2,}", text.lower())

    @staticmethod
    def _compact_text(text: str, *, max_chars: int) -> str:
        """Compact and clip chunk text for citations."""
        compact = re.sub(r"\s+", " ", text).strip()
        if len(compact) <= max_chars:
            return compact
        return compact[: max_chars - 1].rstrip() + "..."

    @staticmethod
    def _compute_fingerprint(paths: list[Path]) -> str:
        """Compute stable fingerprint of indexed reference docs."""
        pieces: list[str] = []
        for path in sorted(paths, key=lambda item: str(item)):
            stat = path.stat()
            pieces.append(f"{path}:{stat.st_size}:{int(stat.st_mtime)}")
        payload = "\n".join(pieces).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _load_existing_index(self) -> _LocalRagIndex | None:
        """Load index from disk if present and valid."""
        if not self._index_path.exists():
            return None
        try:
            raw = json.loads(self._index_path.read_text(encoding="utf-8"))
            return _LocalRagIndex.model_validate(raw)
        except Exception:
            return None

    def _save_index(self, index: _LocalRagIndex) -> None:
        """Persist local RAG index to disk."""
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        self._index_path.write_text(index.model_dump_json(indent=2), encoding="utf-8")
