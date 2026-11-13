"""Opt-in real Mobily FY2025 revenue evidence acceptance.

Gold values originate from the official Saudi Exchange annual results,
NOT from the indexed PDF or retrieved snippets. A page with both metric
and amount is a candidate only; no table-row association is inferred.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import unicodedata
from pathlib import Path

from nexus_ai.documents.collection_index import CollectionIndexService
from nexus_ai.documents.collection_types import CollectionIndexLimits
from nexus_ai.retrieval.collection_repository import InMemoryCollectionIndexRepository
from nexus_ai.retrieval.collection_registration import register_indexed_manifest
from nexus_ai.retrieval.collection_lexical import CollectionLexicalRetriever
from nexus_ai.retrieval.company_metadata import CompanyYearMetadataCatalog
from nexus_ai.benchmark.financial_chunk_forensics import normalize_anchor


GOLD_REVENUE_MILLION_SAR = 19642
GOLD_REVENUE_THOUSAND_SAR = 19641705
GOLD_REVENUE_2024_MILLION_SAR = 18206
GOLD_SOURCE = (
    "https://www.saudiexchange.sa/wps/portal/saudiexchange/newsandreports/"
    "issuer-news/issuer-announcements/issuer-announcements-details/"
    "?anCat=17&anId=93172&cs=7020&locale=en"
)
QUERIES = (
    "إيرادات موبايلي للسنة المالية 2025 مليون ريال سعودي",
    "Mobily 2025 total revenue million SAR",
)
# Official announcement rounds to millions, but audited statements report
# the unrounded amount in SAR thousands. Do not treat 19.6 billion as exact.
_AMOUNT_MILLIONS = re.compile(r"(?<![0-9])19[\s,٬]?642(?![0-9])")
_AMOUNT_THOUSANDS = re.compile(r"(?<![0-9])19[\s,٬]?641[\s,٬]?705(?![0-9])")
_REVENUE = ("ايرادات", "الايرادات", "revenue", "revenues", "المبيعات")
_WORKSPACE = "p4-single-owner-mobily-fy2025"
_COLLECTION = "mobily-2025-official-benchmark"


def _numerals(text: str) -> str:
    digit_map = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
    return unicodedata.normalize("NFKC", text).translate(digit_map)


def _amount_formats(text: str) -> tuple[str, ...]:
    normalized = _numerals(text)
    found = []
    if _AMOUNT_MILLIONS.search(normalized):
        found.append("rounded_millions")
    if _AMOUNT_THOUSANDS.search(normalized):
        found.append("precise_thousands")
    return tuple(found)


def _amount_present(text: str) -> bool:
    return bool(_amount_formats(text))


def _metric_present(text: str) -> bool:
    normalized = normalize_anchor(text)
    return any(term in normalized for term in _REVENUE)


def assess_evidence(indexed, arabic_and_english_results) -> dict:
    """Score independent numeric-label candidates without exposing PDF text."""
    # Record independent amount and label signals before intersecting them.
    # This avoids conflating "not extracted" with "extracted elsewhere".
    amount_pages = sorted({page.page_number for page in indexed.document.pages
                           if page.page_number is not None and _amount_present(page.text)})
    metric_pages = sorted({page.page_number for page in indexed.document.pages
                           if page.page_number is not None and _metric_present(page.text)})
    candidate_pages = sorted(set(amount_pages) & set(metric_pages))
    amount_formats = {
        fmt: sorted(page.page_number for page in indexed.document.pages
                    if page.page_number is not None and fmt in _amount_formats(page.text))[:50]
        for fmt in ("rounded_millions", "precise_thousands")
    }
    candidate_chunks = {
        chunk.chunk_id for chunk in indexed.chunks
        if chunk.page_number in candidate_pages
        and _amount_present(chunk.text) and _metric_present(chunk.text)
    }
    queries = []
    for label, response in zip(("ar", "en"), arabic_and_english_results):
        hits = list(response.results)
        relevant = [
            {"rank": rank, "page_number": item.citation.page_number,
             "chunk_id": item.citation.chunk_id,
             "amount_and_metric_share_chunk": item.citation.chunk_id in candidate_chunks}
            for rank, item in enumerate(hits, 1)
            if item.citation.page_number in candidate_pages
        ]
        queries.append({
            "language": label, "retrieval_status": response.status,
            "relevant_candidate_page_at_5": any(row["rank"] <= 5 for row in relevant),
            "relevant_candidate_page_at_10": any(row["rank"] <= 10 for row in relevant),
            "candidate_hits": relevant,
            "top_5_pages": [item.citation.page_number for item in hits[:5]],
        })
    return {
        "gold": {"company": "Mobily", "financial_year": 2025, "metric": "revenue",
                 "amount_million_sar": GOLD_REVENUE_MILLION_SAR,
                 "precise_amount_thousand_sar": GOLD_REVENUE_THOUSAND_SAR,
                 "previous_year_amount_million_sar": GOLD_REVENUE_2024_MILLION_SAR,
                 "public_source": GOLD_SOURCE},
        "candidate_pages": candidate_pages[:50],
        "amount_pages": amount_pages[:50],
        "metric_pages_count": len(metric_pages),
        "amount_formats": amount_formats,
        "signal_status": (
            "AMOUNT_ABSENT_FROM_EXTRACTED_TEXT" if not amount_pages else
            "AMOUNT_FOUND_NO_REVENUE_LABEL_ON_SAME_PAGE" if not candidate_pages else
            "AMOUNT_AND_REVENUE_LABEL_SHARE_PAGE"
        ),
        "candidate_page_count": len(candidate_pages),
        "candidate_chunk_count": len(candidate_chunks),
        "languages": queries,
        "technical_status": (
            "CANDIDATES_RETRIEVED" if candidate_pages and
            all(row["relevant_candidate_page_at_10"] for row in queries)
            else "RETRIEVAL_OR_EXTRACTION_GAP"
        ),
        "financial_truth_status": "HUMAN_TABLE_ROW_CONFIRMATION_REQUIRED",
        "limitations": [
            "A page may contain the number in a different table row or year.",
            "PDF page numbers are one-based; report page labels may differ.",
            "Currency/units cannot be inferred solely from page-level cooccurrence.",
            "The published gold result belongs to Mobily FY2025; the local PDF identity is checked only by its content digest and owner-selected path.",
            "A rounded millions value and a precise thousands value are distinct reporting precisions; a matching amount does not establish the page's unit.",
        ],
    }


def run(pdf: Path) -> dict:
    """One explicit PDF, one isolated extraction, one RAM index, two retrievals."""
    from nexus_ai.documents.collection_preflight import _manifest_entries
    if not pdf.is_absolute() or pdf.suffix.casefold() != ".pdf" or pdf.is_symlink() or not pdf.is_file():
        raise ValueError("provide an existing absolute non-symlink PDF")
    path = pdf.resolve(strict=True)
    repo = InMemoryCollectionIndexRepository()
    entries = _manifest_entries({"documents": [
        {"path": path.name, "company": "Mobily", "year": 2025}
    ]})
    outcome = CollectionIndexService(
        approved_root=path.parent, repository=repo,
        limits=CollectionIndexLimits(max_documents=1),
    ).index(_WORKSPACE, entries)
    first = outcome["documents"][0]
    if first["status"] not in ("indexed", "unchanged"):
        return {"status": "BLOCKED", "reason": "pdf_extraction_or_indexing_failed"}
    indexed = repo.get_active(_WORKSPACE, first["document_id"])
    catalog = CompanyYearMetadataCatalog(max_documents=1)
    register_indexed_manifest(
        catalog=catalog, repository=repo, workspace_id=_WORKSPACE,
        collection_id=_COLLECTION, entries=entries,
        companies={"mobily": ("Mobily",)},
    )
    retriever = CollectionLexicalRetriever(
        repository=repo, catalog=catalog,
        workspace_id=_WORKSPACE, collection_id=_COLLECTION,
    )
    responses = tuple(
        retriever.retrieve(q, company="Mobily", financial_year=2025, top_k=10)
        for q in QUERIES
    )
    return {
        "status": "PASS",
        "source_sha256": indexed.document.content_sha256,
        "page_count": len(indexed.document.pages),
        "chunk_count": len(indexed.chunks),
        "source_processing_id": indexed.document.processing_id,
        "evaluation": assess_evidence(indexed, responses),
        "scope": {"llm": "NONE", "embeddings": "NONE",
                  "database": "NONE", "hosted_services": "NONE"},
    }


def write_report(path: Path, result: dict, source_pdf: Path) -> None:
    if not path.is_absolute() or path.suffix.lower() != ".json" or path.is_symlink():
        raise ValueError("report path must be an absolute non-symlink .json")
    out = path.resolve()
    source_dir = source_pdf.parent.resolve(strict=True)
    if out == source_dir or source_dir in out.parents or out == source_pdf.resolve(strict=True):
        raise ValueError("report must not be written in the PDF source directory")
    out.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    fd, tmp = tempfile.mkstemp(prefix=".mobily-p4-", suffix=".tmp", dir=out.parent)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(encoded)
        os.replace(tmp, out)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
