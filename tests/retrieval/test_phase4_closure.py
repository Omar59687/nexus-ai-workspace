"""Closure regressions: Windows Arabic args and empty-corpus version fencing."""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.inspect_financial_pdf_page import main


class PdfForensicsJsonInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "inputs"
        self.source.mkdir()
        self.pdf = self.source / "sample.pdf"
        self.pdf.write_bytes(b"%PDF-1.4")
        self.output = self.root / "results" / "out.json"
        self.anchors = self.root / "terms.json"
        self.anchors.write_text(
            json.dumps(["إيرادات", "19.6", "2025"], ensure_ascii=True),
            encoding="utf-8",
        )

    def test_ascii_escaped_arabic_json_round_trips_to_forensic_engine(self):
        expected = ["إيرادات", "19.6", "2025"]
        report = {
            "status": "PASS", "page_count": 142, "findings": {
                "all_anchors_present_on_page": True,
                "all_anchors_share_chunk": False,
                "all_anchors_within_line_window": True,
            }
        }
        with patch("scripts.inspect_financial_pdf_page.run_page_forensics", return_value=report) as run:
            with contextlib.redirect_stdout(io.StringIO()):
                status = main([
                    "--run", "--pdf", str(self.pdf), "--year", "2025",
                    "--page", "114", "--anchors-json", str(self.anchors),
                    "--report", str(self.output),
                ])
        self.assertEqual(status, 0)
        self.assertEqual(run.call_args.kwargs["anchors"], expected)
        self.assertEqual(json.loads(self.output.read_text(encoding="utf-8")), report)
        self.assertFalse(self.output.read_bytes().startswith(b"\xff\xfe"))

    def test_rejects_malformed_json_without_running_pdf_parser(self):
        self.anchors.write_text("[malformed", encoding="utf-8")
        with patch("scripts.inspect_financial_pdf_page.run_page_forensics") as run:
            with contextlib.redirect_stdout(io.StringIO()):
                code = main([
                    "--run", "--pdf", str(self.pdf), "--year", "2025",
                    "--page", "114", "--anchors-json", str(self.anchors),
                    "--report", str(self.output),
                ])
        self.assertEqual(code, 1)
        run.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_no_report_next_to_source_pdf(self):
        with patch("scripts.inspect_financial_pdf_page.run_page_forensics") as run:
            with contextlib.redirect_stdout(io.StringIO()):
                status = main([
                    "--run", "--pdf", str(self.pdf), "--year", "2025",
                    "--page", "114", "--anchors-json", str(self.anchors),
                    "--report", str(self.source / "forbidden.json"),
                ])
        self.assertEqual(status, 1)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
