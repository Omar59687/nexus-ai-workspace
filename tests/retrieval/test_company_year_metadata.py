"""Model-free company/year filtering contract and fail-closed regressions."""
from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from nexus_ai.documents.chunking import ChunkingConfig, SourceAwareChunker
from nexus_ai.documents.service import DocumentIngestionService
from nexus_ai.retrieval.company_metadata import (
    CompanyYearDocument,
    CompanyYearFilter,
    CompanyYearMetadataCatalog,
    MetadataIntegrityError,
)
from nexus_ai.retrieval.repository import InMemoryDocumentIndex
from nexus_ai.retrieval.service import RetrievalService
from tests.documents.test_ingestion import FakeEmbedder


class CompanyYearMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repository = InMemoryDocumentIndex()
        self.embedder = FakeEmbedder()
        self.ingestion = DocumentIngestionService(
            approved_root=self.root,
            repository=self.repository,
            embedder=self.embedder,
            chunker=SourceAwareChunker(ChunkingConfig(max_chars=100, overlap_chars=0)),
        )
        self.catalog = CompanyYearMetadataCatalog()
        self.retriever = RetrievalService(
            repository=self.repository,
            embedder=self.embedder,
            company_metadata=self.catalog,
        )
        self.companies = {
            "acme": ("Acme Holdings", "أكمي القابضة"),
            "mobily": ("Mobily", "شركة اتحاد اتصالات موبايلي"),
        }
        self.docs = {
            "acme24": self._ingest("acme-2024.txt", "Acme Holdings 2024 revenue was 41 million.", "workspace-a"),
            "acme25": self._ingest("acme-2025.txt", "Acme Holdings 2025 revenue was 49 million.", "workspace-a"),
            "mobily24": self._ingest("mobily-2024.txt", "شركة اتحاد اتصالات موبايلي 2024 الإيرادات 77 مليون.", "workspace-a"),
            "mobily25": self._ingest("mobily-2025.txt", "Mobily 2025 revenue was 88 million.", "workspace-a"),
        }
        self._register()

    def _ingest(self, relative_path, content, workspace):
        (self.root / relative_path).write_text(content, encoding="utf-8")
        return self.ingestion.ingest(workspace, relative_path)

    def _metadata(self, result, workspace="workspace-a", collection="annual-reports", company_id=None, year=None,
                  duplicate_of=None):
        active = self.repository.get_active(workspace, result.document_id)
        if company_id is None:
            company_id = "mobily" if "mobily" in active.document.source_path else "acme"
        if year is None:
            year = 2025 if "2025" in active.document.source_path else 2024
        return CompanyYearDocument(
            workspace_id=workspace,
            collection_id=collection,
            document_id=result.document_id,
            document_version_id=result.version_id,
            source_path=active.document.source_path,
            source_sha256=result.content_sha256,
            company_id=company_id,
            financial_year=year,
            duplicate_of_document_id=duplicate_of,
        )

    def _register(self):
        self._register_rows([self._metadata(result) for result in self.docs.values()])

    def _register_rows(self, rows, *, workspace="workspace-a", companies=None):
        return self.catalog.replace_collection(
            workspace_id=workspace,
            collection_id="annual-reports",
            companies=companies or self.companies,
            documents=rows,
        )

    def _retrieve(self, company=None, year=None, *, workspace="workspace-a", strategy="bm25_raw"):
        return self.retriever.retrieve(
            "revenue الإيرادات", workspace_id=workspace, strategy=strategy, top_k=20,
            company_year_filter=CompanyYearFilter("annual-reports", company, year),
        )

    def test_metadata_revision_change_during_bm25_scan_fails_closed(self):
        from unittest.mock import patch
        from dataclasses import replace

        original_iterator = self.repository.iter_active
        initial_snapshot = self.catalog.get("workspace-a", "annual-reports")

        def changed_iterator(workspace_id, filters=None):
            source = original_iterator(workspace_id, filters)
            def rows():
                # Simulate a concurrent metadata reassignment with the
                # underlying document versions unchanged.
                reassigned = [
                    replace(row, financial_year=2023)
                    if row.document_id == self.docs["acme24"].document_id
                    else row for row in initial_snapshot.documents
                ]
                self._register_rows(reassigned)
                yield from source
            return rows()

        with patch.object(self.repository, "iter_active", side_effect=changed_iterator):
            with self.assertRaises(MetadataIntegrityError):
                self._retrieve("Acme Holdings", 2024, strategy="bm25_raw")

    def test_metadata_revision_change_during_vector_scan_fails_closed(self):
        from unittest.mock import patch
        from dataclasses import replace

        original_iterator = self.repository.iter_active
        initial_snapshot = self.catalog.get("workspace-a", "annual-reports")

        def changed_iterator(workspace_id, filters=None):
            source = original_iterator(workspace_id, filters)
            def rows():
                reassigned = [
                    replace(row, financial_year=2023)
                    if row.document_id == self.docs["mobily25"].document_id
                    else row for row in initial_snapshot.documents
                ]
                self._register_rows(reassigned)
                yield from source
            return rows()

        with patch.object(self.repository, "iter_active", side_effect=changed_iterator):
            with self.assertRaises(MetadataIntegrityError):
                self._retrieve("Mobily", 2025, strategy="windowed_e5")

    def test_filters_company_and_year_and_preserves_citations(self):
        response = self._retrieve("Acme Holdings", 2024)
        self.assertEqual([row.citation.document_id for row in response.results], [self.docs["acme24"].document_id])
        citation = response.results[0].citation
        active = self.repository.get_active("workspace-a", citation.document_id)
        self.assertEqual(citation.document_version_id, active.document.version_id)
        self.assertEqual(citation.source_sha256, active.document.content_sha256)
        self.assertEqual(citation.source_path, "acme-2024.txt")

    def test_arabic_company_name_and_english_alias_resolve_the_same_identity(self):
        arabic = self._retrieve("شركة اتحاد اتصالات موبايلي", 2024)
        english_alias = self._retrieve("Mobily", 2024)
        expected = [self.docs["mobily24"].document_id]
        self.assertEqual([row.citation.document_id for row in arabic.results], expected)
        self.assertEqual([row.citation.document_id for row in english_alias.results], expected)

    def test_year_only_and_company_only_filters_are_supported(self):
        year = self._retrieve(year=2025)
        self.assertEqual({row.citation.document_id for row in year.results}, {
            self.docs["acme25"].document_id, self.docs["mobily25"].document_id,
        })
        company = self._retrieve("acme", None)
        self.assertEqual({row.citation.document_id for row in company.results}, {
            self.docs["acme24"].document_id, self.docs["acme25"].document_id,
        })

    def test_windowed_e5_obeys_identical_collection_scope(self):
        response = self._retrieve("أكمي القابضة", 2025, strategy="windowed_e5")
        self.assertTrue(response.results)
        self.assertEqual({row.citation.document_id for row in response.results}, {self.docs["acme25"].document_id})

    def test_unknown_company_and_invalid_filter_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "does not match"):
            self._retrieve("Unregistered Company", 2024)
        for args in ((None, None), ("Acme", True), ("   ", 2024), (None, 2101)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                CompanyYearFilter("annual-reports", *args)

    def test_unconfigured_or_cross_workspace_collection_fails_closed(self):
        without_catalog = RetrievalService(repository=self.repository, embedder=self.embedder)
        with self.assertRaises(MetadataIntegrityError):
            without_catalog.retrieve("revenue", workspace_id="workspace-a", strategy="bm25_raw",
                                     company_year_filter=CompanyYearFilter("annual-reports", "Acme", 2024))
        with self.assertRaises(MetadataIntegrityError):
            self._retrieve("Acme", 2024, workspace="workspace-b")

    def test_missing_or_replaced_active_version_invalidates_collection_snapshot(self):
        active = self.repository.get_active("workspace-a", self.docs["acme24"].document_id)
        (self.root / "acme-2024.txt").write_text("Acme Holdings 2024 revenue was 42 million.", encoding="utf-8")
        updated = self.ingestion.ingest("workspace-a", "acme-2024.txt")
        self.assertEqual(updated.document_id, active.document.document_id)
        self.assertNotEqual(updated.version_id, active.document.version_id)
        with self.assertRaises(MetadataIntegrityError):
            self._retrieve("Acme", 2024)
        self.repository.delete("workspace-a", active.document.document_id)
        with self.assertRaises(MetadataIntegrityError):
            self._retrieve("Acme", 2024)

    def test_metadata_changes_create_a_new_snapshot_revision(self):
        old_snapshot = self.catalog.get("workspace-a", "annual-reports")
        rows = [self._metadata(row) for row in self.docs.values()]
        rows = [replace(row, financial_year=2023) if row.document_id == self.docs["acme24"].document_id else row
                for row in rows]
        updated = self._register_rows(rows)
        self.assertNotEqual(old_snapshot.revision_id, updated.revision_id)
        self.assertEqual(self._retrieve("Acme", 2023).results[0].citation.document_id,
                         self.docs["acme24"].document_id)
        self.assertEqual(self._retrieve("Acme", 2024).status, "empty")

    def test_duplicate_documents_require_explicit_canonical_link(self):
        original = self._metadata(self.docs["acme24"])
        duplicate_result = self._ingest("copy-acme-2024.txt", "Acme Holdings 2024 revenue was 41 million.", "workspace-a")
        duplicate = self._metadata(duplicate_result, company_id="acme", year=2024)
        with self.assertRaisesRegex(ValueError, "exactly one canonical"):
            self._register_rows([original, duplicate])
        duplicate = replace(duplicate, duplicate_of_document_id=original.document_id)
        snapshot = self._register_rows([original, duplicate])
        self.assertEqual(len(snapshot.documents), 2)
        self.assertEqual(len({row.source_sha256 for row in snapshot.documents}), 1)

    def test_duplicate_ids_paths_and_ambiguous_aliases_are_rejected(self):
        row = self._metadata(self.docs["acme24"])
        with self.assertRaisesRegex(ValueError, "only once"):
            self._register_rows([row, row])
        second = replace(self._metadata(self.docs["acme25"]), source_path=row.source_path)
        with self.assertRaisesRegex(ValueError, "paths must be unique"):
            self._register_rows([row, second])
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self._register_rows([row], companies={"acme": ("Shared",), "mobily": ("shared",)})

    def test_collection_records_are_bound_to_workspace_and_company_catalog(self):
        row = self._metadata(self.docs["acme24"])
        with self.assertRaisesRegex(ValueError, "scope does not match"):
            self._register_rows([replace(row, workspace_id="workspace-b")])
        with self.assertRaisesRegex(ValueError, "unknown company"):
            self._register_rows([replace(row, company_id="unregistered")])


if __name__ == "__main__":
    unittest.main()
