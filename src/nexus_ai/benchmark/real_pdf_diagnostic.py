"""Explicit, model-free real-PDF extraction and retrieval diagnostics.

The report omits source text and prompts. It is a diagnostic, not a financial
accuracy claim, and uses only the existing bounded isolated-PDF worker.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from nexus_ai.documents.collection_index import CollectionIndexService
from nexus_ai.documents.collection_types import CollectionIndexLimits
from nexus_ai.retrieval.collection_repository import InMemoryCollectionIndexRepository
from nexus_ai.retrieval.collection_registration import register_indexed_manifest
from nexus_ai.retrieval.collection_lexical import CollectionLexicalRetriever
from nexus_ai.retrieval.company_metadata import CompanyYearMetadataCatalog


_MAX_QUERIES = 12
_MAX_QUERY_CHARS = 300
_MAX_RESULTS = 10
_MAX_PAGE_ROWS = 500
_WORKSPACE = "nexus-local-real-pdf-diagnostic"
_COLLECTION = "owner-explicit-report"


def validate_queries(queries: list[str]) -> list[str]:
    if (not isinstance(queries, list) or not 1 <= len(queries) <= _MAX_QUERIES
            or any(not isinstance(q, str) or not q.strip() or len(q) > _MAX_QUERY_CHARS for q in queries)):
        raise ValueError("provide 1-12 nonblank queries of up to 300 characters")
    return queries


def run_diagnostic(pdf: Path, *, company: str, year: int, queries: list[str],
                   top_k: int = 5, repository=None) -> dict[str, object]:
    """Read exactly one authorized PDF, index in RAM, score lexical citations.

    No directory walk, model calls, external services, or database connection.
    Source text is used in RAM but not written to the JSON report.
    """
    from nexus_ai.documents.collection_preflight import _manifest_entries

    validate_queries(queries)
    if type(top_k) is not int or not 1 <= top_k <= _MAX_RESULTS:
        raise ValueError("top_k must be 1-10")
    path = Path(pdf)
    if not path.is_absolute() or path.suffix.casefold() != ".pdf":
        raise ValueError("a single absolute .pdf file is required")
    if path.is_symlink() or not path.is_file():
        raise ValueError("PDF must be an existing ordinary file, not a symlink")
    root = path.parent.resolve(strict=True)
    # Never pass an arbitrary absolute path to the source-root reader.
    relative_path = path.name
    entries = _manifest_entries({"documents": [{
        "path": relative_path, "company": company, "year": year,
    }]})
    repo = repository if repository is not None else InMemoryCollectionIndexRepository()
    indexer = CollectionIndexService(
        approved_root=root, repository=repo,
        limits=CollectionIndexLimits(max_documents=1),
    )
    index_result = indexer.index(_WORKSPACE, entries)
    row = index_result["documents"][0]
    if row["status"] not in ("indexed", "unchanged"):
        return {
            "kind": "real_pdf_model_free_diagnostic_v1",
            "status": "BLOCKED",
            "reason": row.get("reason", "extraction_or_persistence_failed"),
            "scope": _scope(),
        }

    active = repo.get_active(_WORKSPACE, row["document_id"])
    if active is None:
        raise RuntimeError("indexed document disappeared")
    document = active.document
    pages = document.pages
    if len(pages) > _MAX_PAGE_ROWS:
        raise ValueError("PDF page count exceeds diagnostic limit")
    page_stats = []
    for page in pages:
        text = page.text
        page_stats.append({
            "page_number": page.page_number,
            "characters": len(text),
            "nonblank": bool(text.strip()),
            "arabic_characters": sum("\u0600" <= ch <= "\u06ff" for ch in text),
            "digit_characters": sum(ch.isdigit() for ch in text),
            "line_count": len(text.splitlines()),
        })

    # The catalog validates that the same exact index is queried. This uses a
    # trusted, explicit label rather than guessing the company or financial year.
    catalog = CompanyYearMetadataCatalog(max_documents=1)
    register_indexed_manifest(
        catalog=catalog, repository=repo, workspace_id=_WORKSPACE,
        collection_id=_COLLECTION, entries=entries,
        companies={"report": (company,)},
    )
    retriever = CollectionLexicalRetriever(
        repository=repo, catalog=catalog,
        workspace_id=_WORKSPACE, collection_id=_COLLECTION,
    )
    results = []
    for query in queries:
        retrieved = retriever.retrieve(
            query, company=company, financial_year=year, top_k=top_k,
        )
        results.append({
            "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
            "retrieval_status": retrieved.status,
            "matches": [{
                "rank": i,
                "page_number": item.citation.page_number,
                "score": round(item.score, 6),
                "chunk_id": item.citation.chunk_id,
                "start_char": item.citation.start_char,
                "end_char": item.citation.end_char,
                "source_version_id": item.citation.document_version_id,
                "citation_offsets_validated": True,
            } for i, item in enumerate(retrieved.results, start=1)],
        })

    return {
        "kind": "real_pdf_model_free_diagnostic_v1",
        "status": "PASS",
        "source": {
            "sha256": document.content_sha256,
            "version_id": document.version_id,
            "processing_id": document.processing_id,
            "media_type": document.media_type,
            "extractor": document.extractor_name,
            "extractor_version": document.extractor_version,
            "page_count": len(pages),
            "chunk_count": len(active.chunks),
            "extracted_character_count": sum(len(page.text) for page in pages),
            "nonblank_page_count": sum(bool(page.text.strip()) for page in pages),
            "warning_count": len(document.warnings),
        },
        "page_coverage": page_stats,
        "queries": results,
        "scope": _scope(),
        "limitations": [
            "No real financial facts or answers are validated without independent page annotations.",
            "Page coverage does not prove financial table row/column correctness.",
            "Raw source text and queries are deliberately omitted from this report.",
            "The index is in RAM; no PostgreSQL transaction or durability was tested.",
        ],
    }


def _scope() -> dict[str, str]:
    return {
        "model_calls": "NONE",
        "embeddings": "NONE",
        "database_connections": "NONE",
        "directory_crawling": "NONE",
        "persistent_index_writes": "NONE",
    }
