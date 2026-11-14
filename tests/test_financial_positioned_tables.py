"""Positioned financial table candidates remain untrusted until review."""
from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace

from nexus_ai.data_analytics import AnalyticsInputError
from nexus_ai.documents.types import ExtractedPage, SourceChunk
from nexus_ai.financial_positioned_tables import PositionedText, reconstruct_financial_rows


def source(text):
    chunk = SourceChunk(
        chunk_id="c", document_id="d", version_id="v",
        source_path="finance.pdf", source_sha256="digest",
        extractor_name="pypdf", extractor_version="6",
        page_number=140, start_char=0, end_char=len(text),
        start_line=1, end_line=1, text=text, heading_path=(),
        offsets_reliable=True, chunker_version="v1",
    )
    return SimpleNamespace(
        document=SimpleNamespace(
            workspace_id="w", document_id="d", version_id="v",
            content_sha256="digest", source_path="finance.pdf",
            pages=(ExtractedPage(140, text),),
        ),
        chunks=(chunk,),
    )


class Repository:
    def __init__(self, indexed):
        self.indexed = indexed

    def get_active(self, workspace_id, document_id):
        return self.indexed if workspace_id == "w" and document_id == "d" else None


class PositionedTableTests(unittest.TestCase):
    def setUp(self):
        self.text = "SAR thousands\n2024\n2025\nTotal revenue\n18,206,447\n19,641,705\n"
        self.repo = Repository(source(self.text))
        self.boxes = (
            PositionedText(140, 80, 10, "SAR thousands"),
            PositionedText(140, 200, 40, "2024"),
            PositionedText(140, 320, 40, "2025"),
            PositionedText(140, 20, 90, "Total revenue"),
            PositionedText(140, 200, 90, "18,206,447"),
            PositionedText(140, 320, 90, "19,641,705"),
        )

    def extract(self, boxes=None):
        return reconstruct_financial_rows(
            self.boxes if boxes is None else boxes,
            repository=self.repo, workspace_id="w", document_id="d", page_number=140,
        )

    def test_both_year_columns_produce_independently_cited_review_candidates(self):
        result = self.extract()
        self.assertEqual(result["status"], "CANDIDATES_FOR_REVIEW")
        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual(
            {(x["year"], x["amount"]) for x in result["candidates"]},
            {(2024, "18206447"), (2025, "19641705")},
        )
        self.assertTrue(all(x["status"] == "HUMAN_ROW_REVIEW_REQUIRED"
                            and x["chunk_id"] == "c" for x in result["candidates"]))
        self.assertEqual(result["automatically_verified_financial_facts"], 0)

    def test_arabic_metric_and_arabic_digit_geometry(self):
        text = "ألف ريال سعودي\n٢٠٢٤\n٢٠٢٥\nإجمالي الإيرادات\n١٨٬٢٠٦٬٤٤٧\n١٩٬٦٤١٬٧٠٥"
        self.repo.indexed = source(text)
        result = self.extract((
            PositionedText(140, 20, 5, "ألف ريال سعودي"),
            PositionedText(140, 200, 30, "٢٠٢٤"),
            PositionedText(140, 320, 30, "٢٠٢٥"),
            PositionedText(140, 20, 90, "إجمالي الإيرادات"),
            PositionedText(140, 200, 90, "١٨٬٢٠٦٬٤٤٧"),
            PositionedText(140, 320, 90, "١٩٬٦٤١٬٧٠٥"),
        ))
        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual({c["metric"] for c in result["candidates"]}, {"revenue"})

    def test_missing_unit_or_unaligned_year_abstains(self):
        for boxes in (
            tuple(x for x in self.boxes if x.text != "SAR thousands"),
            tuple(replace(x, x=420) if x.text == "2025" else x for x in self.boxes),
        ):
            result = self.extract(boxes)
            self.assertLess(result["candidate_count"], 2)

    def test_invented_geometry_text_and_cross_page_rejected(self):
        for bad in (
            self.boxes + (PositionedText(140, 10, 30, "999,999,999"),),
            (PositionedText(141, 20, 90, "Total revenue"),),
        ):
            with self.assertRaises(AnalyticsInputError):
                self.extract(bad)

    def test_stale_version_rejected(self):
        orig = self.repo.indexed
        self.repo.indexed = SimpleNamespace(
            document=SimpleNamespace(**{**vars(orig.document), "version_id": "v2"}),
            chunks=orig.chunks,
        )
        result = self.extract()
        self.assertEqual(result["candidate_count"], 0)

    def test_invalid_coordinates_and_limits(self):
        for bad in (
            (PositionedText(140, float("nan"), 10, "SAR thousands"),),
            (PositionedText(140, -1, 10, "SAR thousands"),),
        ):
            with self.assertRaises(AnalyticsInputError):
                self.extract(bad)
        with self.assertRaises(AnalyticsInputError):
            reconstruct_financial_rows(
                self.boxes, repository=self.repo, workspace_id="w",
                document_id="d", page_number=140, max_boxes=2,
            )

    def test_overlapping_year_headers_abstain(self):
        # Both headers map to the same column: impossible to know which year.
        boxes = tuple(replace(x, x=200) if x.text == "2025" else x for x in self.boxes)
        result = self.extract(boxes)
        self.assertNotIn(
            (2025, "18206447"),
            {(c["year"], c["amount"]) for c in result["candidates"]},
        )

    def test_competing_amounts_same_year_rejected(self):
        # Two distinct totals under the same year and label are conflicts.
        text = self.text + "19,641,706"
        self.repo.indexed = source(text)
        boxes = self.boxes + (PositionedText(140, 320, 91, "19,641,706"),)
        result = self.extract(boxes)
        self.assertEqual(result["candidate_count"], 0)


if __name__ == "__main__":
    unittest.main()
