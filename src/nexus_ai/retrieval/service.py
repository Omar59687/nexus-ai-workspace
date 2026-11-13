"""Backend-only retrieval over active in-memory source-index versions."""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Literal

from experiments.rag_prototype import BM25Index, Chunk, ChunkHit, exact_cosine, tokenize
from nexus_ai.documents.types import RetrievalFilters, RetrievalMatch, SourceChunk
from nexus_ai.retrieval.company_metadata import (
    CompanyYearFilter,
    CompanyYearMetadataCatalog,
    MetadataIntegrityError,
)
from nexus_ai.retrieval.embeddings import EmbeddingProvider, validate_vector
from nexus_ai.retrieval.repository import DocumentIndexRepository
from nexus_ai.retrieval.schemas import EvidenceCitation, RetrievedEvidence, RetrievalResponse


RetrievalStrategy = Literal["windowed_e5", "bm25_raw"]
MAX_TOP_K = 20
MAX_RETRIEVAL_WINDOWS = 20_000


class CitationValidationError(ValueError):
    """Raised when retrieved provenance does not match the stored source version."""


class IndexGenerationMismatchError(RuntimeError):
    """Raised when query embeddings are incompatible with active document generations."""


class IndexSnapshotChangedError(RuntimeError):
    """Raised when a two-pass lexical scan observes different active generations."""


@dataclass(frozen=True)
class RetrievalConfig:
    max_top_k: int = MAX_TOP_K
    max_windows: int = MAX_RETRIEVAL_WINDOWS  # per document
    max_total_windows: int = 1_000_000
    max_bm25_chunks: int = 100_000
    max_bm25_tokens: int = 20_000_000

    def __post_init__(self) -> None:
        if type(self.max_top_k) is not int or not 1 <= self.max_top_k <= 100:
            raise ValueError("max_top_k must be between 1 and 100")
        if type(self.max_windows) is not int or self.max_windows <= 0:
            raise ValueError("max_windows must be a positive integer")
        if type(self.max_total_windows) is not int or self.max_total_windows < self.max_windows:
            raise ValueError("max_total_windows must be at least max_windows")
        if type(self.max_bm25_chunks) is not int or self.max_bm25_chunks <= 0:
            raise ValueError("max_bm25_chunks must be positive")
        if type(self.max_bm25_tokens) is not int or self.max_bm25_tokens <= 0:
            raise ValueError("max_bm25_tokens must be positive")


class RetrievalService:
    """Independent of FastAPI, Ollama, LangChain, and persistent database state."""

    def __init__(
        self,
        *,
        repository: DocumentIndexRepository,
        embedder: EmbeddingProvider,
        config: RetrievalConfig = RetrievalConfig(),
        company_metadata: CompanyYearMetadataCatalog | None = None,
    ) -> None:
        self.repository = repository
        self.embedder = embedder
        self.config = config
        self.company_metadata = company_metadata

    def retrieve(
        self,
        query: str,
        *,
        workspace_id: str,
        top_k: int = 5,
        filters: RetrievalFilters | None = None,
        strategy: RetrievalStrategy = "windowed_e5",
        company_year_filter: CompanyYearFilter | None = None,
    ) -> RetrievalResponse:
        _validate_request(query, workspace_id, top_k, strategy, self.config)
        filters = filters or RetrievalFilters()
        if filters.page_number is not None and (type(filters.page_number) is not int or filters.page_number <= 0):
            raise ValueError("page_number filter must be a positive integer")
        if company_year_filter is None:
            rows_factory = lambda: _iter_active(self.repository, workspace_id, filters)
        else:
            if not isinstance(company_year_filter, CompanyYearFilter):
                raise ValueError("company_year_filter must be a validated CompanyYearFilter")
            if self.company_metadata is None:
                raise MetadataIntegrityError("company/year metadata filtering is not configured")
            _, selected = self.company_metadata.resolve(
                self.repository, workspace_id=workspace_id, query_filter=company_year_filter,
            )
            selected_by_id = {row.document_id: row for row in selected}
            if filters.document_id is not None:
                selected_by_id = {
                    document_id: metadata for document_id, metadata in selected_by_id.items()
                    if document_id == filters.document_id
                }
            if filters.page_number is not None:
                page_scoped = {}
                for document_id, metadata in selected_by_id.items():
                    active = self.repository.get_active(workspace_id, document_id)
                    if (active is None
                            or active.document.workspace_id != workspace_id
                            or active.document.version_id != metadata.document_version_id
                            or active.document.source_path != metadata.source_path
                            or active.document.content_sha256 != metadata.source_sha256):
                        raise MetadataIntegrityError(
                            "collection metadata is stale or incomplete; refresh the collection snapshot"
                        )
                    if any(chunk.page_number == filters.page_number for chunk in active.chunks):
                        page_scoped[document_id] = metadata
                selected_by_id = page_scoped
            rows_factory = lambda: _iter_collection_active(
                self.repository, workspace_id, filters, selected_by_id,
            )
        if strategy == "windowed_e5":
            results = self._windowed_e5_stream(query, rows_factory(), workspace_id, filters, top_k)
        else:
            results = self._bm25_stream(query, rows_factory, workspace_id, filters, top_k)
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

    def _windowed_e5_stream(self, query, indexed_rows, workspace_id, filters, top_k):
        """Scan one document generation at a time and retain only top-k evidence.

        Durable adapters can therefore avoid constructing a Python object for
        every document, full source page, and vector in a workspace at once.
        Every active generation must be compatible; mixed model generations
        fail closed instead of returning partial-corpus results.
        """
        expected = (self.embedder.model_id, self.embedder.revision,
                    getattr(self.embedder, "preprocessing_id", None))
        query_vector = None
        dimensions = None
        scanned_windows = 0
        best: dict[str, tuple[RetrievalMatch, object]] = {}
        for indexed in indexed_rows:
            if indexed.document.workspace_id != workspace_id:
                raise CitationValidationError("repository returned an index outside the requested workspace")
            if (indexed.embedding_model_id, indexed.embedding_revision, indexed.preprocessing_id) != expected:
                raise IndexGenerationMismatchError(
                    "active index generation does not match the query embedding model, revision, or preprocessing"
                )
            if dimensions is None:
                dimensions = indexed.embedding_dimensions
                query_vectors = self.embedder.embed([query], input_type="query")
                if len(query_vectors) != 1:
                    raise ValueError("embedding provider returned the wrong number of query vectors")
                query_vector = validate_vector(query_vectors[0], dimensions=dimensions)
            elif indexed.embedding_dimensions != dimensions:
                raise IndexGenerationMismatchError("active index generations use inconsistent dimensions")
            if filters.page_number is None:
                chunks = indexed.chunks
                windows = indexed.windows
            else:
                # Repository filters select documents containing the page, but
                # may return the document's full index snapshot. Restrict both
                # the vector candidates and citation map here so evidence lookup
                # cannot leak a matching chunk from a sibling page.
                chunks = tuple(
                    chunk for chunk in indexed.chunks
                    if chunk.page_number == filters.page_number
                )
                allowed_chunk_ids = {chunk.chunk_id for chunk in chunks}
                windows = tuple(
                    window for window in indexed.windows
                    if window.page_number == filters.page_number
                    and window.chunk_id in allowed_chunk_ids
                )
            if len(windows) > self.config.max_windows:
                raise ValueError("document index exceeds max_windows")
            scanned_windows += len(windows)
            if scanned_windows > self.config.max_total_windows:
                raise ValueError("workspace retrieval exceeds max_total_windows")
            if not windows:
                continue
            vector_map = {window.window_id: window.vector for window in windows}
            ranked = exact_cosine(
                query_vector, vector_map, top_k=len(windows), max_vectors=self.config.max_windows,
            )
            window_by_id = {window.window_id: window for window in windows}
            chunk_by_id = {chunk.chunk_id: chunk for chunk in chunks}
            doc_best: dict[str, tuple[float, object]] = {}
            for item in ranked:
                window = window_by_id[item.item_id]
                previous = doc_best.get(window.chunk_id)
                if previous is None or item.score > previous[0]:
                    doc_best[window.chunk_id] = (item.score, window)
            for chunk_id, (score, window) in doc_best.items():
                chunk = chunk_by_id[chunk_id]
                if chunk.version_id != indexed.document.version_id:
                    continue
                match = RetrievalMatch(
                    chunk=chunk, score=score, score_type="cosine_similarity",
                    strategy="windowed_e5", matched_window_id=window.window_id,
                    matched_window_start_char=window.start_char,
                    matched_window_end_char=window.end_char,
                )
                best[chunk_id] = (match, indexed)
            if len(best) > top_k:
                ordered = sorted(best.items(), key=lambda item: (-item[1][0].score, item[0]))[:top_k]
                best = dict(ordered)
        ordered = sorted(best.values(), key=lambda row: (-row[0].score, row[0].chunk.chunk_id))[:top_k]
        return [_to_evidence(match, workspace_id, (indexed,)) for match, indexed in ordered]

    def _bm25_stream(self, query, rows_factory, workspace_id, filters, top_k):
        """Compute corpus IDF in one pass and retain top-k hits in a second.

        Only token counts and document-generation IDs survive the first pass;
        full pages, chunks, and vectors are loaded one document at a time. A
        changed active-generation set between passes fails closed.
        """
        query_terms = set(tokenize(query))
        if not query_terms:
            return []
        document_generations: dict[str, tuple[str, str]] = {}
        frequencies = Counter()
        corpus_chunks = 0
        total_tokens = 0
        for indexed in rows_factory():
            _assert_workspace(indexed, workspace_id)
            document_id = indexed.document.document_id
            if document_id in document_generations:
                raise CitationValidationError("repository returned a duplicate active document")
            document_generations[document_id] = (
                indexed.document.version_id, indexed.index_generation_id,
            )
            for chunk in indexed.chunks:
                if filters.page_number is not None and chunk.page_number != filters.page_number:
                    continue
                tokens = tokenize(chunk.text)
                total_tokens += len(tokens)
                corpus_chunks += 1
                if corpus_chunks > self.config.max_bm25_chunks:
                    raise ValueError("BM25 corpus exceeds max_bm25_chunks")
                if total_tokens > self.config.max_bm25_tokens:
                    raise ValueError("BM25 corpus exceeds max_bm25_tokens")
                frequencies.update(set(tokens) & query_terms)
        if not corpus_chunks or not total_tokens:
            return []
        average_length = total_tokens / corpus_chunks
        idf = {
            term: math.log1p((corpus_chunks - count + 0.5) / (count + 0.5))
            for term, count in frequencies.items()
        }
        if not idf:
            return []

        second_generations: dict[str, tuple[str, str]] = {}
        best: list[tuple[RetrievalMatch, object]] = []
        for indexed in rows_factory():
            _assert_workspace(indexed, workspace_id)
            document = indexed.document
            if document.document_id in second_generations:
                raise CitationValidationError("repository returned a duplicate active document")
            second_generations[document.document_id] = (
                document.version_id, indexed.index_generation_id,
            )
            for chunk in indexed.chunks:
                if filters.page_number is not None and chunk.page_number != filters.page_number:
                    continue
                tokens = tokenize(chunk.text)
                terms = Counter(tokens)
                length_penalty = 1.2 * (0.25 + 0.75 * len(tokens) / average_length)
                score = math.fsum(
                    idf[term] * (2.2 * terms[term]) / (terms[term] + length_penalty)
                    for term in idf if terms[term]
                )
                if score <= 0:
                    continue
                best.append((RetrievalMatch(chunk, score, "bm25", "bm25_raw"), indexed))
                if len(best) > top_k:
                    best.sort(key=lambda row: (-row[0].score, row[0].chunk.chunk_id))
                    del best[top_k:]
        if document_generations != second_generations:
            raise IndexSnapshotChangedError("active document generations changed during BM25 retrieval")
        best.sort(key=lambda row: (-row[0].score, row[0].chunk.chunk_id))
        return [_to_evidence(match, workspace_id, (indexed,)) for match, indexed in best[:top_k]]


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


def _iter_active(repository, workspace_id, filters):
    iterator = getattr(repository, "iter_active", None)
    if callable(iterator):
        return iterator(workspace_id, filters)
    return iter(repository.list_active(workspace_id, filters))


def _iter_collection_active(repository, workspace_id, filters, expected_members):
    """Yield only the selected, version-bound collection members.

    Recheck identities during each retrieval pass so a concurrent replacement
    cannot cause stale metadata to authorize a different active source version.
    """
    source = _iter_active(repository, workspace_id, filters)
    seen: set[str] = set()
    try:
        for indexed in source:
            document_id = indexed.document.document_id
            metadata = expected_members.get(document_id)
            if metadata is None:
                continue
            if document_id in seen:
                raise MetadataIntegrityError("repository returned a duplicate collection document")
            document = indexed.document
            if (document.workspace_id != workspace_id
                    or document.version_id != metadata.document_version_id
                    or document.source_path != metadata.source_path
                    or document.content_sha256 != metadata.source_sha256):
                raise MetadataIntegrityError(
                    "collection metadata is stale or incomplete; refresh the collection snapshot"
                )
            seen.add(document_id)
            yield indexed
    finally:
        close = getattr(source, "close", None)
        if close is not None:
            close()
    if seen != set(expected_members):
        raise MetadataIntegrityError("collection metadata is stale or incomplete; refresh the collection snapshot")


def _assert_workspace(indexed, workspace_id):
    if indexed.document.workspace_id != workspace_id:
        raise CitationValidationError("repository returned an index outside the requested workspace")
