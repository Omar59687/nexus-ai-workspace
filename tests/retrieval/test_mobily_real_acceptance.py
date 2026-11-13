"""Privacy-preserving real Mobily benchmark tests; no real PDF is committed."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from nexus_ai.benchmark.mobily_real_acceptance import (
    _amount_present, _amount_formats, _metric_present, assess_evidence, write_report,
)
from nexus_ai.documents.types import ExtractedPage, SourceChunk


def _row(text: str, page: int, chunk_id: str) -> SourceChunk:
    return SourceChunk(
        chunk_id=chunk_id, document_id="d", version_id="v",
        source_path="document.pdf", source_sha256="h", extractor_name="pypdf",
        extractor_version="1", page_number=page, start_char=0,
        end_char=len(text), start_line=1, end_line=1,
        text=text, heading_path=(), offsets_reliable=True,
        chunker_version="chunker",
    )


def _retrieval(page: int, chunk_id: str, *, preceding: int = 0):
    rows = [
        SimpleNamespace(citation=SimpleNamespace(
            page_number=500 + rank, chunk_id=f"unrelated-{rank}"
        )) for rank in range(preceding)
    ]
    rows.append(SimpleNamespace(citation=SimpleNamespace(
        page_number=page, chunk_id=chunk_id
    )))
    return SimpleNamespace(status="ok", results=tuple(rows))


class MobilyRealRevenueAcceptanceTests(unittest.TestCase):
    def test_exact_amount_accepts_comma_and_arabic_digits(self):
        for sample in ("19,642", "19642", "١٩٬٦٤٢", "۱۹٬۶۴۲"):
            self.assertTrue(_amount_present(sample))
        for sample in ("19.6", "18,206", "119,642", "19,6427", "19,641,7059"):
            self.assertFalse(_amount_present(sample))

    def test_precise_unrounded_audited_revenue_is_detected(self):
        for amount in ("19,641,705", "19641705", "١٩٬٦٤١٬٧٠٥", "19 641 705"):
            self.assertIn("precise_thousands", _amount_formats(amount))
        self.assertNotIn("rounded_millions", _amount_formats("19,641,705"))

    def test_mismatched_metric_is_reported_separately_from_amount(self):
        indexed = SimpleNamespace(
            document=SimpleNamespace(pages=(
                ExtractedPage(114, "19,641,705 year 2025"),
                ExtractedPage(115, "Revenue in Saudi riyals thousands"),
            )),
            chunks=(
                _row("19,641,705 year 2025", 114, "number"),
                _row("Revenue in Saudi riyals thousands", 115, "label"),
            ),
        )
        result = assess_evidence(
            indexed, (_retrieval(114, "number"), _retrieval(115, "label"))
        )
        self.assertEqual(result["candidate_pages"], [])
        self.assertEqual(result["amount_pages"], [114])
        self.assertEqual(result["signal_status"], "AMOUNT_FOUND_NO_REVENUE_LABEL_ON_SAME_PAGE")

    def test_revenue_metric_in_arabic_without_hamza(self):
        self.assertTrue(_metric_present("المبيعات/الايرادات"))
        self.assertTrue(_metric_present("إيرادات موبايلي"))
        self.assertTrue(_metric_present("Revenue"))
        self.assertFalse(_metric_present("النفقات الرأسمالية"))

    def test_full_gold_candidate_is_reported_without_financial_truth_claim(self):
        evidence = "إيرادات 2025 19,642 مليون ريال سعودي"
        indexed = SimpleNamespace(
            document=SimpleNamespace(pages=(ExtractedPage(114, evidence),)),
            chunks=(_row(evidence, 114, "revenue-chunk"),),
        )
        report = assess_evidence(
            indexed, (_retrieval(114, "revenue-chunk"), _retrieval(114, "revenue-chunk"))
        )
        self.assertEqual(report["gold"]["amount_million_sar"], 19642)
        self.assertEqual(report["candidate_pages"], [114])
        self.assertEqual(report["candidate_chunk_count"], 1)
        self.assertEqual(report["legacy_same_page_word_match_status"], "CANDIDATES_RETRIEVED")
        self.assertEqual(report["financial_truth_status"], "ORIGINAL_PDF_TABLE_VISUALLY_VERIFIED_AUTOMATIC_ROW_ASSOCIATION_UNVERIFIED")
        self.assertNotIn(evidence, json.dumps(report, ensure_ascii=False))

    def test_verified_pdf_pages_pass_evidence_gate_despite_reordered_arabic_label(self):
        # The source table was visually checked independently. These fake
        # strings emulate PDF text extraction omitting/reordering Arabic labels.
        pages = (
            ExtractedPage(140, "2025 19,641,705 2024 18,206,447"),
            ExtractedPage(142, "قطاع التشغيل 19,641,705"),
        )
        indexed = SimpleNamespace(
            document=SimpleNamespace(pages=pages),
            chunks=(
                _row(pages[0].text, 140, "gold-140"),
                _row(pages[1].text, 142, "gold-142"),
            ),
        )
        report = assess_evidence(
            indexed, (_retrieval(140, "gold-140"), _retrieval(142, "gold-142"))
        )
        self.assertEqual(report["candidate_pages"], [])
        self.assertEqual(report["gold_evidence_status"],
                         "EXACT_AMOUNT_EXTRACTED_ON_BOTH_VISUALLY_VERIFIED_PAGES")
        self.assertEqual(report["verified_gold_retrieval_status"],
                         "VERIFIED_PAGES_RETRIEVED_BILINGUALLY")
        self.assertTrue(report["languages"][0]["verified_gold_page_at_10"])
        self.assertTrue(report["languages"][1]["verified_gold_page_at_10"])
        self.assertFalse(report["languages"][0]["relevant_candidate_page_at_10"])

    def test_verified_page_without_exact_numeric_chunk_is_not_full_citation_pass(self):
        pages = (
            ExtractedPage(140, "19,641,705 2025"),
            ExtractedPage(142, "19,641,705 2025"),
        )
        indexed = SimpleNamespace(
            document=SimpleNamespace(pages=pages),
            chunks=(
                _row("other values", 140, "only-context"),
                _row("other values", 142, "another-context"),
            ),
        )
        result = assess_evidence(
            indexed, (_retrieval(140, "only-context"), _retrieval(142, "another-context"))
        )
        self.assertTrue(result["acceptance_gates"]["verified_source_pages_retrieved_bilingually_at_10"])
        self.assertFalse(result["acceptance_gates"]["exact_amount_in_cited_chunk_bilingually_at_10"])
        self.assertEqual(result["acceptance_summary"],
                         "VERIFIED_PAGES_RETRIEVED_BUT_CITED_AMOUNT_UNVERIFIED")
        self.assertFalse(result["acceptance_gates"]["financial_row_association_machine_verified"])

    def test_verified_page_and_exact_number_in_cited_chunk_still_need_row_check(self):
        pages = (
            ExtractedPage(140, "19,641,705 2025"),
            ExtractedPage(142, "19,641,705 2025"),
        )
        indexed = SimpleNamespace(
            document=SimpleNamespace(pages=pages),
            chunks=(_row(pages[0].text, 140, "gold-140"),
                    _row(pages[1].text, 142, "gold-142")),
        )
        result = assess_evidence(
            indexed, (_retrieval(140, "gold-140"), _retrieval(142, "gold-142"))
        )
        self.assertTrue(result["acceptance_gates"]["exact_amount_in_cited_chunk_bilingually_at_10"])
        self.assertEqual(result["acceptance_summary"],
                         "CITED_EXACT_AMOUNT_BILINGUALLY_RETRIEVED_NEEDS_ROW_ASSOCIATION")
        self.assertFalse(result["acceptance_gates"]["financial_row_association_machine_verified"])

    def test_amount_present_on_verified_pages_is_not_a_retrieval_pass(self):
        pages = (
            ExtractedPage(140, "19,641,705"),
            ExtractedPage(142, "19,641,705"),
        )
        indexed = SimpleNamespace(
            document=SimpleNamespace(pages=pages),
            chunks=(
                _row(pages[0].text, 140, "gold-140"),
                _row(pages[1].text, 142, "gold-142"),
            ),
        )
        report = assess_evidence(
            indexed, (_retrieval(114, "auditor"), _retrieval(11, "intro"))
        )
        self.assertEqual(report["gold_evidence_status"],
                         "EXACT_AMOUNT_EXTRACTED_ON_BOTH_VISUALLY_VERIFIED_PAGES")
        self.assertEqual(report["verified_gold_retrieval_status"],
                         "VERIFIED_GOLD_RETRIEVAL_GAP")

    def test_candidate_outside_top_10_is_not_accepted(self):
        evidence = "Revenue 19,642 SAR 2025"
        indexed = SimpleNamespace(
            document=SimpleNamespace(pages=(ExtractedPage(52, evidence),)),
            chunks=(_row(evidence, 52, "amount-chunk"),),
        )
        report = assess_evidence(
            indexed, (_retrieval(52, "amount-chunk", preceding=10),
                      _retrieval(52, "amount-chunk"))
        )
        self.assertEqual(report["legacy_same_page_word_match_status"], "RETRIEVAL_OR_EXTRACTION_GAP")
        self.assertFalse(report["languages"][0]["relevant_candidate_page_at_10"])

    def test_number_without_metric_is_not_a_candidate(self):
        indexed = SimpleNamespace(
            document=SimpleNamespace(pages=(ExtractedPage(50, "19,642 2025"),)),
            chunks=(_row("19,642 2025", 50, "numeric"),),
        )
        result = assess_evidence(
            indexed, (_retrieval(50, "numeric"), _retrieval(50, "numeric"))
        )
        self.assertEqual(result["candidate_pages"], [])
        self.assertEqual(result["legacy_same_page_word_match_status"], "RETRIEVAL_OR_EXTRACTION_GAP")

    def test_report_is_utf8_outside_source_directory(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source_dir = root / "source"
            source_dir.mkdir()
            pdf = source_dir / "sample.pdf"
            pdf.write_bytes(b"%PDF-1.4")
            report_path = root / "results" / "report.json"
            write_report(report_path, {"note": "إيرادات"}, pdf)
            self.assertEqual(json.loads(report_path.read_text("utf-8"))["note"], "إيرادات")
            with self.assertRaises(ValueError):
                write_report(source_dir / "report.json", {}, pdf)


if __name__ == "__main__":
    unittest.main()
