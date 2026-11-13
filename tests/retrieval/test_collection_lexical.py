"""Contract tests for model-free durable retrieval with company/year boundaries."""
import tempfile
import unittest
from pathlib import Path

from nexus_ai.documents.collection_index import CollectionIndexService
from nexus_ai.retrieval.collection_repository import InMemoryCollectionIndexRepository
from nexus_ai.retrieval.collection_registration import register_indexed_manifest
from nexus_ai.retrieval.company_metadata import CompanyYearMetadataCatalog, MetadataIntegrityError
from nexus_ai.retrieval.collection_lexical import CollectionLexicalRetriever


class DurableCollectionLexicalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repository = InMemoryCollectionIndexRepository()
        self.catalog = CompanyYearMetadataCatalog()
        self.entries = [
            {"path": "mobily25.txt", "company": "Mobily", "year": 2025},
            {"path": "mobily24.txt", "company": "موبايلي", "year": 2024},
            {"path": "aramco25.txt", "company": "Aramco", "year": 2025},
        ]
        for path, content in (
            ("mobily25.txt", "Mobily 2025 revenue 88 million Saudi riyals."),
            ("mobily24.txt", "موبايلي 2024 الإيرادات 77 مليون ريال سعودي."),
            ("aramco25.txt", "Aramco 2025 revenue 900 million Saudi riyals."),
        ):
            (self.root / path).write_text(content, encoding="utf-8")
        self.indexer = CollectionIndexService(
            approved_root=self.root, repository=self.repository,
        )
        result = self.indexer.index("tenant-a", self.entries)
        self.assertEqual(result["status"], "PASS")
        self._register()
        self.retriever = CollectionLexicalRetriever(
            repository=self.repository,
            catalog=self.catalog,
            workspace_id="tenant-a",
            collection_id="financial",
        )

    def _register(self):
        return register_indexed_manifest(
            catalog=self.catalog, repository=self.repository,
            workspace_id="tenant-a", collection_id="financial",
            entries=self.entries,
            companies={"mobily": ("Mobily", "موبايلي"),
                       "aramco": ("Aramco", "أرامكو")},
        )

    def test_english_filter_returns_correct_year_citation(self):
        reply = self.retriever.retrieve("revenue", company="Mobily", financial_year=2025)
        self.assertEqual(reply.status, "ok")
        self.assertEqual([r.citation.source_path for r in reply.results], ["mobily25.txt"])
        self.assertIn("88 million", reply.results[0].citation.exact_text)
        self.assertEqual(reply.results[0].citation.start_char, 0)

    def test_arabic_alias_and_year_isolation(self):
        reply = self.retriever.retrieve("الإيرادات", company="موبايلي", financial_year=2024)
        self.assertEqual([r.citation.source_path for r in reply.results], ["mobily24.txt"])
        self.assertIn("77", reply.results[0].citation.exact_text)
        reply = self.retriever.retrieve("revenue", company="Aramco", financial_year=2025)
        self.assertEqual([r.citation.source_path for r in reply.results], ["aramco25.txt"])

    def test_english_revenue_query_finds_arabic_year_filtered_source(self):
        # No E5, cloud model or dictionary service. The explicit bridge
        # must preserve the Arabic source citation and the 2024 filter.
        result = self.retriever.retrieve(
            "Mobily revenue 2024", company="Mobily", financial_year=2024
        )
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.results[0].citation.source_path, "mobily24.txt")
        self.assertIn("77", result.results[0].citation.exact_text)

    def test_arabic_alef_variant_matches_revenue(self):
        result = self.retriever.retrieve(
            "ايرادات", company="موبايلي", financial_year=2024
        )
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.results[0].citation.source_path, "mobily24.txt")

    def test_unfiltered_and_other_workspace_rejected(self):
        with self.assertRaises(ValueError):
            self.retriever.retrieve("revenue")
        wrong_tenant = CollectionLexicalRetriever(
            repository=self.repository, catalog=self.catalog,
            workspace_id="tenant-b", collection_id="financial",
        )
        with self.assertRaises(MetadataIntegrityError):
            wrong_tenant.retrieve("revenue", company="Mobily", financial_year=2025)

    def test_no_matching_company_year_returns_empty(self):
        reply = self.retriever.retrieve("revenue", company="Aramco", financial_year=2024)
        self.assertEqual(reply.status, "empty")
        self.assertEqual(reply.results, [])

    def test_replacement_invalidates_snapshot_until_refreshed(self):
        (self.root / "mobily25.txt").write_text(
            "Mobily 2025 revenue 99 million.", encoding="utf-8"
        )
        self.indexer.index("tenant-a", self.entries)
        with self.assertRaises(MetadataIntegrityError):
            self.retriever.retrieve("revenue", company="Mobily", financial_year=2025)
        self._register()
        reply = self.retriever.retrieve("revenue", company="Mobily", financial_year=2025)
        self.assertEqual([r.citation.source_path for r in reply.results], ["mobily25.txt"])
        self.assertIn("99", reply.results[0].citation.exact_text)

    def test_invalid_offset_fails_closed(self):
        from dataclasses import replace
        from nexus_ai.documents.collection_types import CollectionIndex
        source = self.repository.get_active("tenant-a",
            self.catalog.get("tenant-a", "financial").documents[0].document_id)
        broken_chunk = replace(source.chunks[0], text="not in source")
        # A controlled source corruption must be rejected by the repository,
        # which is the first provenance boundary.
        with self.assertRaises(ValueError):
            self.repository.activate(CollectionIndex(source.document, (broken_chunk,)))

    def test_deterministic_scoring_and_no_generation(self):
        first = self.retriever.retrieve("revenue", financial_year=2025)
        second = self.retriever.retrieve("revenue", financial_year=2025)
        self.assertEqual(first, second)
        self.assertTrue(all(row.strategy == "bm25_raw" for row in first.results))


if __name__ == "__main__":
    unittest.main()
