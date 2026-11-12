"""Opt-in integration tests against a newly created local disposable database.

The suite deliberately requires a dedicated DSN environment variable and an
explicit database-name prefix. It never reads DATABASE_URL, application
settings, or .env files. It creates and drops only its own random schema.
"""
from __future__ import annotations

import hashlib
import ipaddress
import os
import re
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

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
    PostgresDocumentIndex,
    PostgresReadLimits,
)


DSN_ENV = "NEXUS_P4_TEST_DATABASE_URL"
DISPOSABLE_DATABASE_PREFIX = "nexus_ai_p4_it_"
FORBIDDEN_DATABASES = {"nexus_ai", "nexus_ai_p4_test_ff120184bd33"}
EMPTY_DATABASE_QUERY = """SELECT 1
FROM pg_catalog.pg_namespace n
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema', 'public')
  AND n.nspname NOT LIKE 'pg_toast%'
UNION ALL
SELECT 1 FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
UNION ALL
SELECT 1 FROM pg_catalog.pg_proc p
JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public'
UNION ALL
SELECT 1 FROM pg_catalog.pg_type t
JOIN pg_catalog.pg_namespace n ON n.oid = t.typnamespace
WHERE n.nspname = 'public'
UNION ALL
SELECT 1 FROM pg_catalog.pg_collation WHERE collnamespace = 'public'::regnamespace
UNION ALL
SELECT 1 FROM pg_catalog.pg_operator WHERE oprnamespace = 'public'::regnamespace
UNION ALL
SELECT 1 FROM pg_catalog.pg_opclass WHERE opcnamespace = 'public'::regnamespace
UNION ALL
SELECT 1 FROM pg_catalog.pg_opfamily WHERE opfnamespace = 'public'::regnamespace
UNION ALL
SELECT 1 FROM pg_catalog.pg_conversion WHERE connamespace = 'public'::regnamespace
UNION ALL
SELECT 1 FROM pg_catalog.pg_ts_config WHERE cfgnamespace = 'public'::regnamespace
UNION ALL
SELECT 1 FROM pg_catalog.pg_ts_dict WHERE dictnamespace = 'public'::regnamespace
UNION ALL
SELECT 1 FROM pg_catalog.pg_ts_parser WHERE prsnamespace = 'public'::regnamespace
UNION ALL
SELECT 1 FROM pg_catalog.pg_ts_template WHERE tmplnamespace = 'public'::regnamespace
UNION ALL
SELECT 1 FROM pg_catalog.pg_statistic_ext WHERE stxnamespace = 'public'::regnamespace
UNION ALL
SELECT 1 FROM pg_catalog.pg_extension WHERE extname <> 'plpgsql'
UNION ALL
SELECT 1 FROM pg_catalog.pg_largeobject_metadata
UNION ALL
SELECT 1 FROM pg_catalog.pg_event_trigger
UNION ALL
SELECT 1 FROM pg_catalog.pg_publication
UNION ALL
SELECT 1 FROM pg_catalog.pg_subscription
LIMIT 1"""


def _assert_empty_database(connection) -> None:
    """Fail closed if the opt-in target contains user schemas or objects."""
    cursor = connection.cursor()
    try:
        cursor.execute(EMPTY_DATABASE_QUERY)
        if cursor.fetchone() is not None:
            raise RuntimeError(
                "integration target contains user database objects; refusing test schema creation"
            )
    finally:
        cursor.close()


def _indexed(
    *, workspace: str = "workspace-a", document_id: str = "doc-a", text: str,
) -> IndexedDocument:
    source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    chunker_fingerprint = hashlib.sha256(b"integration-test-chunker-v1").hexdigest()
    version_id = stable_source_version_id(document_id, source_hash)
    processing_id = stable_processing_id(
        extractor_name="utf8-text", extractor_version="1", media_type="text/plain",
        offsets_reliable=True, chunker_fingerprint=chunker_fingerprint,
    )
    model_id = "test/multilingual-e5"
    model_revision = "b" * 40
    preprocessing_id = "test-preprocessing-v1"
    window_chars = 512
    window_overlap = 64
    generation_id = stable_index_generation_id(
        document_id=document_id,
        source_version_id=version_id,
        processing_id=processing_id,
        embedding_model_id=model_id,
        embedding_revision=model_revision,
        embedding_dimensions=2,
        chunker_fingerprint=chunker_fingerprint,
        window_chars=window_chars,
        window_overlap_chars=window_overlap,
        preprocessing_id=preprocessing_id,
    )
    document = DocumentVersion(
        workspace_id=workspace,
        document_id=document_id,
        version_id=version_id,
        processing_id=processing_id,
        source_path=f"docs/{document_id}.txt",
        content_sha256=source_hash,
        media_type="text/plain",
        extractor_name="utf8-text",
        extractor_version="1",
        chunker_version=chunker_fingerprint,
        pages=(ExtractedPage(None, text),),
        warnings=(),
        offsets_reliable=True,
    )
    chunk = SourceChunk(
        chunk_id="chunk-" + source_hash[:16],
        document_id=document_id,
        version_id=version_id,
        source_path=document.source_path,
        source_sha256=source_hash,
        extractor_name="utf8-text",
        extractor_version="1",
        page_number=None,
        start_char=0,
        end_char=len(text),
        start_line=1,
        end_line=1,
        text=text,
        heading_path=(),
        offsets_reliable=True,
        chunker_version=chunker_fingerprint,
    )
    window = IndexedWindow(
        window_id="window-" + source_hash[:16],
        chunk_id=chunk.chunk_id,
        page_number=None,
        start_char=0,
        end_char=len(text),
        local_start=0,
        local_end=len(text),
        text=text,
        vector=(1.0, 0.25),
    )
    return IndexedDocument(
        document=document,
        chunks=(chunk,),
        windows=(window,),
        embedding_model_id=model_id,
        embedding_revision=model_revision,
        embedding_dimensions=2,
        index_generation_id=generation_id,
        window_chars=window_chars,
        window_overlap_chars=window_overlap,
        preprocessing_id=preprocessing_id,
    )


class PostgresLiveIntegrationTests(unittest.TestCase):
    """Runs only when an explicitly named loopback integration DB is configured."""

    @classmethod
    def setUpClass(cls):
        dsn = os.environ.get(DSN_ENV)
        if not dsn:
            raise unittest.SkipTest(f"set {DSN_ENV} to opt into disposable PostgreSQL integration tests")
        try:
            import psycopg
            from psycopg.conninfo import conninfo_to_dict
        except ImportError as exc:
            raise unittest.SkipTest("psycopg is unavailable for live PostgreSQL integration tests") from exc

        params = conninfo_to_dict(dsn)
        database = params.get("dbname") or params.get("database") or ""
        host = params.get("host") or ""
        hostaddr = params.get("hostaddr") or ""
        if database in FORBIDDEN_DATABASES or not database.startswith(DISPOSABLE_DATABASE_PREFIX):
            raise RuntimeError(
                f"{DSN_ENV} must target a newly created database named {DISPOSABLE_DATABASE_PREFIX}<suffix>"
            )
        if not re.fullmatch(r"nexus_ai_p4_it_[a-zA-Z0-9_]{4,48}", database):
            raise RuntimeError("integration database name does not satisfy the strict disposable-name pattern")
        loopback = {"localhost", "127.0.0.1", "::1"}
        if host and host not in loopback:
            raise RuntimeError("integration DSN host must be localhost or a loopback address")
        if not host:
            try:
                if not hostaddr or not ipaddress.ip_address(hostaddr).is_loopback:
                    raise RuntimeError("integration DSN must explicitly target a loopback PostgreSQL host")
            except ValueError as exc:
                raise RuntimeError("integration DSN must explicitly target a loopback PostgreSQL host") from exc
        if hostaddr and not ipaddress.ip_address(hostaddr).is_loopback:
            raise RuntimeError("integration DSN hostaddr must be loopback")

        cls._psycopg = psycopg
        cls._base_params = params
        cls._schema = "p4_it_" + os.urandom(8).hex()
        cls._schema_created = False
        # Prefix and loopback checks are not enough: a previously used test DB
        # may still contain application data. Inspect only PostgreSQL catalog
        # metadata before issuing any DDL, and reject pre-existing user objects.
        with psycopg.connect(**params) as connection:
            _assert_empty_database(connection)
        with psycopg.connect(**params) as connection:
            with connection.cursor() as cursor:
                cursor.execute(f'CREATE SCHEMA "{cls._schema}"')
                cls._schema_created = True
                cursor.execute(f'SET search_path TO "{cls._schema}"')
                for statement in POSTGRES_SCHEMA_DDL:
                    cursor.execute(statement)

    @classmethod
    def tearDownClass(cls):
        if not getattr(cls, "_schema_created", False):
            return
        with cls._psycopg.connect(**cls._base_params) as connection:
            with connection.cursor() as cursor:
                cursor.execute(f'DROP SCHEMA "{cls._schema}" CASCADE')

    @classmethod
    def repository(cls, *, limits: PostgresReadLimits | None = None) -> PostgresDocumentIndex:
        params = dict(cls._base_params)
        params["options"] = f"-csearch_path={cls._schema}"
        return PostgresDocumentIndex(
            lambda: cls._psycopg.connect(**params), read_limits=limits,
        )

    def test_restart_safe_idempotency_round_trip_and_workspace_isolation(self):
        indexed = _indexed(text="revenue evidence 42")
        first_process = self.repository()
        self.assertTrue(first_process.activate(indexed))

        # A fresh repository instance models a process restart; replaying an
        # already-active source/index generation remains idempotent in storage.
        restarted = self.repository()
        self.assertFalse(restarted.activate(indexed))
        self.assertEqual(restarted.get_active("workspace-a", "doc-a"), indexed)

        other_workspace = _indexed(workspace="workspace-b", text="private other workspace")
        restarted.activate(other_workspace)
        self.assertEqual([row.document.workspace_id for row in restarted.list_active("workspace-a")], ["workspace-a"])
        self.assertEqual([row.document.workspace_id for row in restarted.list_active("workspace-b")], ["workspace-b"])

    def test_replacement_returns_only_active_version_and_delete_cascades(self):
        repository = self.repository()
        original = _indexed(text="old source value")
        replacement = _indexed(text="new source value")
        repository.activate(original)
        repository.activate(replacement)

        active = repository.get_active("workspace-a", "doc-a")
        self.assertEqual(active.document.version_id, replacement.document.version_id)
        self.assertEqual([row.document.version_id for row in repository.list_active("workspace-a")],
                         [replacement.document.version_id])
        self.assertTrue(repository.delete("workspace-a", "doc-a"))
        self.assertEqual(repository.list_active("workspace-a"), ())
        self.assertFalse(repository.delete("workspace-a", "doc-a"))

        params = dict(self._base_params)
        with self._psycopg.connect(**params) as connection:
            with connection.cursor() as cursor:
                cursor.execute(f'SET search_path TO "{self._schema}"')
                for table in ("nexus_rag_document_versions", "nexus_rag_index_generations",
                              "nexus_rag_chunks", "nexus_rag_windows"):
                    cursor.execute(f"SELECT count(*) FROM {table} WHERE workspace_id = %s AND document_id = %s",
                                   ("workspace-a", "doc-a"))
                    self.assertEqual(cursor.fetchone()[0], 0, table)

    def test_database_trigger_failure_rolls_back_and_preserves_active_version(self):
        repository = self.repository()
        original = _indexed(text="known-good original")
        repository.activate(original)
        connection_params = dict(self._base_params)
        try:
            with self._psycopg.connect(**connection_params) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(f'SET search_path TO "{self._schema}"')
                    # Make this test safe to rerun within a reused integration
                    # schema if an earlier process was interrupted mid-cleanup.
                    cursor.execute("DROP TRIGGER IF EXISTS reject_window ON nexus_rag_windows")
                    cursor.execute("DROP FUNCTION IF EXISTS reject_window_insert()")
                    cursor.execute(
                        """CREATE FUNCTION reject_window_insert() RETURNS trigger AS $$
                           BEGIN RAISE EXCEPTION 'injected integration failure'; END;
                           $$ LANGUAGE plpgsql"""
                    )
                    cursor.execute(
                        "CREATE TRIGGER reject_window BEFORE INSERT ON nexus_rag_windows "
                        "FOR EACH ROW EXECUTE FUNCTION reject_window_insert()"
                    )
            with self.assertRaisesRegex(self._psycopg.Error, "injected integration failure"):
                repository.activate(_indexed(text="candidate that must roll back"))
            self.assertEqual(repository.get_active("workspace-a", "doc-a"), original)
        finally:
            # The trigger intentionally raises, but its DDL was committed in a
            # separate connection. Always remove both objects from the
            # class-scoped schema so later tests see an unmodified repository.
            with self._psycopg.connect(**connection_params) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(f'SET search_path TO "{self._schema}"')
                    cursor.execute("DROP TRIGGER IF EXISTS reject_window ON nexus_rag_windows")
                    cursor.execute("DROP FUNCTION IF EXISTS reject_window_insert()")
                    cursor.execute(
                        """SELECT EXISTS (
                               SELECT 1 FROM pg_catalog.pg_trigger t
                               JOIN pg_catalog.pg_class c ON c.oid = t.tgrelid
                               JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                               WHERE n.nspname = %s AND t.tgname = %s AND NOT t.tgisinternal
                           ), EXISTS (
                               SELECT 1 FROM pg_catalog.pg_proc p
                               JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
                               WHERE n.nspname = %s AND p.proname = %s
                           )""",
                        (self._schema, "reject_window", self._schema, "reject_window_insert"),
                    )
                    self.assertEqual(cursor.fetchone(), (False, False))

    def test_deferred_active_pointer_foreign_key_rejects_missing_generation(self):
        params = dict(self._base_params)
        params["options"] = f"-csearch_path={self._schema}"
        with self.assertRaises(self._psycopg.errors.ForeignKeyViolation):
            with self._psycopg.connect(**params) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """INSERT INTO nexus_rag_documents
                           (workspace_id, document_id, source_path, active_version_id,
                            active_processing_id, active_generation_id)
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                        ("workspace-fk", "doc-fk", "docs/fk.txt", "missing-version",
                         "a" * 64, "b" * 64),
                    )
        repository = self.repository()
        self.assertIsNone(repository.get_active("workspace-fk", "doc-fk"))

    def test_preflight_read_limits_and_document_page_filters(self):
        repository = self.repository()
        repository.activate(_indexed(document_id="one", text="first document"))
        repository.activate(_indexed(document_id="two", text="second document"))
        bounded = self.repository(limits=PostgresReadLimits(max_documents=1))
        with self.assertRaisesRegex(ValueError, "max_documents"):
            list(bounded.iter_active("workspace-a"))
        self.assertEqual([row.document.document_id for row in repository.list_active(
            "workspace-a", filters=RetrievalFilters(document_id="two"),
        )], ["two"])

    def test_concurrent_replacements_and_readers_observe_complete_generations(self):
        repository = self.repository()
        repository.activate(_indexed(text="generation 0 is complete"))
        barrier = threading.Barrier(5)

        def replace(number: int):
            barrier.wait(timeout=10)
            for revision in range(3):
                repository.activate(_indexed(text=f"generation {number}-{revision} is complete"))

        def read_many(_number: int):
            barrier.wait(timeout=10)
            observed = []
            for _ in range(20):
                row = repository.get_active("workspace-a", "doc-a")
                self.assertEqual(len(row.chunks), 1)
                self.assertEqual(row.chunks[0].text, row.document.pages[0].text)
                self.assertEqual(row.windows[0].text, row.chunks[0].text)
                observed.append(row.document.version_id)
            return observed

        with ThreadPoolExecutor(max_workers=5) as pool:
            writes = [pool.submit(replace, n) for n in (1, 2)]
            reads = [pool.submit(read_many, n) for n in range(3)]
            for future in writes + reads:
                future.result(timeout=45)
        final = repository.get_active("workspace-a", "doc-a")
        self.assertEqual(final.chunks[0].text, final.document.pages[0].text)


class _FakeGuardCursor:
    def __init__(self, row):
        self.row = row
        self.sql = None
        self.closed = False

    def execute(self, sql):
        self.sql = sql

    def fetchone(self):
        return self.row

    def close(self):
        self.closed = True


class _FakeGuardConnection:
    def __init__(self, row):
        self.result = _FakeGuardCursor(row)

    def cursor(self):
        return self.result


class DisposableDatabaseGuardTests(unittest.TestCase):

    def test_empty_database_metadata_check_is_read_only_and_closes_cursor(self):
        connection = _FakeGuardConnection(None)
        _assert_empty_database(connection)
        self.assertIn("FROM pg_catalog.pg_namespace", connection.result.sql)
        self.assertIn("FROM pg_catalog.pg_class", connection.result.sql)
        self.assertIn("FROM pg_catalog.pg_proc", connection.result.sql)
        self.assertIn("FROM pg_catalog.pg_type", connection.result.sql)
        self.assertTrue(connection.result.closed)

    def test_existing_user_object_prevents_setup(self):
        connection = _FakeGuardConnection(("public", "workspace_tasks"))
        with self.assertRaisesRegex(RuntimeError, "contains user database objects"):
            _assert_empty_database(connection)
        self.assertTrue(connection.result.closed)


if __name__ == "__main__":
    unittest.main()
