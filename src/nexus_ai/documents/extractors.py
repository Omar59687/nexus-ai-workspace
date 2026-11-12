"""Replaceable text, Markdown, and optional page-aware PDF extractors."""
from __future__ import annotations

from io import BytesIO
from pathlib import PurePosixPath
from typing import Protocol

from nexus_ai.documents.types import ExtractedPage, ExtractionResult


class DocumentExtractionError(ValueError):
    """Raised for corrupt, encrypted, empty, or unsupported source documents."""


class ExtractorUnavailableError(RuntimeError):
    """Raised when an optional format parser is not installed."""


class DocumentExtractor(Protocol):
    name: str
    version: str

    def extract(self, content: bytes, *, source_path: str) -> ExtractionResult: ...


class UTF8TextExtractor:
    name = "utf8-text"
    version = "1"
    media_type = "text/plain"

    def extract(self, content: bytes, *, source_path: str) -> ExtractionResult:
        try:
            text = content.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError as exc:
            raise DocumentExtractionError("document is not valid UTF-8") from exc
        return ExtractionResult(self.name, self.version, self.media_type,
                                (ExtractedPage(None, text),), offsets_reliable=True)


class MarkdownExtractor(UTF8TextExtractor):
    name = "markdown"
    version = "1"
    media_type = "text/markdown"


class PdfExtractor:
    name = "pypdf"
    version = "1"
    media_type = "application/pdf"

    def __init__(self, *, max_pages: int = 500, max_page_chars: int = 2_000_000,
                 max_total_chars: int = 10_000_000) -> None:
        if type(max_pages) is not int or max_pages <= 0:
            raise ValueError("max_pages must be a positive integer")
        if type(max_page_chars) is not int or max_page_chars <= 0:
            raise ValueError("max_page_chars must be a positive integer")
        if type(max_total_chars) is not int or max_total_chars <= 0:
            raise ValueError("max_total_chars must be a positive integer")
        self.max_pages = max_pages
        self.max_page_chars = max_page_chars
        self.max_total_chars = max_total_chars

    def extract(self, content: bytes, *, source_path: str) -> ExtractionResult:
        try:
            from pypdf import PdfReader, __version__ as pypdf_version
        except ImportError as exc:
            raise ExtractorUnavailableError(
                "PDF extraction requires the optional pypdf package; install the documents extra"
            ) from exc
        try:
            reader = PdfReader(BytesIO(content), strict=True)
            if reader.is_encrypted:
                raise DocumentExtractionError("encrypted PDFs are not supported")
            if len(reader.pages) > self.max_pages:
                raise DocumentExtractionError("PDF exceeds the configured page limit")
            pages = []
            warnings = []
            total_chars = 0
            for page_number, page in enumerate(reader.pages, start=1):
                text = page.extract_text()
                if text is None:
                    text = ""
                    warnings.append(f"page {page_number} produced no extractable text")
                if not isinstance(text, str):
                    raise DocumentExtractionError(f"page {page_number} returned invalid extracted text")
                if len(text) > self.max_page_chars:
                    raise DocumentExtractionError(f"page {page_number} exceeds the extracted-text limit")
                total_chars += len(text)
                if total_chars > self.max_total_chars:
                    raise DocumentExtractionError("PDF exceeds the total extracted-text limit")
                pages.append(ExtractedPage(page_number, text))
            if not pages:
                raise DocumentExtractionError("PDF contains no pages")
        except DocumentExtractionError:
            raise
        except Exception as exc:
            raise DocumentExtractionError("PDF is corrupted or could not be extracted") from exc
        return ExtractionResult(self.name, str(pypdf_version), self.media_type,
                                tuple(pages), tuple(warnings), offsets_reliable=True)


def extractor_for_path(
    source_path: str,
    *,
    pdf_max_pages: int = 500,
    pdf_max_page_chars: int = 2_000_000,
    pdf_max_total_chars: int = 10_000_000,
    pdf_max_input_bytes: int = 25 * 1024 * 1024,
    pdf_timeout_seconds: float = 300.0,
    pdf_memory_limit_bytes: int = 1024 * 1024 * 1024,
    pdf_cpu_limit_seconds: int = 300,
) -> DocumentExtractor:
    suffix = PurePosixPath(source_path).suffix.casefold()
    if suffix == ".txt":
        return UTF8TextExtractor()
    if suffix == ".md":
        return MarkdownExtractor()
    if suffix == ".pdf":
        # Do not route untrusted PDFs through the in-process compatibility
        # extractor. The isolated runner fails closed when the OS cannot enforce
        # the requested process limits.
        from nexus_ai.documents.pdf_worker import IsolatedPdfExtractor

        return IsolatedPdfExtractor(
            max_pages=pdf_max_pages,
            max_page_chars=pdf_max_page_chars,
            max_total_chars=pdf_max_total_chars,
            max_input_bytes=pdf_max_input_bytes,
            timeout_seconds=pdf_timeout_seconds,
            memory_limit_bytes=pdf_memory_limit_bytes,
            cpu_limit_seconds=pdf_cpu_limit_seconds,
        )
    raise DocumentExtractionError("unsupported document type")
