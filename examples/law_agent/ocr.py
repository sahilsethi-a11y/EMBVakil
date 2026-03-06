"""OCR utilities for PDF text extraction in the Law Agent example."""

from __future__ import annotations

from io import BytesIO

OCR_FALLBACK_MIN_CHARS = 2000


def extract_pdf_text_with_ocr_fallback(
    pdf_bytes: bytes, *, min_chars: int = OCR_FALLBACK_MIN_CHARS
) -> str:
    """Extract text from PDF bytes, falling back to OCR for scanned pages.

    The fallback uses optional dependencies:
    - `pypdfium2` for PDF page rendering
    - `pytesseract` for OCR

    `pytesseract` also requires the Tesseract binary to be installed on the system.
    """
    merged, _used_ocr = extract_pdf_text_with_ocr_diagnostics(pdf_bytes, min_chars=min_chars)
    return merged


def extract_pdf_text_with_ocr_diagnostics(
    pdf_bytes: bytes, *, min_chars: int = OCR_FALLBACK_MIN_CHARS
) -> tuple[str, bool]:
    """Extract text and return whether OCR fallback was used."""
    base_text = _extract_pdf_text_basic(pdf_bytes)
    if len(base_text.strip()) >= min_chars:
        return base_text, False

    ocr_text = _extract_pdf_text_ocr(pdf_bytes)
    merged = "\n\n".join(part for part in [base_text.strip(), ocr_text.strip()] if part)
    return merged, True


def _extract_pdf_text_basic(pdf_bytes: bytes) -> str:
    """Extract text from PDF using direct text-layer parsing."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency/env specific
        raise RuntimeError("PDF parsing requires pypdf (`uv add pypdf`).") from exc

    reader = PdfReader(BytesIO(pdf_bytes))
    pages = [(page.extract_text() or "") for page in reader.pages]
    return "\n\n".join(pages)


def _extract_pdf_text_ocr(pdf_bytes: bytes) -> str:
    """OCR PDF pages when text-layer extraction is insufficient."""
    try:
        import pypdfium2 as pdfium  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - dependency/env specific
        raise RuntimeError("OCR fallback requires pypdfium2 (`uv add pypdfium2`).") from exc

    try:
        import pytesseract  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - dependency/env specific
        raise RuntimeError("OCR fallback requires pytesseract (`uv add pytesseract`).") from exc

    doc = pdfium.PdfDocument(pdf_bytes)
    page_texts: list[str] = []

    for index in range(len(doc)):
        page = doc[index]
        # ~200 DPI equivalent for better OCR reliability.
        bitmap = page.render(scale=200 / 72)
        image = bitmap.to_pil()
        text = pytesseract.image_to_string(image).strip()
        if text:
            page_texts.append(text)

    return "\n\n".join(page_texts)
