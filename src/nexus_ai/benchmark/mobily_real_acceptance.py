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
from nexus_ai.retrieval.page_context import expand_page_context
from nexus_ai.retrieval.company_metadata import CompanyYearMetadataCatalog
from nexus_ai.benchmark.financial_chunk_forensics import normalize_anchor


GOLD_REVENUE_MILLION_SAR = 19642
GOLD_REVENUE_THOUSAND_SAR = 19641705
GOLD_REVENUE_2024_MILLION_SAR = 18206
GOLD_REVENUE_2024_THOUSAND_SAR = 18206447
# Independently checked against owner-provided screenshots. PDF page numbers,
# NOT the printed annual-report page numbers (278 and 282).
VISUALLY_VERIFIED_REVENUE_PAGES = (140, 142)

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
    # Gold-page annotations are from visually checked, original PDF tables,
    # not produced by lexical retrieval or inferred from arbitrary number hits.
    # Validate that the exact audited number survived extraction on each page.
    page_by_number = {page.page_number: page for page in indexed.document.pages}
    verified_pages = {
        page_number: bool(
            page_number in page_by_number
            and "precise_thousands" in _amount_formats(page_by_number[page_number].text)
        )
        for page_number in VISUALLY_VERIFIED_REVENUE_PAGES
    }
    verified_page_set = {page for page, valid in verified_pages.items() if valid}
    verified_chunks = {
        chunk.chunk_id for chunk in indexed.chunks
        if chunk.page_number in verified_page_set and
        "precise_thousands" in _amount_formats(chunk.text)
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
        verified_hits = [
            {"rank": rank, "page_number": item.citation.page_number,
             "exact_amount_in_cited_chunk": item.citation.chunk_id in verified_chunks}
            for rank, item in enumerate(hits, 1)
            if item.citation.page_number in verified_page_set
        ]
        queries.append({
            "verified_gold_page_at_5": any(row["rank"] <= 5 for row in verified_hits),
            "verified_gold_page_at_10": any(row["rank"] <= 10 for row in verified_hits),
            "precise_amount_in_cited_chunk_at_5": any(
                row["rank"] <= 5 and row["exact_amount_in_cited_chunk"] for row in verified_hits
            ),
            "precise_amount_in_cited_chunk_at_10": any(
                row["rank"] <= 10 and row["exact_amount_in_cited_chunk"] for row in verified_hits
            ),
            "verified_gold_page_hits": verified_hits,
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
                 "previous_year_precise_amount_thousand_sar": GOLD_REVENUE_2024_THOUSAND_SAR,
                 "public_source": GOLD_SOURCE},
        "verified_gold_page_numbers": list(VISUALLY_VERIFIED_REVENUE_PAGES),
        "verified_gold_page_amount_extracted": [
            {"page_number": page, "precise_amount_present": found}
            for page, found in verified_pages.items()
        ],
        "verified_gold_source": "owner_visual_review_of_original_pdf_tables",
        "verified_gold_citations": {
            "pdf_page_140": "printed pages 278-279; note 32 consolidated revenue",
            "pdf_page_142": "printed pages 282-283; note 42 operating segments",
        },
        "gold_evidence_status": (
            "EXACT_AMOUNT_EXTRACTED_ON_BOTH_VISUALLY_VERIFIED_PAGES"
            if all(verified_pages.values()) else
            "VISUALLY_VERIFIED_PAGE_AMOUNT_NOT_EXTRACTED"
        ),
        "verified_gold_retrieval_status": (
            "VERIFIED_PAGES_RETRIEVED_BILINGUALLY" if all(verified_pages.values()) and
            all(row["verified_gold_page_at_10"] for row in queries)
            else "VERIFIED_GOLD_RETRIEVAL_GAP"
        ),
        "acceptance_gates": {
            "verified_source_pages_retrieved_bilingually_at_10": (
                all(verified_pages.values()) and
                all(row["verified_gold_page_at_10"] for row in queries)
            ),
            "exact_amount_in_cited_chunk_bilingually_at_10": (
                all(verified_pages.values()) and
                all(row["precise_amount_in_cited_chunk_at_10"] for row in queries)
            ),
            "financial_row_association_machine_verified": False,
            "unstructured_arabic_revenue_label_detected_on_gold_page": (
                all(page in candidate_pages for page in VISUALLY_VERIFIED_REVENUE_PAGES)
            ),
        },
        "acceptance_summary": (
            "CITED_EXACT_AMOUNT_BILINGUALLY_RETRIEVED_NEEDS_ROW_ASSOCIATION"
            if all(verified_pages.values()) and all(
                row["precise_amount_in_cited_chunk_at_10"] for row in queries
            ) else
            "VERIFIED_PAGES_RETRIEVED_BUT_CITED_AMOUNT_UNVERIFIED"
            if all(verified_pages.values()) and all(
                row["verified_gold_page_at_10"] for row in queries
            ) else
            "VERIFIED_GOLD_PAGE_RETRIEVAL_GAP"
        ),
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
        "legacy_same_page_word_match_status": (
            "CANDIDATES_RETRIEVED" if candidate_pages and
            all(row["relevant_candidate_page_at_10"] for row in queries)
            else "RETRIEVAL_OR_EXTRACTION_GAP"
        ),
        "financial_truth_status": (
            "ORIGINAL_PDF_TABLE_VISUALLY_VERIFIED_AUTOMATIC_ROW_ASSOCIATION_UNVERIFIED"
        ),
        "limitations": [
            "A page may contain the number in a different table row or year.",
            "PDF page numbers are one-based; report page labels may differ.",
            "Currency/units cannot be inferred solely from page-level cooccurrence.",
            "The published gold result belongs to Mobily FY2025; the local PDF identity is checked only by its content digest and owner-selected path.",
            "A rounded millions value and a precise thousands value are distinct reporting precisions; a matching amount does not establish the page's unit.",
            "Visual human annotations are independent of extraction but not pinned to this PDF hash; verify the document edition when reusing them.",
            "Verified page retrieval is measured separately from raw page-level cooccurrence; do not claim success from presence of a gold number alone.",
            "A matching amount inside a cited chunk is only lexical numerical evidence; row, year, and currency associations are not automatically established.",
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
    # Context expansion is a distinct retrieval strategy, not an exact
    # financial-answer assertion. It cannot consult the visually labeled
    # gold pages or revenue number when selecting neighboring source pages.
    context_responses = tuple(
        expand_page_context(
            response, repository=repo, workspace_id=_WORKSPACE,
            radius=1, top_k=10,
        )
        for response in responses
    )
    evaluation = assess_evidence(indexed, context_responses)
    raw = assess_evidence(indexed, responses)
    evaluation["raw_bm25_verified_gold_retrieval_status"] = raw["verified_gold_retrieval_status"]
    evaluation["raw_bm25_top_5_pages"] = [
        row["top_5_pages"] for row in raw["languages"]
    ]
    evaluation["context_expansion_applied"] = True
    return {
        "status": "PASS",
        "source_sha256": indexed.document.content_sha256,
        "page_count": len(indexed.document.pages),
        "chunk_count": len(indexed.chunks),
        "source_processing_id": indexed.document.processing_id,
        "evaluation": evaluation,
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
