from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import re

import fitz
from docx import Document as WordDocument

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".md", ".txt"}


@dataclass(frozen=True)
class ExtractedPage:
    page_number: int | None
    text: str


def extract_text(
    filename: str, content: bytes, enable_ocr: bool = False
) -> list[ExtractedPage]:
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError(
            "Unsupported file type. Upload a PDF, DOCX, Markdown, or TXT file."
        )
    if extension == ".pdf":
        try:
            with fitz.open(stream=content, filetype="pdf") as pdf:
                pages = []
                for index, page in enumerate(pdf):
                    text = page.get_text().strip()
                    if not text and enable_ocr:
                        try:
                            text_page = page.get_textpage_ocr(
                                language="eng", dpi=150, full=True
                            )
                            text = page.get_text("text", textpage=text_page).strip()
                        except Exception as exc:
                            raise ValueError(
                                "OCR could not read this scanned PDF. Check that Tesseract OCR and English language data are installed."
                            ) from exc
                    pages.append(ExtractedPage(index + 1, text))
        except Exception as exc:
            if isinstance(exc, ValueError):
                raise
            raise ValueError(
                "Could not read this PDF. It may be damaged or encrypted."
            ) from exc
        return [page for page in pages if page.text]
    if extension == ".docx":
        try:
            document = WordDocument(BytesIO(content))
            paragraphs = [
                paragraph.text.strip()
                for paragraph in document.paragraphs
                if paragraph.text.strip()
            ]
            tables = [
                " | ".join(cell.text.strip() for cell in row.cells)
                for table in document.tables
                for row in table.rows
            ]
            text = "\n".join(paragraphs + tables).strip()
        except Exception as exc:
            raise ValueError(
                "Could not read this Word document. It may be damaged or password protected."
            ) from exc
        return [ExtractedPage(None, text)] if text else []
    text = content.decode("utf-8-sig", errors="replace").strip()
    return [ExtractedPage(None, text)] if text else []


def split_text(text: str, chunk_size: int = 1100, overlap: int = 160) -> list[str]:
    """Split text near paragraph/sentence boundaries with bounded overlap."""
    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be non-negative and smaller than chunk_size")
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + chunk_size, len(normalized))
        if end < len(normalized):
            boundary = max(
                normalized.rfind(". ", start, end),
                normalized.rfind("? ", start, end),
                normalized.rfind("! ", start, end),
                normalized.rfind("; ", start, end),
            )
            if boundary > start + chunk_size // 2:
                end = boundary + 1
        value = normalized[start:end].strip()
        if value:
            chunks.append(value)
        if end == len(normalized):
            break
        start = max(start + 1, end - overlap)
    return chunks
