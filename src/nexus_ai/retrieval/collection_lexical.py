"""Model-free BM25 retrieval from versioned collection text, with mandatory metadata scope.

Reads only registered, active documents. No E5, LLM, vector generation,
database schema writes or implicit workspace authorization.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from experiments.rag_prototype import tokenize
from nexus_ai.retrieval.company_metadata import (
    CompanyYearFilter, CompanyYearMetadataCatalog, MetadataIntegrityError,
)
from nexus_ai.retrieval.schemas import EvidenceCitation, RetrievedEvidence, RetrievalResponse


@dataclass(frozen=True)
class CollectionLexicalLimits:
    max_chunks: int = 100_000
    max_tokens: int = 20_000_000
    max_top_k: int = 20

    def __post_init__(self):
        if (type(self.max_chunks) is not int or not 1 <= self.max_chunks <= 100_000
                or type(self.max_tokens) is not int or not 1 <= self.max_tokens <= 20_000_000
                or type(self.max_top_k) is not int or not 1 <= self.max_top_k <= 20):
            raise ValueError("invalid lexical retrieval limits")


class CollectionLexicalRetriever:
    """Requires trusted workspace scope and at least one company/year filter."""

    def __init__(
        self, *, repository, catalog: CompanyYearMetadataCatalog,
        workspace_id: str, collection_id: str,
        limits: CollectionLexicalLimits = CollectionLexicalLimits(),
    ) -> None:
        if not isinstance(workspace_id, str) or not workspace_id.strip():
            raise ValueError("authorized workspace ID is required")
        if not isinstance(collection_id, str) or not collection_id.strip():
            raise ValueError("authorized collection ID is required")
        self.repository = repository
        self.catalog = catalog
        self.workspace_id = workspace_id
        self.collection_id = collection_id
        self.limits = limits

    def retrieve(
        self, query: str, *, company: str | None = None,
        financial_year: int | None = None, top_k: int = 5,
    ) -> RetrievalResponse:
        if not isinstance(query, str) or not query.strip() or len(query) > 8000:
            raise ValueError("query must be 1 to 8000 characters")
        if type(top_k) is not int or not 1 <= top_k <= self.limits.max_top_k:
            raise ValueError("invalid top_k")
        query_filter = CompanyYearFilter(self.collection_id, company, financial_year)
        snapshot, selected = self.catalog.resolve(
            self.repository, workspace_id=self.workspace_id, query_filter=query_filter,
        )
        query_terms = set(tokenize(query))
        if not query_terms or not selected:
            return self._empty_if_unchanged(snapshot.revision_id)

        # Load one registered source at a time. Every chunk is checked against
        # its corresponding source page before it can become a citation.
        chunks = []
        doc_frequencies = Counter()
        total_tokens = 0
        for metadata in selected:
            indexed = self.repository.get_active(self.workspace_id, metadata.document_id)
            if not _same_source(indexed, metadata):
                raise MetadataIntegrityError("collection source changed during retrieval")
            pages = {page.page_number: page.text for page in indexed.document.pages}
            for chunk in indexed.chunks:
                if (chunk.document_id != metadata.document_id
                        or chunk.version_id != metadata.document_version_id
                        or chunk.source_path != metadata.source_path
                        or chunk.source_sha256 != metadata.source_sha256
                        or chunk.page_number not in pages):
                    raise MetadataIntegrityError("indexed chunk provenance is inconsistent")
                if chunk.offsets_reliable and (
                    chunk.start_char is None or chunk.end_char is None
                    or chunk.start_char < 0 or chunk.end_char < chunk.start_char
                    or pages[chunk.page_number][chunk.start_char:chunk.end_char] != chunk.text
                ):
                    raise MetadataIntegrityError("source offsets do not match indexed chunk")
                tokens = tokenize(chunk.text)
                total_tokens += len(tokens)
                chunks.append((chunk, tokens))
                if len(chunks) > self.limits.max_chunks or total_tokens > self.limits.max_tokens:
                    raise ValueError("lexical corpus exceeds configured resource limits")
                doc_frequencies.update(set(tokens) & query_terms)

        if not chunks or total_tokens == 0:
            return self._empty_if_unchanged(snapshot.revision_id)
        avg_len = total_tokens / len(chunks)
        idf = {
            term: math.log1p((len(chunks) - n + 0.5) / (n + 0.5))
            for term, n in doc_frequencies.items()
        }
        scored = []
        for chunk, tokens in chunks:
            terms = Counter(tokens)
            length_penalty = 1.2 * (0.25 + 0.75 * len(tokens) / avg_len)
            score = math.fsum(
                idf[term] * (2.2 * terms[term]) / (terms[term] + length_penalty)
                for term in idf if terms[term]
            )
            if score > 0:
                scored.append((score, chunk))
        scored.sort(key=lambda hit: (-hit[0], hit[1].chunk_id))

        results = []
        for score, chunk in scored[:top_k]:
            citation = EvidenceCitation(
                workspace_id=self.workspace_id,
                document_id=chunk.document_id,
                document_version_id=chunk.version_id,
                source_path=chunk.source_path,
                source_sha256=chunk.source_sha256,
                page_number=chunk.page_number,
                chunk_id=chunk.chunk_id,
                start_char=chunk.start_char,
                end_char=chunk.end_char,
                matched_window_id=None,
                matched_window_start_char=None,
                matched_window_end_char=None,
                offsets_reliable=chunk.offsets_reliable,
                exact_text=chunk.text,
            )
            results.append(RetrievedEvidence(
                score=score, score_type="bm25", strategy="bm25_raw", citation=citation,
            ))

        # Catalog revision and indexed document identities are rechecked after
        # ranking, preventing stale versions or assignments from being returned.
        self._assert_unchanged(snapshot.revision_id, selected)
        return RetrievalResponse(
            workspace_id=self.workspace_id, strategy="bm25_raw",
            status="ok" if results else "empty", results=results,
        )

    def _assert_unchanged(self, revision_id, selected):
        if self.catalog.get(self.workspace_id, self.collection_id).revision_id != revision_id:
            raise MetadataIntegrityError("collection metadata changed during retrieval")
        for metadata in selected:
            if not _same_source(
                self.repository.get_active(self.workspace_id, metadata.document_id), metadata
            ):
                raise MetadataIntegrityError("collection source changed during retrieval")

    def _empty_if_unchanged(self, revision_id):
        if self.catalog.get(self.workspace_id, self.collection_id).revision_id != revision_id:
            raise MetadataIntegrityError("collection metadata changed during retrieval")
        return RetrievalResponse(
            workspace_id=self.workspace_id, strategy="bm25_raw",
            status="empty", results=[],
        )


def _same_source(indexed, metadata):
    return bool(indexed is not None and
        indexed.document.workspace_id == metadata.workspace_id
        and indexed.document.document_id == metadata.document_id
        and indexed.document.version_id == metadata.document_version_id
        and indexed.document.source_path == metadata.source_path
        and indexed.document.content_sha256 == metadata.source_sha256)
