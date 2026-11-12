"""Backend-only retrieval over active in-memory source-index versions."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from experiments.rag_prototype import BM25Index, Chunk, ChunkHit, exact_cosine
from nexus_ai.documents.types import RetrievalFilters, RetrievalMatch, SourceChunk
from nexus_ai.retrieval.embeddings import EmbeddingProvider, validate_vector
from nexus_ai.retrieval.repository import DocumentIndexRepository
from nexus_ai.retrieval.schemas import EvidenceCitation, RetrievedEvidence, RetrievalResponse


RetrievalStrategy = Literal["windowed_e5", "bm25_raw"]
MAX_TOP_K = 20
MAX_RETRIEVAL_WINDOWS = 20_000


class CitationValidationError(ValueError):
    """Raised when retrieved provenance does not match the stored source version."""


@dataclass(frozen=True)
class RetrievalConfig:
    max_top_k: int = MAX_TOP_K
    max_windows: int = MAX_RETRIEVAL_WINDOWS

    def __post_init__(self) -> None:
        if type(self.max_top_k) is not int or not 1 <= self.max_top_k <= 100:
            raise ValueError("max_top_k must be between 1 and 100")
        if type(self.max_windows) is not int or self.max_windows <= 0:
            raise ValueError("max_windows must be a positive integer")


class RetrievalService:
    """Independent of FastAPI, Ollama, LangChain, and persistent database state."""

    def __init__(
        self,
        *,
        repository: DocumentIndexRepository,
        embedder: EmbeddingProvider,
        config: RetrievalConfig = RetrievalConfig(),
    ) -> None:
        self.repository = repository
        self.embedder = embedder
        self.config = config

    def retrieve(
        self,
        query: str,
        *,
        workspace_id: str,
        top_k: int = 5,
        filters: RetrievalFilters | None = None,
        strategy: RetrievalStrategy = "windowed_e5",
    ) -> RetrievalResponse:
        _validate_request(query, workspace_id, top_k, strategy, self.config)
        filters = filters or RetrievalFilters()
        if filters.page_number is not None and (type(filters.page_number) is not int or filters.page_number <= 0):
            raise ValueError("page_number filter must be a positive integer")
        documents = self.repository.list_active(workspace_id, filters)
        if any(indexed.document.workspace_id != workspace_id for indexed in documents):
            raise CitationValidationError("repository returned an index outside the requested workspace")
        candidate_chunks = [
            chunk for indexed in documents for chunk in indexed.chunks
            if filters.page_number is None or chunk.page_number == filters.page_number
        ]
        candidate_chunks.sort(key=lambda chunk: chunk.chunk_id)
        if not candidate_chunks:
            return RetrievalResponse(workspace_id=workspace_id, strategy=strategy, status="empty", results=[])

        if strategy == "bm25_raw":
            matches = self._bm25(query, candidate_chunks, documents, top_k)
        else:
            matches = self._windowed_e5(query, candidate_chunks, documents, top_k)
        results = [_to_evidence(match, workspace_id, documents) for match in matches]
        return RetrievalResponse(
            workspace_id=workspace_id,
            strategy=strategy,
            status="ok" if results else "empty",
            results=results,
        )

    @staticmethod
    def _bm25(
        query: str,
        chunks: list[SourceChunk],
        documents,
        top_k: int,
    ) -> tuple[RetrievalMatch, ...]:
        index_chunks = tuple(_to_prototype_chunk(chunk) for chunk in chunks)
        index = BM25Index(index_chunks)
        by_id = {chunk.chunk_id: chunk for chunk in chunks}
        doc_by_id = {row.document.document_id: row.document for row in documents}
        hits = index.search(query, top_k=top_k)
        return tuple(
            RetrievalMatch(
                chunk=by_id[hit.chunk.chunk_id], score=hit.score, score_type="bm25",
                strategy="bm25_raw",
            )
            for hit in hits
            if hit.chunk.version_id == doc_by_id[hit.chunk.document_id].version_id
        )

    def _windowed_e5(
        self,
        query: str,
        chunks: list[SourceChunk],
        documents,
        top_k: int,
    ) -> tuple[RetrievalMatch, ...]:
        allowed = {chunk.chunk_id for chunk in chunks}
        windows = [window for doc in documents for window in doc.windows if window.chunk_id in allowed]
        if len(windows) > self.config.max_windows:
            raise ValueError("retrieval candidates exceed max_windows")
        if not windows:
            return ()
        query_vectors = self.embedder.embed([query], input_type="query")
        if len(query_vectors) != 1:
            raise ValueError("embedding provider returned the wrong number of query vectors")
        query_vector = validate_vector(query_vectors[0], dimensions=documents[0].embedding_dimensions)
        vector_map = {window.window_id: window.vector for window in windows}
        ranked = exact_cosine(query_vector, vector_map, top_k=len(windows), max_vectors=self.config.max_windows)
        window_by_id = {window.window_id: window for window in windows}
        chunk_by_id = {chunk.chunk_id: chunk for chunk in chunks}
        best: dict[str, tuple[float, object]] = {}
        for item in ranked:
            window = window_by_id[item.item_id]
            previous = best.get(window.chunk_id)
            if previous is None or item.score > previous[0]:
                best[window.chunk_id] = (item.score, window)
        matches = []
        for chunk_id, (score, window) in best.items():
            chunk = chunk_by_id[chunk_id]
            doc = next(row.document for row in documents if row.document.document_id == chunk.document_id)
            if doc.version_id != chunk.version_id:
                continue
            matches.append(RetrievalMatch(
                chunk=chunk,
                score=score,
                score_type="cosine_similarity",
                strategy="windowed_e5",
                matched_window_id=window.window_id,
                matched_window_start_char=window.start_char,
                matched_window_end_char=window.end_char,
            ))
        matches.sort(key=lambda row: (-row.score, row.chunk.chunk_id))
        return tuple(matches[:top_k])


def _to_evidence(match: RetrievalMatch, workspace_id: str, documents) -> RetrievedEvidence:
    indexed = next((row for row in documents if row.document.document_id == match.chunk.document_id), None)
    if indexed is None or indexed.document.version_id != match.chunk.version_id:
        raise CitationValidationError("retrieved chunk no longer belongs to an active source version")
    if indexed.document.workspace_id != workspace_id:
        raise CitationValidationError("retrieved chunk belongs to a different workspace")
    citation = EvidenceCitation(
        workspace_id=workspace_id,
        document_id=match.chunk.document_id,
        document_version_id=match.chunk.version_id,
        source_path=match.chunk.source_path,
        source_sha256=match.chunk.source_sha256,
        page_number=match.chunk.page_number,
        chunk_id=match.chunk.chunk_id,
        start_char=match.chunk.start_char,
        end_char=match.chunk.end_char,
        matched_window_id=match.matched_window_id,
        matched_window_start_char=match.matched_window_start_char,
        matched_window_end_char=match.matched_window_end_char,
        offsets_reliable=match.chunk.offsets_reliable,
        exact_text=match.chunk.text,
    )
    validate_citation(citation, indexed.document.pages, match.chunk, windows=indexed.windows)
    return RetrievedEvidence(
        score=match.score, score_type=match.score_type,
        strategy=match.strategy, citation=citation,
    )


def validate_citation(citation: EvidenceCitation, pages, chunk: SourceChunk, *, windows=()) -> None:
    if (citation.document_id != chunk.document_id or citation.document_version_id != chunk.version_id
            or citation.chunk_id != chunk.chunk_id or citation.source_path != chunk.source_path
            or citation.source_sha256 != chunk.source_sha256 or citation.exact_text != chunk.text):
        raise CitationValidationError("citation identity does not match its indexed chunk")
    page = next((row for row in pages if row.page_number == chunk.page_number), None)
    if page is None:
        raise CitationValidationError("citation page does not exist in source version")
    if chunk.offsets_reliable:
        if (citation.start_char is None or citation.end_char is None
                or citation.start_char < 0 or citation.end_char < citation.start_char
                or citation.end_char > len(page.text)
                or page.text[citation.start_char:citation.end_char] != citation.exact_text):
            raise CitationValidationError("citation offsets do not point to the exact source text")
    elif citation.start_char is not None or citation.end_char is not None:
        raise CitationValidationError("unreliable source offsets must be unavailable")
    if citation.matched_window_id is not None:
        matched = next((row for row in windows if row.window_id == citation.matched_window_id), None)
        if windows and (matched is None or matched.chunk_id != chunk.chunk_id):
            raise CitationValidationError("matched window does not belong to the cited source chunk")
        if (citation.matched_window_start_char is None or citation.matched_window_end_char is None):
            if citation.offsets_reliable:
                raise CitationValidationError("reliable matched-window offsets must be present")
        elif (citation.start_char is None or citation.end_char is None
              or citation.matched_window_start_char < citation.start_char
              or citation.matched_window_end_char > citation.end_char
              or citation.matched_window_start_char >= citation.matched_window_end_char):
            raise CitationValidationError("matched window offsets fall outside the cited chunk")
        if matched is not None and (
            matched.start_char != citation.matched_window_start_char
            or matched.end_char != citation.matched_window_end_char
        ):
            raise CitationValidationError("matched window offsets do not match stored window provenance")


def _to_prototype_chunk(chunk: SourceChunk) -> Chunk:
    # BM25 uses only stable identity/text fields; unavailable offsets are not invented.
    return Chunk(
        source=chunk.source_path, document_id=chunk.document_id, version_id=chunk.version_id,
        chunk_id=chunk.chunk_id, start_char=chunk.start_char or 0,
        end_char=chunk.end_char or len(chunk.text), start_line=chunk.start_line or 1,
        end_line=chunk.end_line or 1, heading_path=chunk.heading_path, text=chunk.text,
    )


def _validate_request(query: str, workspace_id: str, top_k: int, strategy: str, config: RetrievalConfig) -> None:
    if not isinstance(query, str) or not query.strip() or len(query) > 8_000:
        raise ValueError("query must be non-empty and at most 8000 characters")
    if not isinstance(workspace_id, str) or not workspace_id.strip() or len(workspace_id) > 128:
        raise ValueError("workspace_id must be a non-empty string of at most 128 characters")
    if type(top_k) is not int or not 1 <= top_k <= config.max_top_k:
        raise ValueError(f"top_k must be between 1 and {config.max_top_k}")
    if strategy not in ("windowed_e5", "bm25_raw"):
        raise ValueError("unsupported retrieval strategy")
