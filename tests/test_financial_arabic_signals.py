"""Arabic lexical diagnostics must not be misrepresented as financial facts."""
from __future__ import annotations

import unittest

from nexus_ai.data_analytics import AnalyticsInputError
from nexus_ai.financial_arabic_signals import (
    financial_signal_counts, financial_signal_diagnostics, normalize_arabic,
)


class ArabicSignalTests(unittest.TestCase):
    def test_arabic_revenue_orthography_and_diacritics(self):
        self.assertEqual(normalize_arabic("إِجْمَالِي الإيرَادَات"),
                         "اجمالي الايرادات")
        counts = financial_signal_counts(
            "إِجْمَالِي الإِيرَادَات (بالآلاف من الريالات السعودية)"
        )
        self.assertGreaterEqual(counts["revenue_word"], 1)
        self.assertGreaterEqual(counts["total_word"], 1)
        self.assertGreaterEqual(counts["thousand_word"], 1)
        self.assertGreaterEqual(counts["saudi_riyals"], 1)

    def test_separately_report_page_and_position_signals(self):
        diagnostic = financial_signal_diagnostics(
            "إجمالي الإيرادات 19,641,705 (ألف ريال سعودي)",
            ("19,641,705", "2025"),
        )
        self.assertGreater(diagnostic["page_text_lexical_hints"]["revenue_word"], 0)
        self.assertEqual(diagnostic["positioned_fragment_lexical_hints"]["revenue_word"], 0)
        self.assertEqual(diagnostic["interpretation"],
                         "DIAGNOSTIC_ONLY_NO_ROW_OR_UNIT_INFERENCE")
        self.assertNotIn("amount", diagnostic)
        self.assertNotIn("year", diagnostic)

    def test_english_and_arabic_currency_hints_but_not_inference(self):
        self.assertEqual(financial_signal_counts("total revenue SAR thousands")["saudi_riyals"], 1)
        self.assertGreater(financial_signal_counts("المليون ريال")["million_word"], 0)

    def test_budget_rejection(self):
        with self.assertRaises(AnalyticsInputError):
            financial_signal_diagnostics("x" * 2_000_001, ())
        with self.assertRaises(AnalyticsInputError):
            financial_signal_diagnostics("safe", ("x" * 401,))
        with self.assertRaises(AnalyticsInputError):
            normalize_arabic(None)


if __name__ == "__main__":
    unittest.main()
