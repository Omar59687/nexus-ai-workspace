"""Opt-in source-validated adjacent-page context for damaged financial PDF layouts.

BM25 alone can select an explanatory page adjacent to the numeric table.
This expansion retrieves bounded neighboring PDF pages from the *same active,
registered source*, with explicit context strategy (not BM25 evidence scores).
It never asserts any amount belongs to a metric; callers must verify rows.
"""
from __future__ import annotations

import re

from nexus_ai.retrieval.company_metadata import MetadataIntegrityError
from nexus_ai.retrieval.schemas import EvidenceCitation, RetrievedEvidence, RetrievalResponse


_NUMERIC_CELL = re.compile(r"(?<!\w)[0-9٠-٩۰-۹][0-9٠-٩۰-۹,٬.\s]{2,}[0-9٠-٩۰-۹](?!\w)")


def _numeric_density(text: str) -> tuple[int, int]:
    """Prioritize tabular evidence, but do not recognize any known target amount."""
    return (len(_NUMERIC_CELL.findall(text)), sum(ch.isdigit() for ch in text))


def expand_page_context(
    response: RetrievalResponse,
    *,
    repository,
    workspace_id: str,
    radius: int = 1,
    top_k: int = 10,
) -> RetrievalResponse:
    """Return top BM25 hits plus bounded adjacent *page-level* context.

    The first eligible BM25 source page anchors the expansion. This function
    does not look at a gold answer, target page, or target number. Context
    candidates are source-version checked and always labelled as context.
    """
    if type(radius) is not int or not 0 <= radius <= 2:
        raise ValueError("radius must be 0-2")
    if type(top_k) is not int or not 1 <= top_k <= 20:
        raise ValueError("top_k must be 1-20")
    if response.workspace_id != workspace_id:
        raise MetadataIntegrityError("response workspace mismatch")
    if not response.results or radius == 0:
        return RetrievalResponse(
            workspace_id=workspace_id,
            strategy="bm25_page_context",
            status=response.status,
            results=list(response.results[:top_k]),
        )

    seen = set()
    output = []

    def add(hit):
        identity = (hit.citation.document_id, hit.citation.document_version_id,
                    hit.citation.chunk_id)
        if identity not in seen and len(output) < top_k:
            seen.add(identity)
            output.append(hit)

    # Preserve best original scored evidence at rank 1.
    add(response.results[0])
    anchor = response.results[0].citation
    if anchor.page_number is not None and anchor.page_number > 0:
        indexed = repository.get_active(workspace_id, anchor.document_id)
        if (indexed is None or indexed.document.version_id != anchor.document_version_id
                or indexed.document.content_sha256 != anchor.source_sha256
                or indexed.document.source_path != anchor.source_path
                or indexed.document.workspace_id != workspace_id):
            raise MetadataIntegrityError("source changed during context expansion")
        pages = {page.page_number: page.text for page in indexed.document.pages}
        candidates = []
        for delta in range(1, radius + 1):
            for page_no in (anchor.page_number - delta, anchor.page_number + delta):
                if page_no not in pages:
                    continue
                adjacent = [c for c in indexed.chunks if c.page_number == page_no]
                if not adjacent:
                    continue
                # One source-validated, most tabular chunk from each neighbor.
                winner = max(adjacent, key=lambda c: (_numeric_density(c.text), -c.start_char if c.start_char is not None else 0))
                if winner.offsets_reliable and (
                    winner.start_char is None or winner.end_char is None
                    or pages[page_no][winner.start_char:winner.end_char] != winner.text
                ):
                    raise MetadataIntegrityError("adjacent citation offset mismatch")
                citation = EvidenceCitation(
                    workspace_id=workspace_id,
                    document_id=winner.document_id,
                    document_version_id=winner.version_id,
                    source_path=winner.source_path,
                    source_sha256=winner.source_sha256,
                    page_number=winner.page_number,
                    chunk_id=winner.chunk_id,
                    start_char=winner.start_char,
                    end_char=winner.end_char,
                    matched_window_id=None,
                    matched_window_start_char=None,
                    matched_window_end_char=None,
                    offsets_reliable=winner.offsets_reliable,
                    exact_text=winner.text,
                )
                candidates.append(RetrievedEvidence(
                    score=0.0, score_type="context", strategy="adjacent_page_context",
                    citation=citation,
                ))
        for hit in candidates:
            add(hit)
        # Fail closed if an active generation was swapped during expansion.
        after = repository.get_active(workspace_id, anchor.document_id)
        if (after is None or after.document.version_id != anchor.document_version_id
                or after.document.content_sha256 != anchor.source_sha256):
            raise MetadataIntegrityError("source changed after context expansion")

    for hit in response.results[1:]:
        add(hit)
    return RetrievalResponse(
        workspace_id=workspace_id, strategy="bm25_page_context",
        status="ok" if output else "empty", results=output,
    )
