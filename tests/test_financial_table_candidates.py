"""Strict table candidate extraction never invents a financial assertion."""
from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace

from nexus_ai.data_analytics import AnalyticsInputError
from nexus_ai.documents.types import ExtractedPage, SourceChunk
from nexus_ai.financial_table_candidates import extract_table_candidates


def index(text, *, version="v1", reliable=True):
    chunk = SourceChunk(
        chunk_id="chunk-1", document_id="d", version_id=version,
        source_path="report.pdf", source_sha256="h",
        extractor_name="fake", extractor_version="1",
        page_number=7, start_char=0, end_char=len(text), start_line=1,
        end_line=len(text.splitlines()), text=text,
        heading_path=(), offsets_reliable=reliable, chunker_version="v1",
    )
    doc = SimpleNamespace(
        workspace_id="tenant", document_id="d", version_id=version,
        source_path="report.pdf", content_sha256="h",
        pages=(ExtractedPage(7, text),),
    )
    return SimpleNamespace(document=doc, chunks=(chunk,))


class Repository:
    def __init__(self, item):
        self.item = item
    def get_active(self, workspace_id, document_id):
        return self.item if workspace_id == "tenant" and document_id == "d" else None


class TableCandidateTests(unittest.TestCase):
    def result(self, text, *, reliable=True):
        return extract_table_candidates(
            repository=Repository(index(text, reliable=reliable)),
            workspace_id="tenant", document_id="d",
        )

    def test_explicit_english_header_and_row(self):
        result = self.result("Year: 2025 SAR thousands\nTotal revenue | 19,641,705\n")
        self.assertEqual(result["status"], "CANDIDATES_FOR_REVIEW")
        self.assertEqual(result["candidate_count"], 1)
        item = result["candidates"][0]
        self.assertEqual((item["year"], item["currency"], item["unit"], item["amount"]),
                         (2025, "SAR", "thousands", "19641705"))
        self.assertEqual((item["page_number"], item["start_char"]),
                         (7, len("Year: 2025 SAR thousands\n")))
        self.assertEqual(item["status"], "HUMAN_ROW_REVIEW_REQUIRED")
        self.assertEqual(result["automatically_verified_financial_facts"], 0)

    def test_arabic_header_digits_and_tabbed_row(self):
        result = self.result("السنة: ٢٠٢٥ ألف ريال سعودي\nإجمالي الإيرادات\t١٩٬٦٤١٬٧٠٥\n")
        self.assertEqual(result["candidate_count"], 1)
        item = result["candidates"][0]
        self.assertEqual(item["metric"], "revenue")
        self.assertEqual(item["amount"], "19641705")

    def test_ambiguous_multiyear_and_layouts_abstain(self):
        sources = [
            "Year: 2024 2025 SAR thousands\nTotal revenue | 19,641,705\n",
            "Year: 2025 SAR thousands SAR millions\nTotal revenue | 19,641,705\n",
            "Total revenue | 19,641,705\n",
            "Year: 2025 SAR thousands\nTotal revenue | 2024 | 19,641,705\n",
            "Year: 2025 SAR thousands\nTotal revenue 19,641,705\n",
            "Year: 2025 SAR thousands\nSegment revenue | 19,641,705\n",
        ]
        for source in sources:
            with self.subTest(source=source):
                result = self.result(source)
                self.assertEqual(result["status"], "ABSTAIN_NO_STRICT_ROWS")
                self.assertFalse(result["candidates"])

    def test_reject_sign_or_decimal_confusion(self):
        result = self.result("Year: 2025 SAR thousands\nTotal revenue | -19,641,705\n")
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["candidates"][0]["amount"], "-19641705")
        result = self.result("Year: 2025 SAR thousands\nTotal revenue | 19,641,705.5\n")
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["candidates"][0]["amount"], "19641705.5")

    def test_broken_citation_fails_closed(self):
        result = self.result("Year: 2025 SAR thousands\nTotal revenue | 19,641,705\n",
                             reliable=False)
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["abstentions"]["unreliable_citation"], 1)

    def test_cross_tenant_rejected(self):
        with self.assertRaises(AnalyticsInputError):
            extract_table_candidates(
                repository=Repository(index("Year: 2025 SAR thousands")),
                workspace_id="another", document_id="d",
            )

    def test_candidate_limit_rejected(self):
        source = "Year: 2025 SAR thousands\nTotal revenue | 1\nTotal revenue | 2\n"
        with self.assertRaisesRegex(AnalyticsInputError, "limit"):
            extract_table_candidates(
                repository=Repository(index(source)), workspace_id="tenant",
                document_id="d", max_candidates=1,
            )

    def test_stale_chunk_identity_rejected(self):
        base = index("Year: 2025 SAR thousands\nTotal revenue | 1\n")
        repo = Repository(SimpleNamespace(
            document=base.document, chunks=(replace(base.chunks[0], version_id="v0"),)
        ))
        with self.assertRaisesRegex(AnalyticsInputError, "provenance"):
            extract_table_candidates(repository=repo, workspace_id="tenant", document_id="d")

    def test_unstructured_real_pdf_style_abstains(self):
        result = self.result("الإيرادات\n٢٠٢٥\n١٩٬٦٤١٬٧٠٥\n٢٠٢٤\n١٨٬٢٠٦٬٤٤٧\n")
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["automatically_verified_financial_facts"], 0)


if __name__ == "__main__":
    unittest.main()
