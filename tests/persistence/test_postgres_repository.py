from __future__ import annotations

import unittest

from nexus_ai.documents.types import (
    DocumentVersion,
    ExtractedPage,
    IndexedDocument,
    IndexedWindow,
    RetrievalFilters,
    SourceChunk,
)
from nexus_ai.retrieval.identity import (
    stable_index_generation_id,
    stable_processing_id,
    stable_source_version_id,
)
from nexus_ai.retrieval.postgres_repository import (
    POSTGRES_SCHEMA_DDL,
    PostgresReadLimits,
    PostgresDocumentIndex,
    _generation_id,
)


def _indexed_document() -> IndexedDocument:
    text = "Evidence is 42."
    document_id = "document-a"
    source_hash = "a" * 64
    chunker_version = "c" * 64
    version_id = stable_source_version_id(document_id, source_hash)
    processing_id = stable_processing_id(
        extractor_name="utf8-text", extractor_version="1", media_type="text/plain",
        offsets_reliable=True, chunker_fingerprint=chunker_version,
    )
    model_id = "test/e5"
    revision = "b" * 40
    preproc = "test-preprocessing-v1"
    generation_id = stable_index_generation_id(
        document_id=document_id, source_version_id=version_id, processing_id=processing_id,
        embedding_model_id=model_id, embedding_revision=revision, embedding_dimensions=2,
        chunker_fingerprint=chunker_version, window_chars=20, window_overlap_chars=5,
        preprocessing_id=preproc,
    )
    document = DocumentVersion(
        workspace_id="workspace-a", document_id=document_id, version_id=version_id,
        processing_id=processing_id, source_path="reports/report.txt", content_sha256=source_hash,
        media_type="text/plain", extractor_name="utf8-text", extractor_version="1",
        chunker_version=chunker_version, pages=(ExtractedPage(None, text),),
        warnings=(), offsets_reliable=True,
    )
    chunk = SourceChunk(
        chunk_id="chunk-a", document_id=document.document_id, version_id=document.version_id,
        source_path=document.source_path, source_sha256=document.content_sha256,
        extractor_name=document.extractor_name, extractor_version=document.extractor_version,
        page_number=None, start_char=0, end_char=len(text), start_line=1, end_line=1,
        text=text, heading_path=(), offsets_reliable=True, chunker_version=document.chunker_version,
    )
    window = IndexedWindow(
        window_id="window-a", chunk_id=chunk.chunk_id, page_number=None,
        start_char=0, end_char=len(text), local_start=0, local_end=len(text),
        text=text, vector=(1.0, 0.25),
    )
    return IndexedDocument(
        document=document, chunks=(chunk,), windows=(window,),
        embedding_model_id=model_id, embedding_revision=revision, embedding_dimensions=2,
        index_generation_id=generation_id, window_chars=20, window_overlap_chars=5,
        preprocessing_id=preproc,
    )


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.rowcount = 1
        self._one = None
        self._all = []
        self.closed = False

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split())
        if sql.count("%s") != len(params):
            raise AssertionError(f"placeholder mismatch: {sql.count('%s')} placeholders for {len(params)} params")
        self.connection.calls.append((normalized, tuple(params)))
        if self.connection.fail_on and self.connection.fail_on in normalized:
            raise RuntimeError("injected database failure")
        if normalized.startswith("SELECT active_version_id"):
            self._one = self.connection.active
        elif normalized.startswith("SELECT COUNT(*)"):
            self._one = self.connection.read_totals
        elif normalized.startswith("SELECT d.source_path"):
            self._one = self.connection.metadata_row
        elif normalized.startswith("SELECT chunk_id"):
            self._all = self.connection.chunk_rows
        elif normalized.startswith("SELECT window_id"):
            self._all = self.connection.window_rows
        elif normalized.startswith("SELECT d.workspace_id"):
            self._all = self.connection.active_rows
        elif normalized.startswith("UPDATE nexus_rag_documents"):
            self.connection.active = (params[1], params[2], params[3])
        self.rowcount = 1

    def executemany(self, sql, rows):
        normalized = " ".join(sql.split())
        materialized = list(rows)
        if any(sql.count("%s") != len(row) for row in materialized):
            raise AssertionError("executemany parameter count does not match SQL placeholders")
        self.connection.calls.append((normalized, materialized))
        if self.connection.fail_on and self.connection.fail_on in normalized:
            raise RuntimeError("injected database failure")
        self.rowcount = len(materialized)

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._all

    def fetchmany(self, size):
        self.connection.fetchmany_sizes.append(size)
        rows = self._all[:size]
        self._all = self._all[size:]
        return rows

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, *, active=None, fail_on=None, read_totals=(0, 0, 0, 0, 0, 0, 0)):
        self.active = active
        self.fail_on = fail_on
        self.calls = []
        self.read_totals = read_totals
        self.active_rows = []
        self.metadata_row = None
        self.chunk_rows = []
        self.window_rows = []
        self.fetchmany_sizes = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


class PostgresRepositoryTests(unittest.TestCase):
    def test_candidate_schema_is_workspace_scoped_and_does_not_enable_pgvector(self):
        ddl = "\n".join(POSTGRES_SCHEMA_DDL)
        self.assertIn("PRIMARY KEY (workspace_id, document_id)", ddl)
        self.assertIn("FOREIGN KEY (workspace_id, document_id, version_id, processing_id, generation_id)", ddl)
        self.assertIn("vector double precision[] NOT NULL", ddl)
        self.assertNotIn("CREATE EXTENSION", ddl)
        self.assertNotIn("vector(", ddl)

    def test_activate_persists_generation_before_atomic_pointer_update_and_is_idempotent(self):
        connection = FakeConnection()
        repository = PostgresDocumentIndex(lambda: connection)
        indexed = _indexed_document()

        self.assertTrue(repository.activate(indexed))
        generation_id = _generation_id(indexed)
        self.assertEqual(connection.active, (indexed.document.version_id, indexed.document.processing_id, generation_id))
        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 0)
        self.assertTrue(connection.closed)
        sql = [statement for statement, _ in connection.calls]
        gen_write = next(i for i, statement in enumerate(sql) if statement.startswith("INSERT INTO nexus_rag_index_generations"))
        chunk_write = next(i for i, statement in enumerate(sql) if statement.startswith("INSERT INTO nexus_rag_chunks"))
        window_write = next(i for i, statement in enumerate(sql) if statement.startswith("INSERT INTO nexus_rag_windows"))
        pointer_update = next(i for i, statement in enumerate(sql) if statement.startswith("UPDATE nexus_rag_documents"))
        self.assertLess(gen_write, chunk_write)
        self.assertLess(chunk_write, window_write)
        self.assertLess(window_write, pointer_update)
        generation_params = connection.calls[gen_write][1]
        self.assertEqual(generation_params[4], indexed.index_generation_id)
        self.assertEqual(generation_params[-3:], (indexed.window_chars, indexed.window_overlap_chars,
                                                  indexed.preprocessing_id))

        second = FakeConnection(active=connection.active)
        self.assertFalse(PostgresDocumentIndex(lambda: second).activate(indexed))
        self.assertEqual(len(second.calls), 1)
        self.assertEqual(second.commits, 1)

    def test_index_write_failure_rolls_back_and_never_activates_partial_generation(self):
        connection = FakeConnection(fail_on="INSERT INTO nexus_rag_windows")
        repository = PostgresDocumentIndex(lambda: connection)
        with self.assertRaisesRegex(RuntimeError, "injected"):
            repository.activate(_indexed_document())
        sql = [statement for statement, _ in connection.calls]
        self.assertFalse(any(statement.startswith("UPDATE nexus_rag_documents") for statement in sql))
        self.assertEqual(connection.commits, 0)
        self.assertEqual(connection.rollbacks, 1)
        self.assertTrue(connection.closed)

    def test_list_active_is_workspace_scoped_and_uses_bound_filters(self):
        connection = FakeConnection()
        repository = PostgresDocumentIndex(lambda: connection)
        self.assertEqual(
            repository.list_active("workspace-a", RetrievalFilters(document_id="doc-a", page_number=3)),
            (),
        )
        query, params = next((q, p) for q, p in connection.calls if "d.workspace_id = %s" in q)
        self.assertIn("d.workspace_id = %s", query)
        self.assertIn("d.document_id = %s", query)
        self.assertIn("c.page_number = %s", query)
        self.assertEqual(params, ("workspace-a", "doc-a", 3))
        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.fetchmany_sizes, [1])

    def test_iterator_loads_one_document_at_a_time_and_checks_read_bounds_first(self):
        indexed = _indexed_document()
        doc = indexed.document
        chunk = indexed.chunks[0]
        window = indexed.windows[0]
        generation_id = indexed.index_generation_id
        connection = FakeConnection(read_totals=(1, 1, 1, 2, len(chunk.text), len(chunk.text), len(window.text)))
        connection.active_rows = [(doc.workspace_id, doc.document_id, doc.version_id,
                                   doc.processing_id, generation_id)]
        connection.metadata_row = (
            doc.source_path, doc.content_sha256, doc.media_type, doc.extractor_name,
            doc.extractor_version, doc.chunker_version, doc.processing_id,
            [{"page_number": page.page_number, "text": page.text} for page in doc.pages],
            list(doc.warnings), doc.offsets_reliable, indexed.embedding_model_id,
            indexed.embedding_revision, indexed.embedding_dimensions,
            indexed.window_chars, indexed.window_overlap_chars, indexed.preprocessing_id,
        )
        connection.chunk_rows = [(
            chunk.chunk_id, chunk.page_number, chunk.start_char, chunk.end_char,
            chunk.start_line, chunk.end_line, chunk.text, list(chunk.heading_path),
            chunk.offsets_reliable, chunk.extractor_name, chunk.extractor_version,
            chunk.chunker_version,
        )]
        connection.window_rows = [(
            window.window_id, window.chunk_id, window.page_number, window.start_char,
            window.end_char, window.local_start, window.local_end, window.text, list(window.vector),
        )]
        iterator = PostgresDocumentIndex(lambda: connection).iter_active("workspace-a")
        loaded = tuple(iterator)
        self.assertEqual(loaded, (indexed,))
        self.assertEqual(connection.fetchmany_sizes, [1, 1])
        self.assertEqual(connection.commits, 1)
        self.assertTrue(connection.closed)

        too_many = FakeConnection(read_totals=(1, 1, 1, 2_000_001, 5, 5, 5))
        bounded = PostgresDocumentIndex(
            lambda: too_many,
            read_limits=PostgresReadLimits(max_vector_coordinates=2_000_000),
        )
        with self.assertRaisesRegex(ValueError, "max_vector_coordinates"):
            list(bounded.iter_active("workspace-a"))
        self.assertFalse(any(q.startswith("SELECT d.workspace_id") for q, _ in too_many.calls))
        self.assertEqual(too_many.rollbacks, 1)

    def test_delete_and_cleanup_scope_every_mutation_to_workspace_and_document(self):
        connection = FakeConnection()
        repository = PostgresDocumentIndex(lambda: connection)
        self.assertTrue(repository.delete("workspace-a", "doc-a"))
        query, params = connection.calls[0]
        self.assertIn("workspace_id = %s AND document_id = %s", query)
        self.assertEqual(params, ("workspace-a", "doc-a"))
        self.assertEqual(connection.commits, 1)

        cleanup = FakeConnection(active=("active-version", "active-processing", "active-generation"))
        self.assertEqual(PostgresDocumentIndex(lambda: cleanup).cleanup_stale("workspace-a", "doc-a"), 2)
        self.assertTrue(all(params[:2] == ("workspace-a", "doc-a") for _, params in cleanup.calls))

    def test_failure_recording_truncates_unbounded_error_metadata(self):
        from nexus_ai.documents.types import IngestionFailure

        connection = FakeConnection()
        repository = PostgresDocumentIndex(lambda: connection)
        repository.record_failure(IngestionFailure("workspace-a", "x" * 2000, "E" * 300))
        _, params = connection.calls[0]
        self.assertEqual(len(params[1]), 1024)
        self.assertEqual(len(params[2]), 256)


if __name__ == "__main__":
    unittest.main()
