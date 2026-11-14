"""Review inventory never joins digest-only labels to indexed numbers."""
from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace

from nexus_ai.documents.types import ExtractedPage, SourceChunk
from nexus_ai.data_analytics import AnalyticsInputError
from nexus_ai.financial_geometry_review import build_financial_review_inventory
from nexus_ai.financial_positioned_tables import PositionedText


def make_source(text="2025 19,641,705 revenue data"):
    chunk = SourceChunk(
        chunk_id="c1", document_id="doc", version_id="v1",
        source_path="report.pdf", source_sha256="hash",
        extractor_name="pypdf", extractor_version="6", page_number=140,
        start_char=0, end_char=len(text), start_line=1, end_line=1,
        text=text, heading_path=(), offsets_reliable=True,
        chunker_version="v1",
    )
    document = SimpleNamespace(
        workspace_id="tenant", document_id="doc", version_id="v1",
        source_path="report.pdf", content_sha256="hash",
        pages=(ExtractedPage(140, text),),
    )
    return SimpleNamespace(document=document, chunks=(chunk,))


class Repo:
    def __init__(self):
        self.source = make_source()
        self.calls = 0
        self.replace_after_one = False

    def get_active(self, workspace, document):
        if workspace != "tenant" or document != "doc":
            return None
        self.calls += 1
        if self.replace_after_one and self.calls > 1:
            return SimpleNamespace(
                document=SimpleNamespace(**{**vars(self.source.document), "version_id": "v2"}),
                chunks=self.source.chunks,
            )
        return self.source


class FinancialGeometryReviewTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.boxes = (
            PositionedText(140, 300, 20, "إجمالي الإيرادات"),
            PositionedText(140, 300, 40, "بالآلاف من الريالات السعودية"),
            PositionedText(140, 200, 90, "2025"),
            PositionedText(140, 200, 120, "19,641,705"),
        )

    def run_inventory(self, **kw):
        return build_financial_review_inventory(
            self.boxes, repository=self.repo,
            workspace_id="tenant", document_id="doc", page_number=140,
            **kw,
        )

    def test_unindexed_arabic_label_can_appear_separately_from_cited_amount(self):
        result = self.run_inventory()
        self.assertEqual(result["numeric_citation_count"], 1)
        self.assertEqual(result["geometry_label_band_count"], 2)
        self.assertEqual(result["numeric_citations"][0]["value"], "19641705")
        self.assertEqual(result["numeric_citations"][0]["citation"]["chunk_id"], "c1")
        self.assertEqual(result["numeric_citations"][0]["status"], "SOURCE_NUMERIC_TOKEN_ONLY")
        self.assertEqual(result["cross_evidence_associations"], 0)
        self.assertEqual(result["automatically_verified_financial_facts"], 0)
        self.assertTrue(result["requires_explicit_human_review"])
        self.assertFalse(any("amount" in hint or "value" in hint or "citation" in hint
                             for hint in result["geometry_label_bands"]))

    def test_forged_geometry_amount_has_no_citation(self):
        forged = self.boxes + (PositionedText(140, 200, 150, "99,999,999"),)
        output = build_financial_review_inventory(
            forged, repository=self.repo, workspace_id="tenant",
            document_id="doc", page_number=140,
        )
        self.assertEqual(output["numeric_citation_count"], 1)
        self.assertEqual(output["uncited_numeric_fragments_skipped"], 1)

    def test_negative_or_extended_value_not_accepted_as_positive_citation(self):
        for text in ("2025 -19,641,705", "2025 119,641,705", "2025 19,641,705.5"):
            self.repo.source = make_source(text)
            with self.subTest(text=text):
                result = self.run_inventory()
                self.assertEqual(result["numeric_citation_count"], 0)

    def test_source_version_swap_and_cross_scope_fail_closed(self):
        self.repo.replace_after_one = True
        with self.assertRaisesRegex(AnalyticsInputError, "changed"):
            self.run_inventory()
        with self.assertRaises(AnalyticsInputError):
            build_financial_review_inventory(
                self.boxes, repository=self.repo,
                workspace_id="other", document_id="doc", page_number=140,
            )

    def test_wrong_geometry_page_and_output_budgets_rejected(self):
        with self.assertRaises(AnalyticsInputError):
            build_financial_review_inventory(
                (PositionedText(141, 200, 30, "2025"),), repository=self.repo,
                workspace_id="tenant", document_id="doc", page_number=140,
            )
        with self.assertRaises(AnalyticsInputError):
            self.run_inventory(max_numeric=0)

    def test_missing_or_unreliable_citation_does_not_pass(self):
        previous = self.repo.source
        self.repo.source = SimpleNamespace(
            document=previous.document,
            chunks=(replace(previous.chunks[0], offsets_reliable=False),),
        )
        result = self.run_inventory()
        self.assertEqual(result["numeric_citation_count"], 0)
        self.assertEqual(result["geometry_label_band_count"], 2)


if __name__ == "__main__":
    unittest.main()
