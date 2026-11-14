"""Bounded, hash-checked original PDF evidence attachment.

No arbitrary-path filesystem read. Caller provides trusted, privately
authorized PDF bytes obtained by document/version ID from controlled storage.
The PDF is an attachment, not claimed human-verified evidence.
"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO

from fastapi import Response
from pypdf import PdfReader

from nexus_ai.data_analytics import AnalyticsInputError

MAX_REVIEW_PDF_BYTES = 40 * 1024 * 1024
MAX_REVIEW_PDF_PAGES = 500


def make_review_pdf_attachment(*, indexed_evidence: dict, pdf_bytes: bytes) -> Response:
    if not isinstance(indexed_evidence, dict):
        raise AnalyticsInputError("invalid source evidence")
    citation = indexed_evidence.get("citation")
    if (not isinstance(citation, dict)
            or indexed_evidence.get("evidence_kind") != "INDEXED_TEXT_ONLY"
            or indexed_evidence.get("requires_original_document_review") is not True
            or indexed_evidence.get("document_id") != citation.get("document_id")
            or indexed_evidence.get("version_id") != citation.get("version_id")):
        raise AnalyticsInputError("invalid source evidence")
    expected_hash = citation.get("source_sha256")
    page = indexed_evidence.get("page_number")
    if (not isinstance(expected_hash, str) or len(expected_hash) != 64
            or not isinstance(page, int) or isinstance(page, bool)
            or page < 1 or page > MAX_REVIEW_PDF_PAGES):
        raise AnalyticsInputError("invalid original PDF identity")
    if (not isinstance(pdf_bytes, bytes)
            or len(pdf_bytes) < 8
            or len(pdf_bytes) > MAX_REVIEW_PDF_BYTES
            or not pdf_bytes.startswith(b"%PDF-")):
        raise AnalyticsInputError("invalid original PDF bytes")
    if sha256(pdf_bytes).hexdigest() != expected_hash:
        raise AnalyticsInputError("original PDF digest mismatch")
    try:
        pdf = PdfReader(BytesIO(pdf_bytes), strict=True)
        if pdf.is_encrypted or not 1 <= len(pdf.pages) <= MAX_REVIEW_PDF_PAGES:
            raise AnalyticsInputError("invalid original PDF pages")
        if page > len(pdf.pages):
            raise AnalyticsInputError("cited PDF page is missing")
        # Force referenced page to resolve; do not extract or return text.
        _ = pdf.pages[page - 1].mediabox
    except AnalyticsInputError:
        raise
    except Exception as exc:
        raise AnalyticsInputError("invalid original PDF structure") from exc
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="financial-source.pdf"',
            "Cache-Control": "private, no-store",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
        },
    )
