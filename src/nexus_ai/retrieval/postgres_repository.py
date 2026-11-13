"""Transactional PostgreSQL persistence adapter proposal for document indexes.

This adapter deliberately does not create or migrate its schema. Its DDL is a
reviewable proposal; an Alembic migration and disposable-PostgreSQL verification
must precede any deployment. Connections are injected, so importing this module
does not require psycopg or open a database connection.
"""
from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields, is_dataclass
from typing import Any, Callable, Iterator, Sequence

from nexus_ai.documents.types import (
    DocumentVersion,
    ExtractedPage,
    IndexedDocument,
    IndexedWindow,
    IngestionFailure,
    RetrievalFilters,
    SourceChunk,
)
from nexus_ai.retrieval.embeddings import validate_vector
from nexus_ai.retrieval.repository import (
    DocumentIndexRepository,
    _validate_indexed_document,
    _validate_workspace_id,
)


# Candidate DDL only. Never executed automatically by the adapter.
POSTGRES_SCHEMA_DDL: tuple[str, ...] = (
    """CREATE TABLE nexus_rag_documents (
        workspace_id text NOT NULL,
        document_id text NOT NULL,
        source_path text NOT NULL,
        active_version_id text,
        active_processing_id char(64),
        active_generation_id char(64),
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (workspace_id, document_id),
        UNIQUE (workspace_id, source_path),
        UNIQUE (workspace_id, document_id, source_path),
        CHECK (length(workspace_id) BETWEEN 1 AND 128),
        CHECK ((active_version_id IS NULL) = (active_processing_id IS NULL)),
        CHECK ((active_version_id IS NULL) = (active_generation_id IS NULL))
    )""",
    """CREATE TABLE nexus_rag_document_versions (
        workspace_id text NOT NULL,
        document_id text NOT NULL,
        version_id text NOT NULL,
        source_path text NOT NULL,
        source_sha256 char(64) NOT NULL,
        media_type text NOT NULL,
        extractor_name text NOT NULL,
        extractor_version text NOT NULL,
        chunker_version text NOT NULL,
        processing_id char(64) NOT NULL,
        source_payload_sha256 char(64) NOT NULL,
        pages_json jsonb NOT NULL,
        warnings_json jsonb NOT NULL,
        offsets_reliable boolean NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (workspace_id, document_id, version_id, processing_id),
        FOREIGN KEY (workspace_id, document_id, source_path)
            REFERENCES nexus_rag_documents(workspace_id, document_id, source_path) ON DELETE CASCADE,
        CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
        CHECK (source_payload_sha256 ~ '^[0-9a-f]{64}$')
    )""",
    """CREATE TABLE nexus_rag_index_generations (
        workspace_id text NOT NULL,
        document_id text NOT NULL,
        version_id text NOT NULL,
        processing_id char(64) NOT NULL,
        generation_id char(64) NOT NULL,
        embedding_model_id text NOT NULL,
        embedding_revision text NOT NULL,
        embedding_dimensions integer NOT NULL CHECK (embedding_dimensions BETWEEN 1 AND 4096),
        window_chars integer NOT NULL CHECK (window_chars BETWEEN 1 AND 4096),
        window_overlap_chars integer NOT NULL CHECK (window_overlap_chars >= 0 AND window_overlap_chars < window_chars),
        preprocessing_id text NOT NULL,
        payload_sha256 char(64) NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (workspace_id, document_id, version_id, processing_id, generation_id),
        FOREIGN KEY (workspace_id, document_id, version_id, processing_id)
            REFERENCES nexus_rag_document_versions(workspace_id, document_id, version_id, processing_id)
            ON DELETE CASCADE,
        CHECK (generation_id ~ '^[0-9a-f]{64}$'),
        CHECK (payload_sha256 ~ '^[0-9a-f]{64}$')
    )""",
    """ALTER TABLE nexus_rag_documents
        ADD CONSTRAINT nexus_rag_active_generation_fk
        FOREIGN KEY (workspace_id, document_id, active_version_id, active_processing_id, active_generation_id)
        REFERENCES nexus_rag_index_generations
            (workspace_id, document_id, version_id, processing_id, generation_id)
        DEFERRABLE INITIALLY DEFERRED""",
    """CREATE TABLE nexus_rag_chunks (
        workspace_id text NOT NULL,
        document_id text NOT NULL,
        version_id text NOT NULL,
        processing_id char(64) NOT NULL,
        generation_id char(64) NOT NULL,
        chunk_id text NOT NULL,
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
        chunker_version text NOT NULL,
        PRIMARY KEY (workspace_id, document_id, version_id, processing_id, generation_id, chunk_id),
        FOREIGN KEY (workspace_id, document_id, version_id, processing_id, generation_id)
            REFERENCES nexus_rag_index_generations
            (workspace_id, document_id, version_id, processing_id, generation_id) ON DELETE CASCADE,
        CHECK (page_number IS NULL OR page_number > 0),
        CHECK ((start_char IS NULL) = (end_char IS NULL)),
        CHECK (start_char IS NULL OR (start_char >= 0 AND end_char >= start_char))
    )""",
    """CREATE TABLE nexus_rag_windows (
        workspace_id text NOT NULL,
        document_id text NOT NULL,
        version_id text NOT NULL,
        processing_id char(64) NOT NULL,
        generation_id char(64) NOT NULL,
        window_id text NOT NULL,
        chunk_id text NOT NULL,
        page_number integer,
        start_char integer,
        end_char integer,
        local_start integer NOT NULL CHECK (local_start >= 0),
        local_end integer NOT NULL CHECK (local_end > local_start),
        text_content text NOT NULL,
        vector double precision[] NOT NULL,
        PRIMARY KEY (workspace_id, document_id, version_id, processing_id, generation_id, window_id),
        FOREIGN KEY (workspace_id, document_id, version_id, processing_id, generation_id, chunk_id)
            REFERENCES nexus_rag_chunks
            (workspace_id, document_id, version_id, processing_id, generation_id, chunk_id) ON DELETE CASCADE,
        CHECK (array_ndims(vector) = 1 AND cardinality(vector) BETWEEN 1 AND 4096),
        CHECK ((start_char IS NULL) = (end_char IS NULL)),
        CHECK (start_char IS NULL OR (start_char >= 0 AND end_char >= start_char))
    )""",
    """CREATE TABLE nexus_rag_ingestion_failures (
        failure_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        workspace_id text NOT NULL,
        source_path text NOT NULL,
        error_type text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        CHECK (length(workspace_id) BETWEEN 1 AND 128)
    )""",
    "CREATE INDEX nexus_rag_active_workspace_idx ON nexus_rag_documents (workspace_id, source_path, document_id)",
    "CREATE INDEX nexus_rag_chunks_page_idx ON nexus_rag_chunks (workspace_id, document_id, version_id, generation_id, page_number)",
    "CREATE INDEX nexus_rag_windows_chunk_idx ON nexus_rag_windows (workspace_id, document_id, version_id, generation_id, chunk_id)",
)


class PostgresDocumentIndex(DocumentIndexRepository):
    """DB-API adapter with atomic active-generation swaps.

    `connection_factory` must return a fresh synchronous DB-API connection with
    autocommit disabled. The adapter commits or rolls back and closes it for each
    operation. Use only a database with the reviewed candidate schema installed.
    It stores exact vectors in PostgreSQL arrays and ranks them in application
    code; no pgvector extension is needed or installed. The current repository
    protocol returns complete active indexes, so list reads are preflighted and
    bounded. This prevents unbounded loading but does not meet the 50–150 PDF
    workload target; a streaming candidate-window query contract remains needed.
    """

    def __init__(
        self,
        connection_factory: Callable[[], Any],
        *,
        read_limits: "PostgresReadLimits | None" = None,
        max_failures_per_workspace: int = 100,
    ) -> None:
        if not callable(connection_factory):
            raise TypeError("connection_factory must be callable")
        self._connection_factory = connection_factory
        self.read_limits = read_limits or PostgresReadLimits()
        if type(max_failures_per_workspace) is not int or max_failures_per_workspace <= 0:
            raise ValueError("max_failures_per_workspace must be a positive integer")
        self.max_failures_per_workspace = max_failures_per_workspace

    def activate(self, indexed: IndexedDocument) -> bool:
        _validate_indexed_document(indexed)
        generation_id = _generation_id(indexed)
        payload_sha256 = _indexed_payload_sha256(indexed)
        document = indexed.document
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                # Materialize the parent before locking it. SELECT ... FOR
                # UPDATE alone does not lock a missing row, so concurrent first
                # activations otherwise have no document-level serialization.
                cursor.execute(
                    """INSERT INTO nexus_rag_documents
                       (workspace_id, document_id, source_path)
                       VALUES (%s, %s, %s)
                       ON CONFLICT DO NOTHING""",
                    (document.workspace_id, document.document_id, document.source_path),
                )
                cursor.execute(
                    """SELECT source_path, active_version_id, active_processing_id, active_generation_id
                       FROM nexus_rag_documents WHERE workspace_id = %s AND document_id = %s
                       FOR UPDATE""",
                    (document.workspace_id, document.document_id),
                )
                current = cursor.fetchone()
                if current is None:
                    # ON CONFLICT DO NOTHING can indicate another document ID
                    # already owns this workspace/source path. Fail closed with
                    # an explicit identity error, not an unexplained missing row.
                    cursor.execute(
                        """SELECT document_id FROM nexus_rag_documents
                           WHERE workspace_id = %s AND source_path = %s""",
                        (document.workspace_id, document.source_path),
                    )
                    if cursor.fetchone() is not None:
                        raise ValueError("source path is already bound to a different document identity")
                    raise RuntimeError("document identity row disappeared during activation")
                if current[0] != document.source_path:
                    raise ValueError("document ID is already bound to a different source path")
                if (current[1] == document.version_id and current[2] == document.processing_id
                        and current[3] == generation_id):
                    stored_payload = self._generation_payload_sha256(
                        cursor, document.workspace_id, document.document_id,
                        document.version_id, document.processing_id, generation_id,
                    )
                    if stored_payload != payload_sha256:
                        raise ValueError("active index generation ID has a different immutable payload")
                    return False
                cursor.execute(
                    """INSERT INTO nexus_rag_document_versions
                       (workspace_id, document_id, version_id, source_path, source_sha256,
                        media_type, extractor_name, extractor_version, chunker_version, processing_id,
                        source_payload_sha256, pages_json, warnings_json, offsets_reliable)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
                       ON CONFLICT (workspace_id, document_id, version_id, processing_id) DO NOTHING""",
                    (
                        document.workspace_id, document.document_id, document.version_id,
                        document.source_path, document.content_sha256, document.media_type,
                        document.extractor_name, document.extractor_version,
                        document.chunker_version, document.processing_id,
                        _document_payload_sha256(document),
                        _json([asdict(page) for page in document.pages]),
                        _json(document.warnings), document.offsets_reliable,
                    ),
                )
                if cursor.rowcount != 1:
                    stored_source_payload = self._source_payload_sha256(
                        cursor, document.workspace_id, document.document_id,
                        document.version_id, document.processing_id,
                    )
                    if stored_source_payload != _document_payload_sha256(document):
                        raise ValueError("source version identity has different immutable provenance")
                cursor.execute(
                    """INSERT INTO nexus_rag_index_generations
                       (workspace_id, document_id, version_id, processing_id, generation_id,
                        embedding_model_id, embedding_revision, embedding_dimensions,
                        window_chars, window_overlap_chars, preprocessing_id, payload_sha256)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (workspace_id, document_id, version_id, processing_id, generation_id) DO NOTHING""",
                    (
                        document.workspace_id, document.document_id, document.version_id,
                        document.processing_id, generation_id,
                        indexed.embedding_model_id, indexed.embedding_revision,
                        indexed.embedding_dimensions, indexed.window_chars,
                        indexed.window_overlap_chars, indexed.preprocessing_id, payload_sha256,
                    ),
                )
                generation_created = cursor.rowcount == 1
                if not generation_created:
                    stored_payload = self._generation_payload_sha256(
                        cursor, document.workspace_id, document.document_id,
                        document.version_id, document.processing_id, generation_id,
                    )
                    if stored_payload != payload_sha256:
                        raise ValueError("index generation ID has a different immutable payload")
                if generation_created:
                    _execute_batches(
                        cursor,
                        """INSERT INTO nexus_rag_chunks
                           (workspace_id, document_id, version_id, processing_id, generation_id, chunk_id,
                            page_number, start_char, end_char, start_line, end_line,
                            text_content, heading_path_json, offsets_reliable,
                            extractor_name, extractor_version, chunker_version)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                                   %s::jsonb, %s, %s, %s, %s)""",
                        (
                            (
                                document.workspace_id, document.document_id, document.version_id,
                                document.processing_id, generation_id, chunk.chunk_id, chunk.page_number,
                                chunk.start_char, chunk.end_char, chunk.start_line, chunk.end_line,
                                chunk.text, _json(chunk.heading_path), chunk.offsets_reliable,
                                chunk.extractor_name, chunk.extractor_version, chunk.chunker_version,
                            )
                            for chunk in indexed.chunks
                        ),
                    )
                    _execute_batches(
                        cursor,
                        """INSERT INTO nexus_rag_windows
                           (workspace_id, document_id, version_id, processing_id, generation_id, window_id,
                            chunk_id, page_number, start_char, end_char, local_start, local_end,
                            text_content, vector)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (
                            (
                                document.workspace_id, document.document_id, document.version_id,
                                document.processing_id, generation_id, window.window_id, window.chunk_id,
                                window.page_number, window.start_char, window.end_char,
                                window.local_start, window.local_end, window.text, list(window.vector),
                            )
                            for window in indexed.windows
                        ),
                    )
                cursor.execute(
                    """UPDATE nexus_rag_documents
                       SET source_path = %s, active_version_id = %s,
                           active_processing_id = %s, active_generation_id = %s, updated_at = now()
                       WHERE workspace_id = %s AND document_id = %s""",
                    (
                        document.source_path, document.version_id, document.processing_id, generation_id,
                        document.workspace_id, document.document_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("document active-generation update did not affect one row")
            finally:
                cursor.close()
        return True

    @staticmethod
    def _source_payload_sha256(
        cursor: Any, workspace_id: str, document_id: str, version_id: str, processing_id: str,
    ) -> str:
        cursor.execute(
            """SELECT source_payload_sha256 FROM nexus_rag_document_versions
               WHERE workspace_id = %s AND document_id = %s AND version_id = %s
                 AND processing_id = %s""",
            (workspace_id, document_id, version_id, processing_id),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("source version conflict row is missing")
        return row[0].strip() if isinstance(row[0], str) else str(row[0])

    @staticmethod
    def _generation_payload_sha256(
        cursor: Any, workspace_id: str, document_id: str, version_id: str,
        processing_id: str, generation_id: str,
    ) -> str:
        cursor.execute(
            """SELECT payload_sha256 FROM nexus_rag_index_generations
               WHERE workspace_id = %s AND document_id = %s AND version_id = %s
                 AND processing_id = %s AND generation_id = %s""",
            (workspace_id, document_id, version_id, processing_id, generation_id),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("index generation conflict row is missing")
        return row[0].strip() if isinstance(row[0], str) else str(row[0])

    def get_active(self, workspace_id: str, document_id: str) -> IndexedDocument | None:
        _validate_workspace_id(workspace_id)
        docs = self.list_active(workspace_id, RetrievalFilters(document_id=document_id))
        return docs[0] if docs else None

    def list_active(
        self,
        workspace_id: str,
        filters: RetrievalFilters | None = None,
    ) -> tuple[IndexedDocument, ...]:
        """Materializing convenience API; prefer ``iter_active`` for retrieval."""
        return tuple(self.iter_active(workspace_id, filters))

    def iter_active(
        self,
        workspace_id: str,
        filters: RetrievalFilters | None = None,
    ) -> Iterator[IndexedDocument]:
        """Yield at most one fully loaded document index at a time.

        The global preflight rejects requests above configured caps before
        loading page/chunk/window payloads. A repeatable-read snapshot prevents
        a concurrent activation or cleanup from mixing source/index versions.
        Callers must consume or explicitly close the iterator to finish the
        read transaction.
        """
        _validate_workspace_id(workspace_id)
        selected = filters or RetrievalFilters()
        if selected.document_id is not None and (not isinstance(selected.document_id, str) or not selected.document_id):
            raise ValueError("document_id filter must be non-empty text")
        if selected.page_number is not None and (type(selected.page_number) is not int or selected.page_number <= 0):
            raise ValueError("page_number filter must be a positive integer")
        predicates, params = _active_predicates(workspace_id, selected)
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                cursor.execute(
                    """SELECT COUNT(*),
                              COALESCE(SUM((SELECT COUNT(*) FROM nexus_rag_chunks c
                                WHERE c.workspace_id = d.workspace_id AND c.document_id = d.document_id
                                  AND c.version_id = d.active_version_id AND c.processing_id = d.active_processing_id
                                  AND c.generation_id = d.active_generation_id)), 0),
                              COALESCE(SUM((SELECT COUNT(*) FROM nexus_rag_windows w
                                WHERE w.workspace_id = d.workspace_id AND w.document_id = d.document_id
                                  AND w.version_id = d.active_version_id AND w.processing_id = d.active_processing_id
                                  AND w.generation_id = d.active_generation_id)), 0),
                              COALESCE(SUM((SELECT COUNT(*) * g.embedding_dimensions FROM nexus_rag_windows w
                                WHERE w.workspace_id = d.workspace_id AND w.document_id = d.document_id
                                  AND w.version_id = d.active_version_id AND w.processing_id = d.active_processing_id
                                  AND w.generation_id = d.active_generation_id)), 0),
                              COALESCE(SUM((SELECT SUM(length(p.value->>'text'))
                                FROM jsonb_array_elements(v.pages_json) p)), 0),
                              COALESCE(SUM((SELECT SUM(length(c.text_content)) FROM nexus_rag_chunks c
                                WHERE c.workspace_id = d.workspace_id AND c.document_id = d.document_id
                                  AND c.version_id = d.active_version_id AND c.processing_id = d.active_processing_id
                                  AND c.generation_id = d.active_generation_id)), 0),
                              COALESCE(SUM((SELECT SUM(length(w.text_content)) FROM nexus_rag_windows w
                                WHERE w.workspace_id = d.workspace_id AND w.document_id = d.document_id
                                  AND w.version_id = d.active_version_id AND w.processing_id = d.active_processing_id
                                  AND w.generation_id = d.active_generation_id)), 0)
                       FROM nexus_rag_documents d
                       JOIN nexus_rag_document_versions v
                         ON v.workspace_id = d.workspace_id AND v.document_id = d.document_id
                        AND v.version_id = d.active_version_id AND v.processing_id = d.active_processing_id
                       JOIN nexus_rag_index_generations g
                         ON g.workspace_id = d.workspace_id AND g.document_id = d.document_id
                        AND g.version_id = d.active_version_id AND g.processing_id = d.active_processing_id
                        AND g.generation_id = d.active_generation_id
                       WHERE """ + " AND ".join(predicates),
                    tuple(params),
                )
                totals = cursor.fetchone() or (0, 0, 0, 0, 0, 0, 0)
                _enforce_read_limits(totals, self.read_limits)
                cursor.execute(
                    """SELECT d.workspace_id, d.document_id,
                              d.active_version_id, d.active_processing_id, d.active_generation_id
                       FROM nexus_rag_documents d
                       WHERE """ + " AND ".join(predicates) +
                    " ORDER BY d.source_path, d.document_id",
                    tuple(params),
                )
                while True:
                    rows = cursor.fetchmany(1)
                    if not rows:
                        break
                    row = rows[0]
                    yield self._load_indexed_document(connection, row[0], row[1], row[2], row[3], row[4])
            finally:
                cursor.close()

    def _load_indexed_document(
        self,
        connection: Any,
        workspace_id: str,
        document_id: str,
        version_id: str,
        processing_id: str,
        generation_id: str,
    ) -> IndexedDocument:
        cursor = connection.cursor()
        try:
            cursor.execute(
                """SELECT d.source_path, v.source_sha256, v.media_type,
                          v.extractor_name, v.extractor_version, v.chunker_version,
                          v.processing_id, v.pages_json, v.warnings_json, v.offsets_reliable,
                          g.embedding_model_id, g.embedding_revision, g.embedding_dimensions,
                          g.window_chars, g.window_overlap_chars, g.preprocessing_id
                   FROM nexus_rag_documents d
                   JOIN nexus_rag_document_versions v
                     ON v.workspace_id = d.workspace_id AND v.document_id = d.document_id
                    AND v.version_id = %s AND v.processing_id = %s
                   JOIN nexus_rag_index_generations g
                     ON g.workspace_id = d.workspace_id AND g.document_id = d.document_id
                    AND g.version_id = v.version_id AND g.processing_id = v.processing_id
                    AND g.generation_id = %s
                   WHERE d.workspace_id = %s AND d.document_id = %s
                     AND d.active_version_id = %s AND d.active_processing_id = %s
                     AND d.active_generation_id = %s""",
                (version_id, processing_id, generation_id, workspace_id, document_id,
                 version_id, processing_id, generation_id),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("active document version changed within read snapshot")
            (
                source_path, source_sha256, media_type, extractor_name, extractor_version,
                chunker_version, processing_id, pages_json, warnings_json, offsets_reliable,
                model_id, revision, dimensions, window_chars, window_overlap_chars, preprocessing_id,
            ) = row
            return self._construct_indexed_document(
                cursor, workspace_id, document_id, version_id, generation_id,
                source_path, source_sha256, media_type, extractor_name, extractor_version,
                chunker_version, processing_id, pages_json, warnings_json, offsets_reliable,
                model_id, revision, dimensions, window_chars, window_overlap_chars, preprocessing_id,
            )
        finally:
            cursor.close()

    def _construct_indexed_document(
        self, cursor: Any, workspace_id: str, document_id: str, version_id: str,
        generation_id: str, source_path: str, source_sha256: str, media_type: str,
        extractor_name: str, extractor_version: str, chunker_version: str,
        processing_id: str, pages_json: Any, warnings_json: Any,
        offsets_reliable: bool, model_id: str, revision: str, dimensions: int,
        window_chars: int, window_overlap_chars: int, preprocessing_id: str,
    ) -> IndexedDocument:
        pages = tuple(ExtractedPage(**item) for item in _from_json(pages_json))
        document = DocumentVersion(
            workspace_id=workspace_id, document_id=document_id, version_id=version_id,
            processing_id=processing_id,
            source_path=source_path, content_sha256=source_sha256, media_type=media_type,
            extractor_name=extractor_name, extractor_version=extractor_version,
            chunker_version=chunker_version, pages=pages,
            warnings=tuple(_from_json(warnings_json)), offsets_reliable=offsets_reliable,
        )
        cursor.execute(
            """SELECT chunk_id, page_number, start_char, end_char, start_line, end_line,
                      text_content, heading_path_json, offsets_reliable, extractor_name,
                      extractor_version, chunker_version
               FROM nexus_rag_chunks
               WHERE workspace_id = %s AND document_id = %s AND version_id = %s
                 AND processing_id = %s AND generation_id = %s
               ORDER BY page_number NULLS FIRST, start_char NULLS FIRST, chunk_id""",
            (workspace_id, document_id, version_id, processing_id, generation_id),
        )
        chunk_rows = cursor.fetchall()
        chunks = tuple(
            SourceChunk(
                chunk_id=r[0], document_id=document_id, version_id=version_id,
                source_path=source_path, source_sha256=source_sha256,
                extractor_name=r[9], extractor_version=r[10], page_number=r[1],
                start_char=r[2], end_char=r[3], start_line=r[4], end_line=r[5],
                text=r[6], heading_path=tuple(_from_json(r[7])), offsets_reliable=r[8],
                chunker_version=r[11],
            ) for r in chunk_rows
        )
        cursor.execute(
            """SELECT window_id, chunk_id, page_number, start_char, end_char,
                      local_start, local_end, text_content, vector
               FROM nexus_rag_windows
               WHERE workspace_id = %s AND document_id = %s AND version_id = %s
                 AND processing_id = %s AND generation_id = %s
               ORDER BY chunk_id, local_start, window_id""",
            (workspace_id, document_id, version_id, processing_id, generation_id),
        )
        window_rows = cursor.fetchall()
        windows = tuple(
            IndexedWindow(
                window_id=r[0], chunk_id=r[1], page_number=r[2], start_char=r[3], end_char=r[4],
                local_start=r[5], local_end=r[6], text=r[7],
                vector=validate_vector(r[8], dimensions=dimensions),
            ) for r in window_rows
        )
        indexed = IndexedDocument(
            document=document, chunks=chunks, windows=windows,
            embedding_model_id=model_id, embedding_revision=revision,
            embedding_dimensions=dimensions, index_generation_id=generation_id,
            window_chars=window_chars, window_overlap_chars=window_overlap_chars,
            preprocessing_id=preprocessing_id,
        )
        _validate_indexed_document(indexed)
        if indexed.index_generation_id != generation_id:
            raise ValueError("stored index generation identity does not match reconstructed index")
        return indexed

    def delete(self, workspace_id: str, document_id: str) -> bool:
        _validate_workspace_id(workspace_id)
        if not isinstance(document_id, str) or not document_id:
            raise ValueError("document_id must be non-empty text")
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "DELETE FROM nexus_rag_documents WHERE workspace_id = %s AND document_id = %s",
                    (workspace_id, document_id),
                )
                return cursor.rowcount == 1
            finally:
                cursor.close()

    def cleanup_stale(self, workspace_id: str, document_id: str) -> int:
        """Delete inactive source versions/index generations after successful activation."""
        _validate_workspace_id(workspace_id)
        if not isinstance(document_id, str) or not document_id:
            raise ValueError("document_id must be non-empty text")
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """SELECT active_version_id, active_processing_id, active_generation_id
                       FROM nexus_rag_documents
                       WHERE workspace_id = %s AND document_id = %s
                       FOR UPDATE""",
                    (workspace_id, document_id),
                )
                if cursor.fetchone() is None:
                    return 0
                cursor.execute(
                    """DELETE FROM nexus_rag_document_versions v
                       WHERE v.workspace_id = %s AND v.document_id = %s
                         AND (v.version_id, v.processing_id) <> (
                           SELECT d.active_version_id, d.active_processing_id FROM nexus_rag_documents d
                           WHERE d.workspace_id = v.workspace_id AND d.document_id = v.document_id
                         )""",
                    (workspace_id, document_id),
                )
                stale_versions = cursor.rowcount
                cursor.execute(
                    """DELETE FROM nexus_rag_index_generations g
                       WHERE g.workspace_id = %s AND g.document_id = %s
                         AND (g.version_id, g.processing_id, g.generation_id) <> (
                           SELECT d.active_version_id, d.active_processing_id, d.active_generation_id FROM nexus_rag_documents d
                           WHERE d.workspace_id = g.workspace_id AND d.document_id = g.document_id
                         )""",
                    (workspace_id, document_id),
                )
                return stale_versions + max(cursor.rowcount, 0)
            finally:
                cursor.close()

    def record_failure(self, failure: IngestionFailure) -> None:
        _validate_workspace_id(failure.workspace_id)
        if not failure.source_path or not failure.error_type:
            raise ValueError("failure source_path and error_type must be non-empty")
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """INSERT INTO nexus_rag_ingestion_failures
                       (workspace_id, source_path, error_type) VALUES (%s, %s, %s)""",
                    (failure.workspace_id, failure.source_path[:1024], failure.error_type[:256]),
                )
                cursor.execute(
                    """DELETE FROM nexus_rag_ingestion_failures
                       WHERE workspace_id = %s AND failure_id NOT IN (
                         SELECT failure_id FROM nexus_rag_ingestion_failures
                         WHERE workspace_id = %s ORDER BY failure_id DESC LIMIT %s
                       )""",
                    (failure.workspace_id, failure.workspace_id, self.max_failures_per_workspace),
                )
            finally:
                cursor.close()

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        connection = self._connection_factory()
        try:
            if getattr(connection, "autocommit", False):
                raise ValueError("PostgreSQL repository requires autocommit-disabled connections")
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


def candidate_schema_ddl() -> tuple[str, ...]:
    """Return unexecuted DDL for review and conversion into an Alembic migration."""
    return POSTGRES_SCHEMA_DDL


def _generation_id(indexed: IndexedDocument) -> str:
    explicit = indexed.index_generation_id
    if not isinstance(explicit, str) or not re.fullmatch(r"[0-9a-f]{64}", explicit):
        raise ValueError("index_generation_id must be a lowercase SHA-256 hex digest")
    return explicit


def _indexed_payload_sha256(indexed: IndexedDocument) -> str:
    """Hash the complete immutable source/chunk/window payload for generation reuse."""
    return _canonical_payload_sha256(indexed)


def _document_payload_sha256(document: DocumentVersion) -> str:
    """Bind immutable extracted pages and source provenance to a source version."""
    return _canonical_payload_sha256(document)


def _canonical_payload_sha256(value: Any) -> str:
    """Stream canonical JSON into SHA-256 without copying the whole index graph."""
    def encode_dataclass(instance: Any) -> dict[str, Any]:
        if not is_dataclass(instance) or isinstance(instance, type):
            raise TypeError(f"unsupported canonical payload type: {type(instance).__name__}")
        return {field.name: getattr(instance, field.name) for field in fields(instance)}

    encoder = json.JSONEncoder(
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        default=encode_dataclass,
    )
    digest = hashlib.sha256()
    for token in encoder.iterencode(value):
        digest.update(token.encode("utf-8"))
    return digest.hexdigest()


@dataclass(frozen=True)
class PostgresReadLimits:
    """Bounds for full-index reads until a streaming retrieval contract exists."""

    max_documents: int = 250
    max_chunks: int = 20_000
    max_windows: int = 5_000
    max_vector_coordinates: int = 2_000_000
    max_source_chars: int = 20_000_000
    max_index_text_chars: int = 20_000_000

    def __post_init__(self) -> None:
        if any(type(value) is not int or value <= 0 for value in self.__dict__.values()):
            raise ValueError("PostgreSQL read limits must be positive integers")


def _active_predicates(workspace_id: str, selected: RetrievalFilters) -> tuple[list[str], list[Any]]:
    predicates = ["d.workspace_id = %s", "d.active_version_id IS NOT NULL"]
    params: list[Any] = [workspace_id]
    if selected.document_id is not None:
        predicates.append("d.document_id = %s")
        params.append(selected.document_id)
    if selected.page_number is not None:
        predicates.append(
            "EXISTS (SELECT 1 FROM nexus_rag_chunks c WHERE c.workspace_id = d.workspace_id "
            "AND c.document_id = d.document_id AND c.version_id = d.active_version_id "
            "AND c.processing_id = d.active_processing_id AND c.generation_id = d.active_generation_id "
            "AND c.page_number = %s)"
        )
        params.append(selected.page_number)
    return predicates, params


def _enforce_read_limits(totals: Sequence[Any], limits: PostgresReadLimits) -> None:
    docs, chunks, windows, coordinates, source_chars, chunk_chars, window_chars = (
        int(value or 0) for value in totals
    )
    if docs > limits.max_documents:
        raise ValueError("PostgreSQL active result exceeds max_documents read limit")
    if chunks > limits.max_chunks:
        raise ValueError("PostgreSQL active result exceeds max_chunks read limit")
    if windows > limits.max_windows:
        raise ValueError("PostgreSQL active result exceeds max_windows read limit")
    if coordinates > limits.max_vector_coordinates:
        raise ValueError("PostgreSQL active result exceeds max_vector_coordinates read limit")
    if source_chars > limits.max_source_chars:
        raise ValueError("PostgreSQL active result exceeds max_source_chars read limit")
    if chunk_chars + window_chars > limits.max_index_text_chars:
        raise ValueError("PostgreSQL active result exceeds max_index_text_chars read limit")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _from_json(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _execute_batches(cursor: Any, statement: str, rows, *, batch_size: int = 256) -> None:
    """Use a fixed-size parameter buffer so ingestion does not copy a whole index."""
    batch = []
    for row in rows:
        batch.append(row)
        if len(batch) == batch_size:
            cursor.executemany(statement, batch)
            batch.clear()
    if batch:
        cursor.executemany(statement, batch)
