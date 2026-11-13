"""Transactional model-independent PostgreSQL persistence for extracted collections.

The schema is an inert proposal. This module never creates tables, opens a
connection at import time, or chooses a database; callers inject DB-API
connections after a reviewed schema has been installed in a disposable DB.
"""
from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from threading import RLock
from typing import Any, Callable, Iterator

from nexus_ai.documents.collection_types import CollectionIndex, validate_collection_workspace_id
from nexus_ai.documents.types import DocumentVersion, ExtractedPage, IngestionFailure, SourceChunk
from nexus_ai.retrieval.identity import (
    stable_document_id,
    stable_processing_id,
    stable_source_version_id,
)


COLLECTION_SCHEMA_DDL: tuple[str, ...] = (
    """CREATE TABLE nexus_collection_documents (
        workspace_id text NOT NULL,
        document_id char(64) NOT NULL,
        source_path text NOT NULL,
        active_version_id char(64),
        active_processing_id char(64),
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (workspace_id, document_id),
        UNIQUE (workspace_id, source_path),
        CHECK (length(workspace_id) BETWEEN 1 AND 128),
        CHECK ((active_version_id IS NULL) = (active_processing_id IS NULL)),
        CHECK (document_id ~ '^[0-9a-f]{64}$'),
        CHECK (active_version_id IS NULL OR active_version_id ~ '^[0-9a-f]{64}$'),
        CHECK (active_processing_id IS NULL OR active_processing_id ~ '^[0-9a-f]{64}$')
    )""",
    """CREATE TABLE nexus_collection_versions (
        workspace_id text NOT NULL,
        document_id char(64) NOT NULL,
        version_id char(64) NOT NULL,
        processing_id char(64) NOT NULL,
        source_path text NOT NULL,
        source_sha256 char(64) NOT NULL,
        payload_sha256 char(64) NOT NULL,
        media_type text NOT NULL,
        extractor_name text NOT NULL,
        extractor_version text NOT NULL,
        chunker_version char(64) NOT NULL,
        pages_json jsonb NOT NULL,
        warnings_json jsonb NOT NULL,
        offsets_reliable boolean NOT NULL,
        source_char_count integer NOT NULL CHECK (source_char_count BETWEEN 0 AND 10000000),
        created_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (workspace_id, document_id, version_id, processing_id),
        FOREIGN KEY (workspace_id, document_id)
            REFERENCES nexus_collection_documents(workspace_id, document_id) ON DELETE CASCADE,
        CHECK (version_id ~ '^[0-9a-f]{64}$'),
        CHECK (processing_id ~ '^[0-9a-f]{64}$'),
        CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
        CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
        CHECK (chunker_version ~ '^[0-9a-f]{64}$')
    )""",
    """ALTER TABLE nexus_collection_documents
        ADD CONSTRAINT nexus_collection_active_version_fk
        FOREIGN KEY (workspace_id, document_id, active_version_id, active_processing_id)
        REFERENCES nexus_collection_versions
            (workspace_id, document_id, version_id, processing_id)
        DEFERRABLE INITIALLY DEFERRED""",
    """CREATE TABLE nexus_collection_chunks (
        workspace_id text NOT NULL,
        document_id char(64) NOT NULL,
        version_id char(64) NOT NULL,
        processing_id char(64) NOT NULL,
        ordinal integer NOT NULL CHECK (ordinal BETWEEN 0 AND 19999),
        chunk_id char(64) NOT NULL,
        source_path text NOT NULL,
        source_sha256 char(64) NOT NULL,
        page_number integer,
        start_char integer,
        end_char integer,
        start_line integer,
        end_line integer,
        text_content text NOT NULL,
        heading_path_json jsonb NOT NULL,
        offsets_reliable boolean NOT NULL,
        extractor_name text NOT NULL,
        extractor_version text NOT NULL,
        chunker_version char(64) NOT NULL,
        PRIMARY KEY (workspace_id, document_id, version_id, processing_id, chunk_id),
        UNIQUE (workspace_id, document_id, version_id, processing_id, ordinal),
        FOREIGN KEY (workspace_id, document_id, version_id, processing_id)
            REFERENCES nexus_collection_versions
                (workspace_id, document_id, version_id, processing_id) ON DELETE CASCADE,
        CHECK (chunk_id ~ '^[0-9a-f]{64}$'),
        CHECK (page_number IS NULL OR page_number BETWEEN 1 AND 500),
        CHECK ((start_char IS NULL) = (end_char IS NULL)),
        CHECK (start_char IS NULL OR (start_char >= 0 AND end_char >= start_char)),
        CHECK ((start_line IS NULL) = (end_line IS NULL)),
        CHECK (start_line IS NULL OR (start_line > 0 AND end_line >= start_line))
    )""",
    """CREATE TABLE nexus_collection_ingestion_failures (
        failure_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        workspace_id text NOT NULL,
        source_path text NOT NULL,
        error_type text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        CHECK (length(workspace_id) BETWEEN 1 AND 128)
    )""",
    "CREATE INDEX nexus_collection_active_idx ON nexus_collection_documents (workspace_id, source_path)",
    "CREATE INDEX nexus_collection_chunks_page_idx ON nexus_collection_chunks (workspace_id, document_id, version_id, page_number)",
)


@dataclass(frozen=True)
class CollectionRepositoryLimits:
    max_documents_per_workspace: int = 150
    max_chunks_per_document: int = 20_000
    max_source_chars_per_document: int = 10_000_000
    max_chunk_text_chars_per_document: int = 20_000_000
    max_chunk_metadata_chars_per_document: int = 1_000_000
    max_failures_per_workspace: int = 100

    def __post_init__(self) -> None:
        maxima = {
            "max_documents_per_workspace": 150,
            "max_chunks_per_document": 20_000,
            "max_source_chars_per_document": 10_000_000,
            "max_chunk_text_chars_per_document": 20_000_000,
            "max_chunk_metadata_chars_per_document": 1_000_000,
            "max_failures_per_workspace": 100,
        }
        for name, maximum in maxima.items():
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f"{name} must be between 1 and {maximum}")


class InMemoryCollectionIndexRepository:
    """Bounded volatile fake/reference repository with atomic copy-on-write swaps."""

    def __init__(self, limits: CollectionRepositoryLimits = CollectionRepositoryLimits()) -> None:
        self.limits = limits
        self._lock = RLock()
        self._active: dict[tuple[str, str], CollectionIndex] = {}
        self._failures: list[IngestionFailure] = []

    def activate(self, indexed: CollectionIndex) -> bool:
        _validate_collection_index(indexed, self.limits)
        doc = indexed.document
        key = (doc.workspace_id, doc.document_id)
        with self._lock:
            old = self._active.get(key)
            if old is not None and old.document.version_id == doc.version_id \
                    and old.document.processing_id == doc.processing_id:
                if old != indexed:
                    raise ValueError("same collection generation was activated with conflicting content")
                return False
            candidate = dict(self._active)
            candidate[key] = indexed
            workspace_count = sum(1 for workspace, _ in candidate if workspace == doc.workspace_id)
            if workspace_count > self.limits.max_documents_per_workspace:
                raise ValueError("collection index exceeds max_documents_per_workspace")
            chunks = sum(len(item.chunks) for (workspace, _), item in candidate.items()
                         if workspace == doc.workspace_id)
            chars = sum(sum(len(page.text) for page in item.document.pages)
                        for (workspace, _), item in candidate.items() if workspace == doc.workspace_id)
            if chunks > self.limits.max_chunks_per_document * self.limits.max_documents_per_workspace:
                raise ValueError("collection index exceeds configured chunk capacity")
            if chars > self.limits.max_source_chars_per_document * self.limits.max_documents_per_workspace:
                raise ValueError("collection index exceeds configured source-text capacity")
            self._active = candidate
            return True

    def get_active(self, workspace_id: str, document_id: str) -> CollectionIndex | None:
        validate_collection_workspace_id(workspace_id)
        with self._lock:
            return self._active.get((workspace_id, document_id))

    def delete(self, workspace_id: str, document_id: str) -> bool:
        validate_collection_workspace_id(workspace_id)
        key = (workspace_id, document_id)
        with self._lock:
            if key not in self._active:
                return False
            candidate = dict(self._active)
            del candidate[key]
            self._active = candidate
            return True

    def record_failure(self, failure: IngestionFailure) -> None:
        _validate_failure(failure)
        with self._lock:
            scoped = [row for row in self._failures if row.workspace_id != failure.workspace_id]
            own = [row for row in self._failures if row.workspace_id == failure.workspace_id]
            retained = own[-(self.limits.max_failures_per_workspace - 1):] if self.limits.max_failures_per_workspace > 1 else []
            self._failures = [*scoped, *retained, failure]

    def failures(self, workspace_id: str | None = None) -> tuple[IngestionFailure, ...]:
        with self._lock:
            rows = tuple(self._failures)
        return rows if workspace_id is None else tuple(row for row in rows if row.workspace_id == workspace_id)


class PostgresCollectionIndexRepository:
    """DB-API persistence adapter; DDL is never executed by this class.

    The factory must return a fresh synchronous connection with autocommit
    disabled. Connections are committed or rolled back and closed per operation.
    """

    def __init__(
        self,
        connection_factory: Callable[[], Any],
        *,
        limits: CollectionRepositoryLimits = CollectionRepositoryLimits(),
        batch_size: int = 256,
    ) -> None:
        if not callable(connection_factory):
            raise TypeError("connection_factory must be callable")
        if type(batch_size) is not int or not 1 <= batch_size <= 1_000:
            raise ValueError("batch_size must be between 1 and 1000")
        self._connection_factory = connection_factory
        self.limits = limits
        self.batch_size = batch_size

    def activate(self, indexed: CollectionIndex) -> bool:
        _validate_collection_index(indexed, self.limits)
        doc = indexed.document
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                # Serialize bounded per-workspace capacity checks and pointer swaps.
                cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                               (doc.workspace_id,))
                cursor.execute(
                    """SELECT d.active_version_id, d.active_processing_id, v.payload_sha256
                       FROM nexus_collection_documents d
                       LEFT JOIN nexus_collection_versions v
                         ON v.workspace_id = d.workspace_id AND v.document_id = d.document_id
                        AND v.version_id = d.active_version_id AND v.processing_id = d.active_processing_id
                       WHERE d.workspace_id = %s AND d.document_id = %s FOR UPDATE OF d""",
                    (doc.workspace_id, doc.document_id),
                )
                current = cursor.fetchone()
                if current is None:
                    cursor.execute(
                        """INSERT INTO nexus_collection_documents (workspace_id, document_id, source_path)
                           VALUES (%s, %s, %s)
                           ON CONFLICT (workspace_id, document_id) DO NOTHING""",
                        (doc.workspace_id, doc.document_id, doc.source_path),
                    )
                    cursor.execute(
                        """SELECT d.active_version_id, d.active_processing_id, v.payload_sha256
                           FROM nexus_collection_documents d
                           LEFT JOIN nexus_collection_versions v
                             ON v.workspace_id = d.workspace_id AND v.document_id = d.document_id
                            AND v.version_id = d.active_version_id AND v.processing_id = d.active_processing_id
                           WHERE d.workspace_id = %s AND d.document_id = %s FOR UPDATE OF d""",
                        (doc.workspace_id, doc.document_id),
                    )
                    current = cursor.fetchone()
                if current and current[0] == doc.version_id and current[1] == doc.processing_id:
                    if current[2] != _payload_sha256(indexed):
                        raise ValueError("same collection generation was activated with conflicting content")
                    return False
                if current is None:
                    raise RuntimeError("collection document row was not created")
                if current[0] is None:
                    cursor.execute(
                        "SELECT COUNT(*) FROM nexus_collection_documents WHERE workspace_id = %s",
                        (doc.workspace_id,),
                    )
                    count_row = cursor.fetchone()
                    if count_row and int(count_row[0]) > self.limits.max_documents_per_workspace:
                        raise ValueError("collection exceeds max_documents_per_workspace")
                cursor.execute(
                    """INSERT INTO nexus_collection_versions
                       (workspace_id, document_id, version_id, processing_id, source_path,
                        source_sha256, payload_sha256, media_type, extractor_name, extractor_version, chunker_version,
                        pages_json, warnings_json, offsets_reliable, source_char_count)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
                       ON CONFLICT (workspace_id, document_id, version_id, processing_id) DO NOTHING""",
                    (doc.workspace_id, doc.document_id, doc.version_id, doc.processing_id,
                     doc.source_path, doc.content_sha256, _payload_sha256(indexed), doc.media_type, doc.extractor_name,
                     doc.extractor_version, doc.chunker_version,
                     _json([asdict(page) for page in doc.pages]), _json(doc.warnings),
                     doc.offsets_reliable, sum(len(page.text) for page in doc.pages)),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("inactive collection generation already exists; refusing unverified reuse")
                _execute_batches(cursor, self.batch_size, indexed)
                cursor.execute(
                    """UPDATE nexus_collection_documents
                       SET source_path = %s, active_version_id = %s, active_processing_id = %s,
                           updated_at = now()
                       WHERE workspace_id = %s AND document_id = %s""",
                    (doc.source_path, doc.version_id, doc.processing_id, doc.workspace_id, doc.document_id),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("collection active-version update did not affect one row")
                cursor.execute(
                    """DELETE FROM nexus_collection_versions
                       WHERE workspace_id = %s AND document_id = %s
                         AND NOT (version_id = %s AND processing_id = %s)""",
                    (doc.workspace_id, doc.document_id, doc.version_id, doc.processing_id),
                )
            finally:
                cursor.close()
        return True

    def get_active(self, workspace_id: str, document_id: str) -> CollectionIndex | None:
        validate_collection_workspace_id(workspace_id)
        if not isinstance(document_id, str) or not re.fullmatch(r"[0-9a-f]{64}", document_id):
            raise ValueError("document_id must be a lowercase SHA-256 identity")
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                cursor.execute(
                    """SELECT d.workspace_id, d.document_id, d.active_version_id, d.active_processing_id,
                              v.source_path, v.source_sha256, v.media_type, v.extractor_name,
                              v.extractor_version, v.chunker_version, v.pages_json, v.warnings_json,
                              v.offsets_reliable, v.payload_sha256
                       FROM nexus_collection_documents d JOIN nexus_collection_versions v
                         ON v.workspace_id = d.workspace_id AND v.document_id = d.document_id
                        AND v.version_id = d.active_version_id AND v.processing_id = d.active_processing_id
                       WHERE d.workspace_id = %s AND d.document_id = %s""",
                    (workspace_id, document_id),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                cursor.execute(
                    """SELECT chunk_id, source_path, source_sha256, extractor_name, extractor_version,
                              page_number, start_char, end_char, start_line, end_line, text_content,
                              heading_path_json, offsets_reliable, chunker_version
                       FROM nexus_collection_chunks
                       WHERE workspace_id = %s AND document_id = %s AND version_id = %s AND processing_id = %s
                       ORDER BY ordinal""",
                    (workspace_id, document_id, row[2], row[3]),
                )
                chunk_rows = cursor.fetchall()
                indexed = _decode_index(row, chunk_rows)
                _validate_collection_index(indexed, self.limits)
                if _payload_sha256(indexed) != row[13]:
                    raise ValueError("stored collection payload digest does not match its content")
                return indexed
            finally:
                cursor.close()

    def delete(self, workspace_id: str, document_id: str) -> bool:
        validate_collection_workspace_id(workspace_id)
        if not isinstance(document_id, str) or not re.fullmatch(r"[0-9a-f]{64}", document_id):
            raise ValueError("document_id must be a lowercase SHA-256 identity")
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (workspace_id,))
                cursor.execute(
                    "DELETE FROM nexus_collection_documents WHERE workspace_id = %s AND document_id = %s",
                    (workspace_id, document_id),
                )
                return cursor.rowcount == 1
            finally:
                cursor.close()

    def record_failure(self, failure: IngestionFailure) -> None:
        _validate_failure(failure)
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (failure.workspace_id,),
                )
                cursor.execute(
                    """INSERT INTO nexus_collection_ingestion_failures
                       (workspace_id, source_path, error_type) VALUES (%s, %s, %s)""",
                    (failure.workspace_id, failure.source_path, failure.error_type),
                )
                cursor.execute(
                    """DELETE FROM nexus_collection_ingestion_failures
                       WHERE workspace_id = %s AND failure_id NOT IN (
                         SELECT failure_id FROM nexus_collection_ingestion_failures
                         WHERE workspace_id = %s ORDER BY failure_id DESC LIMIT %s)""",
                    (failure.workspace_id, failure.workspace_id, self.limits.max_failures_per_workspace),
                )
            finally:
                cursor.close()

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        connection = self._connection_factory()
        if getattr(connection, "autocommit", False) is True:
            connection.close()
            raise ValueError("collection repository requires autocommit to be disabled")
        try:
            yield connection
            connection.commit()
        except BaseException:
            try:
                connection.rollback()
            except Exception:
                pass
            raise
        finally:
            connection.close()


def _validate_collection_index(indexed: CollectionIndex, limits: CollectionRepositoryLimits) -> None:
    document = indexed.document
    validate_collection_workspace_id(document.workspace_id)
    if not document.document_id or not document.version_id or not document.processing_id:
        raise ValueError("collection identity fields are required")
    if not isinstance(document.source_path, str) or not document.source_path:
        raise ValueError("source_path is required")
    path = PurePosixPath(document.source_path)
    if (not path.parts or not isinstance(document.source_path, str) or len(document.source_path) > 500
            or path.as_posix() != document.source_path or path.is_absolute()
            or ".." in path.parts or "\\" in document.source_path):
        raise ValueError("source_path must be a safe workspace-relative POSIX path")
    if path.suffix.casefold() not in {".pdf", ".md", ".txt"}:
        raise ValueError("source_path suffix is unsupported")
    for value, label in ((document.document_id, "document_id"), (document.version_id, "version_id"),
                         (document.processing_id, "processing_id"), (document.content_sha256, "source_sha256"),
                         (document.chunker_version, "chunker_version")):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError(f"{label} must be a lowercase SHA-256 identity")
    if document.version_id != stable_source_version_id(document.document_id, document.content_sha256):
        raise ValueError("version_id does not match source content")
    if document.document_id != stable_document_id(document.workspace_id, document.source_path):
        raise ValueError("document_id does not match workspace and source path")
    if any(not isinstance(value, str) or not value.strip() or len(value) > 500
           for value in (document.media_type, document.extractor_name, document.extractor_version)):
        raise ValueError("media type and extractor identity are required")
    expected_processing = stable_processing_id(
        extractor_name=document.extractor_name, extractor_version=document.extractor_version,
        media_type=document.media_type, offsets_reliable=document.offsets_reliable,
        chunker_fingerprint=document.chunker_version,
    )
    if document.processing_id != expected_processing:
        raise ValueError("processing_id does not match extraction and chunking metadata")
    if not document.pages or len(document.pages) > 500:
        raise ValueError("collection document page count is outside the supported range")
    if sum(len(page.text) for page in document.pages) > limits.max_source_chars_per_document:
        raise ValueError("collection document exceeds max_source_chars_per_document")
    page_text = {}
    for page in document.pages:
        if not isinstance(page.text, str):
            raise ValueError("extracted page text must be text")
        if page.page_number is not None and (type(page.page_number) is not int or page.page_number <= 0):
            raise ValueError("page numbers must be positive integers")
        if page.page_number in page_text:
            raise ValueError("duplicate extracted page number")
        if len(page.text) > 2_000_000:
            raise ValueError("extracted page exceeds max_pdf_page_chars")
        page_text[page.page_number] = page.text
    if (len(document.warnings) > 1_000
            or any(not isinstance(warning, str) for warning in document.warnings)
            or sum(len(warning) for warning in document.warnings) > 100_000):
        raise ValueError("extraction warnings exceed metadata limits")
    if not indexed.chunks or len(indexed.chunks) > limits.max_chunks_per_document:
        raise ValueError("collection chunk count is outside the supported range")
    chunk_ids = set()
    chunk_text_chars = 0
    heading_chars = 0
    for chunk in indexed.chunks:
        if not re.fullmatch(r"[0-9a-f]{64}", chunk.chunk_id):
            raise ValueError("chunk_id must be a lowercase SHA-256 identity")
        if chunk.chunk_id in chunk_ids:
            raise ValueError("duplicate chunk IDs are not allowed")
        chunk_ids.add(chunk.chunk_id)
        if (chunk.document_id != document.document_id or chunk.version_id != document.version_id
                or chunk.source_path != document.source_path or chunk.source_sha256 != document.content_sha256
                or chunk.extractor_name != document.extractor_name
                or chunk.extractor_version != document.extractor_version
                or chunk.chunker_version != document.chunker_version):
            raise ValueError("chunk provenance does not match its collection document")
        if chunk.page_number not in page_text:
            raise ValueError("chunk references an unknown source page")
        if chunk.offsets_reliable != document.offsets_reliable:
            raise ValueError("chunk offset reliability does not match its source")
        if not chunk.text:
            raise ValueError("empty chunks are not allowed")
        chunk_text_chars += len(chunk.text)
        if len(chunk.heading_path) > 6 or any(
            not isinstance(title, str) or len(title) > 4_000 for title in chunk.heading_path
        ):
            raise ValueError("chunk heading path exceeds metadata limits")
        heading_chars += sum(len(title) for title in chunk.heading_path)
        if chunk.offsets_reliable:
            if (type(chunk.start_char) is not int or type(chunk.end_char) is not int
                    or chunk.start_char < 0 or chunk.end_char < chunk.start_char
                    or page_text[chunk.page_number][chunk.start_char:chunk.end_char] != chunk.text):
                raise ValueError("chunk source offsets do not match extracted page text")
            if (type(chunk.start_line) is not int or type(chunk.end_line) is not int
                    or chunk.start_line <= 0 or chunk.end_line < chunk.start_line):
                raise ValueError("reliable source offsets require a valid line span")
        elif any(value is not None for value in (chunk.start_char, chunk.end_char, chunk.start_line, chunk.end_line)):
            raise ValueError("unreliable source offsets must not be persisted")
    if chunk_text_chars > limits.max_chunk_text_chars_per_document:
        raise ValueError("collection exceeds max_chunk_text_chars_per_document")
    if heading_chars > limits.max_chunk_metadata_chars_per_document:
        raise ValueError("collection exceeds max_chunk_metadata_chars_per_document")


def _execute_batches(cursor: Any, batch_size: int, indexed: CollectionIndex) -> None:
    doc = indexed.document
    statement = """INSERT INTO nexus_collection_chunks
        (workspace_id, document_id, version_id, processing_id, ordinal, chunk_id, source_path,
         source_sha256, page_number, start_char, end_char, start_line, end_line, text_content,
         heading_path_json, offsets_reliable, extractor_name, extractor_version, chunker_version)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)"""
    batch = []
    for ordinal, chunk in enumerate(indexed.chunks):
        batch.append((doc.workspace_id, doc.document_id, doc.version_id, doc.processing_id,
                      ordinal, chunk.chunk_id, chunk.source_path, chunk.source_sha256,
                      chunk.page_number, chunk.start_char, chunk.end_char, chunk.start_line,
                      chunk.end_line, chunk.text, _json(chunk.heading_path), chunk.offsets_reliable,
                      chunk.extractor_name, chunk.extractor_version, chunk.chunker_version))
        if len(batch) >= batch_size:
            cursor.executemany(statement, batch)
            batch.clear()
    if batch:
        cursor.executemany(statement, batch)


def _decode_index(document_row, chunk_rows) -> CollectionIndex:
    (workspace_id, document_id, version_id, processing_id, source_path, source_sha256,
     media_type, extractor_name, extractor_version, chunker_version, pages_value,
     warnings_value, offsets_reliable, _payload_digest) = document_row
    pages = tuple(ExtractedPage(**row) for row in _from_json(pages_value))
    document = DocumentVersion(
        workspace_id=workspace_id, document_id=document_id, version_id=version_id,
        processing_id=processing_id, source_path=source_path, content_sha256=source_sha256,
        media_type=media_type, extractor_name=extractor_name, extractor_version=extractor_version,
        chunker_version=chunker_version, pages=pages, warnings=tuple(_from_json(warnings_value)),
        offsets_reliable=offsets_reliable,
    )
    chunks = []
    for row in chunk_rows:
        (chunk_id, chunk_source_path, chunk_sha256, chunk_extractor, chunk_extractor_version,
         page_number, start_char, end_char, start_line, end_line, text, heading_path,
         chunk_offsets_reliable, chunker) = row
        chunks.append(SourceChunk(
            chunk_id=chunk_id, document_id=document_id, version_id=version_id,
            source_path=chunk_source_path, source_sha256=chunk_sha256,
            extractor_name=chunk_extractor, extractor_version=chunk_extractor_version,
            page_number=page_number, start_char=start_char, end_char=end_char,
            start_line=start_line, end_line=end_line, text=text,
            heading_path=tuple(_from_json(heading_path)), offsets_reliable=chunk_offsets_reliable,
            chunker_version=chunker,
        ))
    return CollectionIndex(document=document, chunks=tuple(chunks))


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _from_json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _payload_sha256(indexed: CollectionIndex) -> str:
    payload = {
        "document": asdict(indexed.document),
        "chunks": [asdict(chunk) for chunk in indexed.chunks],
    }
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


def _validate_failure(failure: IngestionFailure) -> None:
    validate_collection_workspace_id(failure.workspace_id)
    if (not isinstance(failure.source_path, str) or not isinstance(failure.error_type, str)
            or not failure.error_type or len(failure.error_type) > 200):
        raise ValueError("failure source_path and error_type must be non-empty text")
    path = PurePosixPath(failure.source_path)
    if (not path.parts or len(failure.source_path) > 500 or path.is_absolute() or ".." in path.parts
            or "\\" in failure.source_path or path.as_posix() != failure.source_path):
        raise ValueError("failure source_path must be safe and workspace-relative")
