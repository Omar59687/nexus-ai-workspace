"""Model-free page/chunk evidence forensics regression tests."""
from __future__ import annotations

import unittest
from dataclasses import replace

from nexus_ai.benchmark.financial_chunk_forensics import inspect_page_anchors
from nexus_ai.documents.chunking import ChunkingConfig, SourceAwareChunker
from nexus_ai.documents.types import ExtractedPage, ExtractionResult


class FinancialChunkForensicsTests(unittest.TestCase):
    def _inspect(self, text, anchors, *, max_chars=1200, radius=2):
        extracted = ExtractionResult(
            "test-fixture", "1", "application/pdf", (ExtractedPage(114, text),)
        )
        chunks = SourceAwareChunker(ChunkingConfig(
            max_chars=max_chars, overlap_chars=0
        )).chunk(
            extracted, document_id="d", version_id="v",
            source_path="report.pdf", source_sha256="h",
        )
        return inspect_page_anchors(
            pages=extracted.pages, chunks=chunks, page_number=114,
            anchors=anchors, line_radius=radius,
        )

    def test_relevant_arabic_page_anchors_within_chunk_and_line_window(self):
        result = self._inspect(
            "إثبات الإيرادات\n"
            "تتكون إيرادات المجموعة البالغة 19.6 مليار\n"
            "للسنة المنتهية في 31 ديسمبر 2025\n",
            ["إيرادات", "19.6", "2025"],
        )
        self.assertTrue(result["all_anchors_present_on_page"])
        self.assertTrue(result["all_anchors_share_chunk"])
        self.assertTrue(result["all_anchors_within_line_window"])
        self.assertNotIn("19.6", str(result))
        self.assertNotIn("إيرادات", str(result))

    def test_amount_and_year_can_be_on_page_but_separated_across_chunks(self):
        result = self._inspect(
            "إيرادات 19.6 مليار\n" + "بند محاسبي غير مرتبط\n" * 18 +
            "المعلومات المالية للسنة 2025\n",
            ["إيرادات", "19.6", "2025"],
            max_chars=95,
            radius=1,
        )
        self.assertTrue(result["all_anchors_present_on_page"])
        self.assertFalse(result["all_anchors_share_chunk"])
        self.assertFalse(result["all_anchors_within_line_window"])

    def test_reported_year_normalizes_arabic_digits(self):
        result = self._inspect(
            "إيرادات المجموعة\nالمبلغ ١٩.٦ مليار\nالسنة ٢٠٢٥\n",
            ["إيرادات", "19.6", "2025"],
        )
        self.assertTrue(result["all_anchors_present_on_page"])
        self.assertTrue(result["all_anchors_share_chunk"])

    def test_arabic_alef_tatweel_and_vowel_marks_are_matching_variants(self):
        result = self._inspect(
            "إِيرَادَات المجموعة\n"
            "مبلغ 19.6 مليار\n"
            "السنة 2025\n",
            ["إيرادات", "19.6", "2025"],
        )
        self.assertTrue(result["all_anchors_present_on_page"])
        self.assertTrue(result["all_anchors_share_chunk"])
        variants = self._inspect(
            "ايرادات المجموعة\nمبلغ 19.6 مليار\nالسنة 2025\n",
            ["إيرادات", "19.6", "2025"],
        )
        self.assertTrue(variants["all_anchors_present_on_page"])

    def test_missing_currency_is_not_silently_inferred(self):
        result = self._inspect(
            "إيرادات 19.6 مليار للسنة المنتهية في 2025\n",
            ["إيرادات", "19.6", "2025", "ريال"],
        )
        self.assertFalse(result["all_anchors_present_on_page"])
        self.assertFalse(result["all_anchors_share_chunk"])
        self.assertFalse(result["all_anchors_within_line_window"])

    def test_empty_missing_and_duplicate_anchors_are_rejected(self):
        with self.assertRaises(ValueError):
            self._inspect("hello", ["19.6"])
        with self.assertRaises(ValueError):
            self._inspect("hello", ["2025", "٢٠٢٥"])
        with self.assertRaises(ValueError):
            self._inspect("hello", ["x", "y"], radius=6)

    def test_corrupted_chunk_span_rejected(self):
        extracted = ExtractionResult(
            "fixture", "1", "application/pdf", (ExtractedPage(114, "revenue 19.6 2025"),)
        )
        chunk = SourceAwareChunker().chunk(
            extracted, document_id="d", version_id="v",
            source_path="report.pdf", source_sha256="h",
        )[0]
        with self.assertRaises(ValueError):
            inspect_page_anchors(
                pages=extracted.pages,
                chunks=[replace(chunk, text="unrelated")],
                page_number=114, anchors=["revenue", "19.6"],
            )


if __name__ == "__main__":
    unittest.main()
