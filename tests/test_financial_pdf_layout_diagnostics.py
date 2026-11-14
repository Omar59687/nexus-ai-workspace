"""Layout diagnostics: RTL/LTR ambiguity and no automatic financial claims."""
from __future__ import annotations

import unittest

from nexus_ai.data_analytics import AnalyticsInputError
from nexus_ai.financial_pdf_layout_diagnostics import inspect_pdf_layout_signals
from nexus_ai.financial_positioned_tables import PositionedText


class PdfLayoutDiagnosticTests(unittest.TestCase):
    def test_split_revenue_and_unit_are_only_layout_hints(self):
        fragments = (
            PositionedText(140, 300, 50, "إجمالي"),
            PositionedText(140, 250, 50, "الإيرادات"),
            PositionedText(140, 300, 90, "بالآلاف"),
            PositionedText(140, 250, 90, "من"),
            PositionedText(140, 200, 90, "الريالات"),
            PositionedText(140, 160, 90, "السعودية"),
            PositionedText(140, 150, 130, "19,641,705"),
        )
        result = inspect_pdf_layout_signals(fragments, page_number=140)
        self.assertEqual(result["joined_fragment_revenue_bands"], 1)
        self.assertEqual(result["joined_fragment_currency_unit_bands"], 1)
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["automatically_verified_financial_facts"], 0)
        self.assertEqual(result["source_binding"], "PDF_DIGEST_ONLY_NOT_INDEX_TEXT_CITATION")
        self.assertGreater(result["reading_order_disagreements"], 0)

    def test_single_fragment_recognition(self):
        boxes = (
            PositionedText(142, 25, 60, "إجمالي الإيرادات"),
            PositionedText(142, 25, 80, "ألف ريال سعودي"),
        )
        result = inspect_pdf_layout_signals(boxes, page_number=142)
        self.assertEqual(result["single_fragment_revenue_bands"], 1)
        self.assertEqual(result["single_fragment_currency_unit_bands"], 1)

    def test_unrecognized_year_and_number_only_never_infers_row(self):
        boxes = (PositionedText(140, 200, 20, "2025"),
                 PositionedText(140, 200, 50, "19,641,705"))
        result = inspect_pdf_layout_signals(boxes, page_number=140)
        self.assertEqual(result["joined_fragment_revenue_bands"], 0)
        self.assertEqual(result["joined_fragment_currency_unit_bands"], 0)
        self.assertEqual(result["automatically_verified_financial_facts"], 0)

    def test_reject_cross_page_nonfinite_and_over_budget(self):
        for boxes in (
            (PositionedText(141, 20, 50, "revenue"),),
            (PositionedText(140, float("nan"), 10, "revenue"),),
            (PositionedText(140, -1, 10, "revenue"),),
            (PositionedText(140, 20, 50, "x" * 401),),
        ):
            with self.subTest(boxes=boxes), self.assertRaises(AnalyticsInputError):
                inspect_pdf_layout_signals(boxes, page_number=140)
        with self.assertRaises(AnalyticsInputError):
            inspect_pdf_layout_signals(
                (PositionedText(140, 20, 50, "a"),) * 4,
                page_number=140, max_fragments=3,
            )


if __name__ == "__main__":
    unittest.main()
