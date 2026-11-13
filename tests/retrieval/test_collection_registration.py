"""Cross-slice manifest -> indexed collection -> filtered citation contract."""
import tempfile
import unittest
from pathlib import Path

from nexus_ai.documents.service import DocumentIngestionService
from nexus_ai.retrieval.collection_registration import register_indexed_manifest
from nexus_ai.retrieval.company_metadata import (
    CompanyYearFilter, CompanyYearMetadataCatalog, MetadataIntegrityError,
)
from nexus_ai.retrieval.repository import InMemoryDocumentIndex
from nexus_ai.retrieval.service import RetrievalService
from tests.documents.test_ingestion import FakeEmbedder


class RegistrationIntegrationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.repository = InMemoryDocumentIndex()
        self.embedder = FakeEmbedder()
        self.ingestion = DocumentIngestionService(
            approved_root=self.root, repository=self.repository, embedder=self.embedder,
        )
        self.catalog = CompanyYearMetadataCatalog()
        self.companies = {
            "mobily": ("Mobily", "شركة اتحاد اتصالات موبايلي"),
            "aramco": ("Aramco", "أرامكو"),
        }
        self.entries = [
            {"path": "mobily25.txt", "company": "Mobily", "year": 2025},
            {"path": "mobily24.txt", "company": "شركة اتحاد اتصالات موبايلي", "year": 2024},
            {"path": "aramco25.txt", "company": "Aramco", "year": 2025},
        ]
        for path, text in [
            ("mobily25.txt", "Mobily 2025 revenue 88 million."),
            ("mobily24.txt", "Mobily 2024 revenue 77 million."),
            ("aramco25.txt", "Aramco 2025 revenue 900 million."),
        ]:
            (self.root / path).write_text(text, encoding="utf-8")
            self.ingestion.ingest("workspace-a", path)

    def _register(self, entries=None):
        return register_indexed_manifest(
            catalog=self.catalog, repository=self.repository,
            workspace_id="workspace-a", collection_id="reports",
            entries=self.entries if entries is None else entries,
            companies=self.companies,
        )

    def _search(self, company, year):
        service = RetrievalService(
            repository=self.repository, embedder=self.embedder,
            company_metadata=self.catalog,
        )
        return service.retrieve(
            "revenue", workspace_id="workspace-a", strategy="bm25_raw",
            company_year_filter=CompanyYearFilter("reports", company, year),
        )

    def test_trusted_manifest_registration_and_exact_filtered_citation(self):
        snapshot = self._register()
        self.assertEqual(len(snapshot.documents), 3)
        result = self._search("شركة اتحاد اتصالات موبايلي", 2025)
        self.assertEqual(result.status, "ok")
        self.assertEqual([x.citation.source_path for x in result.results], ["mobily25.txt"])
        self.assertIn("88 million", result.results[0].citation.exact_text)
        self.assertEqual(self._search("Aramco", 2025).results[0].citation.source_path, "aramco25.txt")

    def test_missing_index_prevents_partial_registration(self):
        baseline = self._register()
        self.repository.delete("workspace-a", baseline.documents[0].document_id)
        with self.assertRaises(MetadataIntegrityError):
            self._register()
        self.assertEqual(
            self.catalog.get("workspace-a", "reports").revision_id,
            baseline.revision_id,
        )

    def test_unknown_company_label_fails_closed_without_reassignment(self):
        baseline = self._register()
        invalid = [*self.entries]
        invalid[0] = {**invalid[0], "company": "Other Company"}
        with self.assertRaises(MetadataIntegrityError):
            self._register(invalid)
        self.assertEqual(
            self.catalog.get("workspace-a", "reports").revision_id,
            baseline.revision_id,
        )

    def test_replaced_source_version_requires_reregistration(self):
        before = self._register()
        (self.root / "mobily25.txt").write_text("Mobily 2025 revenue 99 million.", encoding="utf-8")
        self.ingestion.ingest("workspace-a", "mobily25.txt")
        with self.assertRaises(MetadataIntegrityError):
            self._search("Mobily", 2025)
        after = self._register()
        self.assertNotEqual(before.revision_id, after.revision_id)
        self.assertIn("99 million", self._search("Mobily", 2025).results[0].citation.exact_text)

    def test_duplicate_different_company_and_year_fails_closed(self):
        (self.root / "aramco25.txt").write_text(
            (self.root / "mobily25.txt").read_text(encoding="utf-8"), encoding="utf-8",
        )
        self.ingestion.ingest("workspace-a", "aramco25.txt")
        with self.assertRaises(MetadataIntegrityError):
            self._register()

    def test_cross_workspace_registration_cannot_adopt_other_workspace_sources(self):
        with self.assertRaises(MetadataIntegrityError):
            register_indexed_manifest(
                catalog=self.catalog, repository=self.repository,
                workspace_id="workspace-b", collection_id="reports",
                entries=self.entries, companies=self.companies,
            )

    def test_duplicate_matching_metadata_requires_canonical_document_link(self):
        (self.root / "mobily25-copy.txt").write_text(
            (self.root / "mobily25.txt").read_text(encoding="utf-8"), encoding="utf-8"
        )
        self.ingestion.ingest("workspace-a", "mobily25-copy.txt")
        snapshot = self._register([*self.entries, {
            "path": "mobily25-copy.txt", "company": "Mobily", "year": 2025
        }])
        docs = {row.source_path: row for row in snapshot.documents}
        self.assertEqual(
            docs["mobily25-copy.txt"].duplicate_of_document_id,
            docs["mobily25.txt"].document_id,
        )


if __name__ == "__main__":
    unittest.main()
