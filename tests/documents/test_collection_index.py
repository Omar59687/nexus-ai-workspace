"""Model-free durable collection lifecycle tests; no live database is used."""
from __future__ import annotations

import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path

from nexus_ai.documents.collection_index import CollectionIndexService
from nexus_ai.documents.collection_types import CollectionIndexLimits
from nexus_ai.documents.types import ExtractedPage, ExtractionResult
from nexus_ai.retrieval.collection_repository import (
    COLLECTION_SCHEMA_DDL,
    InMemoryCollectionIndexRepository,
    PostgresCollectionIndexRepository,
    _json,
    _payload_sha256,
)


def item(path: str, company: str = "Mobily", year: int = 2025) -> dict[str, object]:
    return {"path": path, "company": company, "year": year}


class TextExtractor:
    name = "fixture-text"
    version = "1"
    media_type = "text/plain"

    def extract(self, content: bytes, *, source_path: str) -> ExtractionResult:
        return ExtractionResult(self.name, self.version, self.media_type,
                                (ExtractedPage(None, content.decode("utf-8")),))


class FakeCursor:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection
        self.rowcount = 1
        self._one = None
        self.closed = False

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split())
        if sql.count("%s") != len(params):
            raise AssertionError(f"placeholder mismatch: {sql.count('%s')} placeholders for {len(params)} params")
        self.connection.calls.append((normalized, tuple(params)))
        if self.connection.fail_on and self.connection.fail_on in normalized:
            raise RuntimeError("injected database failure")
        if normalized.startswith("SELECT d.active_version_id"):
            self._one = (self.connection.active or (None, None)) if self.connection.exists else None
        elif normalized.startswith("SELECT d.workspace_id"):
            self._one = self.connection.read_document_row
        elif normalized.startswith("SELECT chunk_id, source_path"):
            self.connection._all = self.connection.read_chunk_rows
        elif normalized.startswith("SELECT COUNT(*)"):
            self._one = (0,)
        elif normalized.startswith("INSERT INTO nexus_collection_documents"):
            self.connection.exists = True
        elif normalized.startswith("INSERT INTO nexus_collection_versions"):
            self.rowcount = 1
            self.connection.pending_payload = params[6]
        elif normalized.startswith("UPDATE nexus_collection_documents"):
            self.connection.active = (params[1], params[2], self.connection.pending_payload)
        else:
            self.rowcount = 1

    def executemany(self, sql, rows):
        normalized = " ".join(sql.split())
        materialized = list(rows)
        if any(sql.count("%s") != len(row) for row in materialized):
            raise AssertionError("executemany parameter count mismatch")
        self.connection.calls.append((normalized, materialized))
        if self.connection.fail_on and self.connection.fail_on in normalized:
            raise RuntimeError("injected database failure")
        self.rowcount = len(materialized)

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self.connection._all

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, *, active=None, fail_on=None):
        self.active = active
        self.exists = active is not None
        self.fail_on = fail_on
        self.calls = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.cursor_instance = None
        self.pending_payload = None
        self.original_active = active
        self.original_exists = self.exists
        self.read_document_row = None
        self.read_chunk_rows = []
        self._all = []

    def cursor(self):
        self.cursor_instance = FakeCursor(self)
        return self.cursor_instance

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1
        self.active = self.original_active
        self.exists = self.original_exists

    def close(self):
        self.closed = True


class CollectionIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "reports"
        self.root.mkdir()
        self.repo = InMemoryCollectionIndexRepository()
        self.service = CollectionIndexService(
            approved_root=self.root,
            repository=self.repo,
            extractors={".txt": TextExtractor()},
        )

    def write(self, name: str, text: str) -> None:
        (self.root / name).write_text(text, encoding="utf-8")

    def index(self, entries, *, workspace="workspace-a"):
        return self.service.index(workspace, entries)

    def test_indexes_only_selected_text_and_preserves_source_offsets(self):
        self.write("selected.txt", "Revenue 42\nعربي ١٢٣")
        self.write("not-selected.txt", "must not be read")
        result = self.index([item("selected.txt")])
        self.assertEqual((result["status"], result["indexed_count"]), ("PASS", 1))
        active = self.repo.get_active("workspace-a", result["documents"][0]["document_id"])
        self.assertIsNotNone(active)
        self.assertEqual("".join(chunk.text for chunk in active.chunks), active.document.pages[0].text)
        for chunk in active.chunks:
            self.assertEqual(active.document.pages[0].text[chunk.start_char:chunk.end_char], chunk.text)
        self.assertNotIn("must not be read", "".join(chunk.text for chunk in active.chunks))

    def test_same_file_reingestion_is_idempotent_and_duplicate_manifest_is_rejected(self):
        self.write("a.txt", "stable source")
        first = self.index([item("a.txt")])
        second = self.index([item("a.txt")])
        self.assertEqual(first["documents"][0]["version_id"], second["documents"][0]["version_id"])
        self.assertEqual((second["indexed_count"], second["unchanged_count"]), (0, 1))
        with self.assertRaisesRegex(ValueError, "duplicate path"):
            self.index([item("a.txt"), item("a.txt")])

    def test_changed_source_replaces_active_version_atomically(self):
        self.write("a.txt", "old source")
        first = self.index([item("a.txt")])
        old = self.repo.get_active("workspace-a", first["documents"][0]["document_id"])
        self.write("a.txt", "new source")
        second = self.index([item("a.txt")])
        current = self.repo.get_active("workspace-a", first["documents"][0]["document_id"])
        self.assertNotEqual(old.document.version_id, current.document.version_id)
        self.assertEqual(second["documents"][0]["status"], "indexed")
        self.assertEqual(current.chunks[0].text, "new source")

    def test_identical_bytes_at_different_paths_remain_separate_documents(self):
        self.write("one.txt", "same bytes")
        self.write("two.txt", "same bytes")
        result = self.index([item("one.txt"), item("two.txt")])
        ids = [row["document_id"] for row in result["documents"]]
        self.assertEqual(result["indexed_count"], 2)
        self.assertNotEqual(ids[0], ids[1])
        self.assertEqual(self.repo.get_active("workspace-a", ids[0]).document.content_sha256,
                         self.repo.get_active("workspace-a", ids[1]).document.content_sha256)

    def test_one_failed_document_does_not_block_following_documents(self):
        self.write("bad.txt", "invalid")
        self.write("good.txt", "valid")
        class Broken:
            name = "broken"
            version = "1"
            media_type = "text/plain"
            def extract(self, content, *, source_path):
                if source_path == "bad.txt":
                    raise RuntimeError("secret source must not appear")
                return TextExtractor().extract(content, source_path=source_path)
        service = CollectionIndexService(
            approved_root=self.root,
            repository=self.repo,
            extractors={".txt": Broken()},
        )
        result = service.index("workspace-a", [item("bad.txt"), item("good.txt")])
        self.assertEqual((result["status"], result["blocked_count"], result["indexed_count"]),
                         ("PARTIAL", 1, 1))
        self.assertEqual(result["documents"][0]["reason"], "extraction_or_persistence_failed")
        self.assertNotIn("secret source", str(result))
        self.assertEqual(len(self.repo.failures()), 1)

    def test_repository_failure_isolated_and_later_document_still_commits(self):
        self.write("first.txt", "first payload")
        self.write("second.txt", "second payload")

        class FailFirstRepository:
            def activate(inner_self, indexed):
                if indexed.document.source_path == "first.txt":
                    raise RuntimeError("private database detail")
                return self.repo.activate(indexed)

            def get_active(inner_self, workspace_id, document_id):
                return self.repo.get_active(workspace_id, document_id)

            def delete(inner_self, workspace_id, document_id):
                return self.repo.delete(workspace_id, document_id)

            def record_failure(inner_self, failure):
                self.repo.record_failure(failure)

        service = CollectionIndexService(
            approved_root=self.root,
            repository=FailFirstRepository(),
            extractors={".txt": TextExtractor()},
        )
        result = service.index("workspace-a", [item("first.txt"), item("second.txt")])
        self.assertEqual((result["blocked_count"], result["indexed_count"]), (1, 1))
        self.assertEqual(result["documents"][0]["reason"], "extraction_or_persistence_failed")
        self.assertNotIn("private database detail", str(result))
        self.assertIsNotNone(self.repo.get_active("workspace-a", result["documents"][1]["document_id"]))

    def test_delete_removes_active_document(self):
        self.write("a.txt", "delete me")
        result = self.index([item("a.txt")])
        document_id = result["documents"][0]["document_id"]
        self.assertTrue(self.repo.delete("workspace-a", document_id))
        self.assertIsNone(self.repo.get_active("workspace-a", document_id))
        self.assertFalse(self.repo.delete("workspace-a", document_id))

    def test_lowered_byte_limits_are_enforced_per_file_and_across_collection(self):
        self.write("one.txt", "1234")
        self.write("two.txt", "5678")
        small_repo = InMemoryCollectionIndexRepository()
        limits = CollectionIndexLimits(max_file_bytes=4, max_total_bytes=6)
        service = CollectionIndexService(
            approved_root=self.root,
            repository=small_repo,
            extractors={".txt": TextExtractor()},
            limits=limits,
        )
        result = service.index("workspace-a", [item("one.txt"), item("two.txt")])
        self.assertEqual(result["documents"][0]["status"], "indexed")
        self.assertEqual(result["documents"][1]["status"], "blocked")
        self.assertEqual(result["blocked_count"], 1)

    def test_in_memory_activation_rejects_same_generation_with_conflicting_payload(self):
        self.write("a.txt", "consistent")
        result = self.index([item("a.txt")])
        active = self.repo.get_active("workspace-a", result["documents"][0]["document_id"])
        conflicting_document = replace(active.document, pages=(ExtractedPage(None, "forged"),))
        conflicting_chunk = replace(active.chunks[0], end_char=6, text="forged")
        conflicting = replace(active, document=conflicting_document, chunks=(conflicting_chunk,))
        with self.assertRaisesRegex(ValueError, "conflicting"):
            self.repo.activate(conflicting)


class PostgresCollectionRepositoryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "a.txt").write_text("Revenue 42", encoding="utf-8")
        self.memory = InMemoryCollectionIndexRepository()
        self.service = CollectionIndexService(
            approved_root=self.root, repository=self.memory,
            extractors={".txt": TextExtractor()},
        )
        self.indexed = self.service.index("workspace-a", [item("a.txt")])
        self.document_id = self.indexed["documents"][0]["document_id"]
        self.record = self.memory.get_active("workspace-a", self.document_id)
        self.connection = FakeConnection()

    def _record(self):
        return self.record

    def test_postgres_candidate_ddl_is_inert_and_has_no_embedding_columns(self):
        ddl = "\n".join(COLLECTION_SCHEMA_DDL)
        self.assertIn("nexus_collection_documents", ddl)
        self.assertIn("nexus_collection_chunks", ddl)
        self.assertIn("active_version_id", ddl)
        self.assertIn("pages_json", ddl)
        self.assertNotIn("vector", ddl.casefold())
        self.assertNotIn("CREATE EXTENSION", ddl)

    def test_activation_persists_text_and_flips_pointer_after_chunks(self):
        record = self._record()
        repository = PostgresCollectionIndexRepository(lambda: self.connection)
        self.assertTrue(repository.activate(record))
        statements = [sql for sql, _ in self.connection.calls]
        chunk_write = next(i for i, sql in enumerate(statements) if sql.startswith("INSERT INTO nexus_collection_chunks"))
        pointer_update = next(i for i, sql in enumerate(statements) if sql.startswith("UPDATE nexus_collection_documents"))
        self.assertLess(chunk_write, pointer_update)
        chunk_params = self.connection.calls[chunk_write][1][0]
        self.assertIn("Revenue 42", chunk_params)
        self.assertEqual(self.connection.commits, 1)
        self.assertEqual(self.connection.rollbacks, 0)
        self.assertTrue(self.connection.closed)

    def test_active_same_generation_is_idempotent(self):
        record = self._record()
        self.connection.active = (record.document.version_id, record.document.processing_id,
                                  _payload_sha256(record))
        self.connection.exists = True
        self.assertFalse(PostgresCollectionIndexRepository(lambda: self.connection).activate(record))
        writes = [sql for sql, _ in self.connection.calls if sql.startswith("INSERT")]
        self.assertEqual(writes, [])
        self.assertEqual(self.connection.commits, 1)

    def test_get_active_reconstructs_persisted_page_and_chunk_provenance(self):
        record = self._record()
        doc = record.document
        self.connection.exists = True
        self.connection.active = (doc.version_id, doc.processing_id, _payload_sha256(record))
        self.connection.read_document_row = (
            doc.workspace_id, doc.document_id, doc.version_id, doc.processing_id,
            doc.source_path, doc.content_sha256, doc.media_type, doc.extractor_name,
            doc.extractor_version, doc.chunker_version,
            _json([asdict(page) for page in doc.pages]), _json(doc.warnings),
            doc.offsets_reliable, _payload_sha256(record),
        )
        chunk = record.chunks[0]
        self.connection.read_chunk_rows = [(
            chunk.chunk_id, chunk.source_path, chunk.source_sha256, chunk.extractor_name,
            chunk.extractor_version, chunk.page_number, chunk.start_char, chunk.end_char,
            chunk.start_line, chunk.end_line, chunk.text, _json(chunk.heading_path),
            chunk.offsets_reliable, chunk.chunker_version,
        )]
        loaded = PostgresCollectionIndexRepository(lambda: self.connection).get_active(
            doc.workspace_id, doc.document_id
        )
        self.assertEqual(loaded, record)
        self.assertEqual(self.connection.commits, 1)

    def test_invalid_autocommit_connection_is_rejected_for_atomicity(self):
        class AutoCommitConnection(FakeConnection):
            autocommit = True

        with self.assertRaisesRegex(ValueError, "autocommit"):
            PostgresCollectionIndexRepository(lambda: AutoCommitConnection()).activate(self._record())

    def test_chunk_write_failure_rolls_back_before_active_pointer_update(self):
        record = self._record()
        self.connection.fail_on = "INSERT INTO nexus_collection_chunks"
        with self.assertRaisesRegex(RuntimeError, "injected"):
            PostgresCollectionIndexRepository(lambda: self.connection).activate(record)
        statements = [sql for sql, _ in self.connection.calls]
        self.assertFalse(any(sql.startswith("UPDATE nexus_collection_documents") for sql in statements))
        self.assertEqual(self.connection.commits, 0)
        self.assertEqual(self.connection.rollbacks, 1)
        self.assertTrue(self.connection.closed)

    def test_failure_after_pointer_update_rolls_back_to_previous_version(self):
        old = self._record()
        previous = (old.document.version_id, old.document.processing_id, _payload_sha256(old))
        self.connection = FakeConnection(active=previous, fail_on="DELETE FROM nexus_collection_versions")
        (self.root / "a.txt").write_text("replacement text", encoding="utf-8")
        self.service.index("workspace-a", [item("a.txt")])
        replacement = self.memory.get_active("workspace-a", self.document_id)
        self.assertNotEqual(old.document.version_id, replacement.document.version_id)
        with self.assertRaisesRegex(RuntimeError, "injected"):
            PostgresCollectionIndexRepository(lambda: self.connection).activate(replacement)
        self.assertEqual(self.connection.active, previous)
        self.assertEqual(self.connection.commits, 0)
        self.assertEqual(self.connection.rollbacks, 1)


if __name__ == "__main__":
    unittest.main()
