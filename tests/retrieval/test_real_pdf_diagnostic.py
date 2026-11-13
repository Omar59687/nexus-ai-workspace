"""Real-PDF diagnostic workflow tests without real PDF bytes or models."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nexus_ai.benchmark.real_pdf_diagnostic import run_diagnostic
from nexus_ai.documents.types import ExtractedPage, ExtractionResult
from scripts.diagnose_real_pdf_evidence import main


class RealPdfDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "approved"
        self.root.mkdir()
        self.pdf = self.root / "financial.pdf"
        self.pdf.write_bytes(b"%PDF-1.4 deterministic dummy")
        self.report = Path(self.temp.name) / "out.json"

    def _fake_pdf(self):
        class FakeIsolatedPdf:
            isolation_enforced = True
            name = "isolated-fixture"
            version = "1"
            media_type = "application/pdf"

            def extract(self, content, *, source_path):
                return ExtractionResult(
                    "isolated-fixture", "1", "application/pdf",
                    (
                        ExtractedPage(1, "Mobily 2025 revenue 88 million SAR.\n"),
                        ExtractedPage(2, "شركة موبايلي إيرادات ٢٠٢٥ ثمانية وثمانون مليون ريال.\n"),
                        ExtractedPage(3, ""),
                    ), (), True,
                )
        return FakeIsolatedPdf()

    def test_citations_and_page_coverage_without_text_leak(self):
        with patch("nexus_ai.documents.collection_index.extractor_for_path",
                   return_value=self._fake_pdf()):
            result = run_diagnostic(
                self.pdf, company="Mobily", year=2025,
                queries=["Mobily 2025 revenue SAR", "إيرادات موبايلي"],
            )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["source"]["page_count"], 3)
        self.assertEqual(result["source"]["nonblank_page_count"], 2)
        self.assertEqual(len(result["queries"]), 2)
        self.assertEqual(result["queries"][0]["matches"][0]["page_number"], 1)
        self.assertTrue(result["queries"][0]["matches"][0]["citation_offsets_validated"])
        as_json = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("88 million", as_json)
        self.assertNotIn("إيرادات موبايلي", as_json)
        self.assertEqual(result["scope"]["embeddings"], "NONE")

    def test_cli_writes_utf8_without_shell_redirection(self):
        with patch("nexus_ai.documents.collection_index.extractor_for_path",
                   return_value=self._fake_pdf()):
            import contextlib
            import io
            with contextlib.redirect_stdout(io.StringIO()):
                code = main([
                    "--run", "--pdf", str(self.pdf), "--company", "موبايلي",
                    "--year", "2025", "--query", "إيرادات موبايلي",
                    "--report", str(self.report),
                ])
        self.assertEqual(code, 0)
        raw = self.report.read_bytes()
        self.assertFalse(raw.startswith(b"\xff\xfe"))
        self.assertEqual(json.loads(raw.decode("utf-8"))["status"], "PASS")

    def test_output_inside_pdf_root_is_rejected(self):
        with patch("nexus_ai.documents.collection_index.extractor_for_path",
                   return_value=self._fake_pdf()):
            import contextlib
            import io
            with contextlib.redirect_stdout(io.StringIO()):
                code = main([
                    "--run", "--pdf", str(self.pdf), "--company", "Mobily",
                    "--year", "2025", "--query", "revenue",
                    "--report", str(self.root / "forbidden.json"),
                ])
        self.assertEqual(code, 1)
        self.assertFalse((self.root / "forbidden.json").exists())

    def test_invalid_labels_and_queries_fail_before_file_indexing(self):
        with self.assertRaises(ValueError):
            run_diagnostic(self.pdf, company="Mobily", year=2025, queries=[])
        with self.assertRaises(ValueError):
            run_diagnostic(self.pdf, company="Mobily", year=True, queries=["revenue"])
        with self.assertRaises(ValueError):
            run_diagnostic(self.pdf, company="Mobily", year=2025, queries=[" "])

    def test_broken_pdf_extract_fails_closed_and_reports_no_text(self):
        class FaultyIsolated:
            isolation_enforced = True
            def extract(self, content, *, source_path):
                raise ValueError("secret document text")
        with patch("nexus_ai.documents.collection_index.extractor_for_path",
                   return_value=FaultyIsolated()):
            result = run_diagnostic(
                self.pdf, company="Mobily", year=2025,
                queries=["revenue"],
            )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertNotIn("secret document text", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
