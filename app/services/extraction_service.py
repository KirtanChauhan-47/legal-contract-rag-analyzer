"""Raw text extraction from uploaded files. Deliberately dumb: no cleaning,
no chunking, no judgment about whether the text is a contract — that's
Sprint 3's contract_gate_service / cleaning_service / chunking_service.
"""
import fitz  # PyMuPDF
import docx


class ExtractionError(Exception):
    """Raised for any extraction failure. Callers must catch this and set
    Document.status = FAILED + error_message rather than letting it surface
    as a raw 500."""


def extract_text(file_path: str, file_type: str) -> tuple[str, int | None]:
    """Returns (extracted_text, page_count). page_count is None for formats
    without a native page concept (docx, txt)."""
    try:
        if file_type == "pdf":
            return _extract_pdf(file_path)
        if file_type == "docx":
            return _extract_docx(file_path)
        if file_type == "txt":
            return _extract_txt(file_path)
        raise ExtractionError(f"No extractor available for file type '{file_type}'.")
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError(f"Failed to extract text: {exc}") from exc


def _extract_pdf(file_path: str) -> tuple[str, int]:
    document = fitz.open(file_path)
    try:
        pages = [page.get_text() for page in document]
    finally:
        document.close()

    # Page-break marker preserved so future page-level citations are possible.
    text = "\n\n[PAGE_BREAK]\n\n".join(pages)
    if not text.strip():
        raise ExtractionError(
            "No extractable text found in the PDF (it may be scanned/image-only)."
        )
    return text, len(pages)


def _extract_docx(file_path: str) -> tuple[str, None]:
    document = docx.Document(file_path)
    paragraphs = [p.text for p in document.paragraphs]
    text = "\n".join(paragraphs)
    if not text.strip():
        raise ExtractionError("No extractable text found in the DOCX file.")
    return text, None


def _extract_txt(file_path: str) -> tuple[str, None]:
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    if not text.strip():
        raise ExtractionError("Text file is empty.")
    return text, None
