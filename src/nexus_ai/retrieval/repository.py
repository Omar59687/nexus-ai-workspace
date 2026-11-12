"""Bounded, thread-safe in-memory index and future durable repository contract."""
from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Iterable, Protocol, Sequence
from pathlib import PurePosixPath
import re

from nexus_ai.documents.types import IndexedDocument, IngestionFailure, RetrievalFilters
from nexus_ai.retrieval.embeddings import validate_vector
from nexus_ai.retrieval.identity import (
    stable_index_generation_id,
    stable_processing_id,
    stable_source_version_id,
)


@dataclass(frozen=True)
class RepositoryLimits:
    max_documents: int = 5_000
    max_chunks: int = 100_000
    max_windows: int = 200_000
    # Python tuple-backed vectors have substantial object overhead. Keep this
    # experimental in-memory ceiling conservative; durable stores will need a
    # separate capacity policy based on their actual representation.
    max_vector_coordinates: int = 2_000_000
    max_failures: int = 100

    def __post_init__(self) -> None:
        for field, value in self.__dict__.items():
            if type(value) is not int or value <= 0:
                raise ValueError(f"{field} must be a positive integer")


class DocumentIndexRepository(Protocol):
    """Logical contract. A future PostgreSQL adapter must preserve atomic swap semantics."""

    def activate(self, indexed: IndexedDocument) -> bool: ...
    def get_active(self, workspace_id: str, document_id: str) -> IndexedDocument | None: ...
    def list_active(self, workspace_id: str, filters: RetrievalFilters | None = None) -> tuple[IndexedDocument, ...]: ...
    def iter_active(self, workspace_id: str, filters: RetrievalFilters | None = None) -> Iterable[IndexedDocument]: ...
    def delete(self, workspace_id: str, document_id: str) -> bool: ...
    def record_failure(self, failure: IngestionFailure) -> None: ...


class InMemoryDocumentIndex:
    """Copy-on-write active index; thread-safe, bounded, and intentionally volatile."""

    def __init__(self, limits: RepositoryLimits = RepositoryLimits()) -> None:
        self.limits = limits
        self._lock = RLock()
        self._active: dict[tuple[str, str], IndexedDocument] = {}
        self._failures: list[IngestionFailure] = []

    def activate(self, indexed: IndexedDocument) -> bool:
        _validate_indexed_document(indexed)
        key = (indexed.document.workspace_id, indexed.document.document_id)
        with self._lock:
            old = self._active.get(key)
            if old is not None and old.index_generation_id == indexed.index_generation_id:
                if old != indexed:
                    raise ValueError("same index generation was activated with conflicting content or vectors")
                return False
            candidate = dict(self._active)
            candidate[key] = indexed
            self._validate_capacity(candidate.values())
            # The single reference swap is the transaction boundary: readers see
            # either complete version, never a partial set of chunks/windows.
            self._active = candidate
            return True

    def get_active(self, workspace_id: str, document_id: str) -> IndexedDocument | None:
        _validate_workspace_id(workspace_id)
        with self._lock:
            return self._active.get((workspace_id, document_id))

    def list_active(
        self,
        workspace_id: str,
        filters: RetrievalFilters | None = None,
    ) -> tuple[IndexedDocument, ...]:
        _validate_workspace_id(workspace_id)
        selected = filters or RetrievalFilters()
        with self._lock:
            documents = [doc for (ws, _), doc in self._active.items() if ws == workspace_id]
        if selected.document_id is not None:
            documents = [doc for doc in documents if doc.document.document_id == selected.document_id]
        if selected.page_number is not None:
            documents = [doc for doc in documents if any(c.page_number == selected.page_number for c in doc.chunks)]
        documents.sort(key=lambda doc: (doc.document.source_path, doc.document.document_id))
        return tuple(documents)

    def iter_active(
        self,
        workspace_id: str,
        filters: RetrievalFilters | None = None,
    ) -> Iterable[IndexedDocument]:
        # In-memory storage already owns the full bounded index. Durable adapters
        # should override this and yield one document at a time from a stable
        # database snapshot.
        return iter(self.list_active(workspace_id, filters))

    def delete(self, workspace_id: str, document_id: str) -> bool:
        _validate_workspace_id(workspace_id)
        key = (workspace_id, document_id)
        with self._lock:
            if key not in self._active:
                return False
            candidate = dict(self._active)
            del candidate[key]
            self._active = candidate
            return True

    def record_failure(self, failure: IngestionFailure) -> None:
        _validate_workspace_id(failure.workspace_id)
        if not failure.source_path or not failure.error_type:
            raise ValueError("failure source_path and error_type must be non-empty")
        with self._lock:
            rows = [*self._failures, failure]
            self._failures = rows[-self.limits.max_failures:]

    def failures(self) -> tuple[IngestionFailure, ...]:
        with self._lock:
            return tuple(self._failures)

    def _validate_capacity(self, documents: Sequence[IndexedDocument] | object) -> None:
        rows = tuple(documents)  # snapshot under caller-held lock
        count_docs = len(rows)
        count_chunks = sum(len(doc.chunks) for doc in rows)
        count_windows = sum(len(doc.windows) for doc in rows)
        coordinates = sum(len(window.vector) for doc in rows for window in doc.windows)
        if count_docs > self.limits.max_documents:
            raise ValueError("in-memory index exceeds max_documents")
        if count_chunks > self.limits.max_chunks:
            raise ValueError("in-memory index exceeds max_chunks")
        if count_windows > self.limits.max_windows:
            raise ValueError("in-memory index exceeds max_windows")
        if coordinates > self.limits.max_vector_coordinates:
            raise ValueError("in-memory index exceeds max_vector_coordinates")


def _validate_indexed_document(indexed: IndexedDocument) -> None:
    document = indexed.document
    _validate_workspace_id(document.workspace_id)
    if not document.document_id or not document.version_id or not document.processing_id or not document.source_path:
        raise ValueError("indexed document identity and source are required")
    if document.version_id != stable_source_version_id(document.document_id, document.content_sha256):
        raise ValueError("source version ID does not match document identity and content")
    if not re.fullmatch(r"[0-9a-f]{64}", document.processing_id):
        raise ValueError("processing ID must be a SHA-256 identity")
    source_path = PurePosixPath(document.source_path)
    if source_path.is_absolute() or ".." in source_path.parts or "\\" in document.source_path:
        raise ValueError("source_path must be a safe workspace-relative POSIX path")
    if not re.fullmatch(r"[0-9a-f]{64}", document.content_sha256):
        raise ValueError("document source digest must be SHA-256")
    if not indexed.chunks:
        raise ValueError("indexed document needs at least one chunk")
    chunk_ids = {chunk.chunk_id for chunk in indexed.chunks}
    if len(chunk_ids) != len(indexed.chunks):
        raise ValueError("duplicate chunk IDs are not allowed")
    if any(chunk.document_id != document.document_id or chunk.version_id != document.version_id
           or chunk.source_path != document.source_path or chunk.source_sha256 != document.content_sha256
           or chunk.chunker_version != document.chunker_version
           for chunk in indexed.chunks):
        raise ValueError("chunk provenance does not match its document version")
    pages = {page.page_number: page.text for page in document.pages}
    for chunk in indexed.chunks:
        if chunk.page_number not in pages:
            raise ValueError("chunk references an unknown source page")
        if chunk.offsets_reliable:
            if (type(chunk.start_char) is not int or type(chunk.end_char) is not int
                    or chunk.start_char < 0 or chunk.end_char < chunk.start_char
                    or pages[chunk.page_number][chunk.start_char:chunk.end_char] != chunk.text):
                raise ValueError("chunk source offsets do not validate against extracted text")
        elif chunk.start_char is not None or chunk.end_char is not None:
            raise ValueError("unreliable source offsets must be unavailable")
    window_ids = {window.window_id for window in indexed.windows}
    if len(window_ids) != len(indexed.windows):
        raise ValueError("duplicate window IDs are not allowed")
    if any(window.chunk_id not in chunk_ids for window in indexed.windows):
        raise ValueError("window references an unknown chunk")
    chunk_by_id = {chunk.chunk_id: chunk for chunk in indexed.chunks}
    for window in indexed.windows:
        chunk = chunk_by_id[window.chunk_id]
        if (window.local_start < 0 or window.local_end > len(chunk.text)
                or window.local_end <= window.local_start
                or chunk.text[window.local_start:window.local_end] != window.text
                or window.page_number != chunk.page_number):
            raise ValueError("window text and chunk provenance do not match")
        if chunk.offsets_reliable:
            if (window.start_char != chunk.start_char + window.local_start
                    or window.end_char != chunk.start_char + window.local_end):
                raise ValueError("window source offsets do not validate against its chunk")
        elif window.start_char is not None or window.end_char is not None:
            raise ValueError("unreliable window offsets must be unavailable")
    if not indexed.embedding_model_id or not indexed.embedding_revision:
        raise ValueError("embedding model identity and revision are required")
    if type(indexed.embedding_dimensions) is not int or indexed.embedding_dimensions <= 0:
        raise ValueError("embedding_dimensions must be a positive integer")
    if type(indexed.window_chars) is not int or not 1 <= indexed.window_chars <= 4_096:
        raise ValueError("window_chars must be between 1 and 4096")
    if type(indexed.window_overlap_chars) is not int or not 0 <= indexed.window_overlap_chars < indexed.window_chars:
        raise ValueError("window_overlap_chars must be less than window_chars")
    if not isinstance(indexed.preprocessing_id, str) or not indexed.preprocessing_id.strip():
        raise ValueError("preprocessing identity is required")
    if not re.fullmatch(r"[0-9a-f]{64}", document.chunker_version):
        raise ValueError("chunker fingerprint must be a SHA-256 identity")
    expected_processing_id = stable_processing_id(
        extractor_name=document.extractor_name,
        extractor_version=document.extractor_version,
        media_type=document.media_type,
        offsets_reliable=document.offsets_reliable,
        chunker_fingerprint=document.chunker_version,
    )
    if document.processing_id != expected_processing_id:
        raise ValueError("processing ID does not match extraction and chunking metadata")
    expected_generation = stable_index_generation_id(
        document_id=document.document_id,
        source_version_id=document.version_id,
        processing_id=document.processing_id,
        embedding_model_id=indexed.embedding_model_id,
        embedding_revision=indexed.embedding_revision,
        embedding_dimensions=indexed.embedding_dimensions,
        chunker_fingerprint=document.chunker_version,
        window_chars=indexed.window_chars,
        window_overlap_chars=indexed.window_overlap_chars,
        preprocessing_id=indexed.preprocessing_id,
    )
    if not re.fullmatch(r"[0-9a-f]{64}", indexed.index_generation_id) or indexed.index_generation_id != expected_generation:
        raise ValueError("index generation ID does not match its configuration")
    if any(len(window.vector) != indexed.embedding_dimensions for window in indexed.windows):
        raise ValueError("window vector dimensions do not match index metadata")
    for window in indexed.windows:
        validate_vector(window.vector, dimensions=indexed.embedding_dimensions)


def _validate_workspace_id(workspace_id: str) -> None:
    if not isinstance(workspace_id, str) or not workspace_id.strip() or len(workspace_id) > 128:
        raise ValueError("workspace_id must be a non-empty string of at most 128 characters")
