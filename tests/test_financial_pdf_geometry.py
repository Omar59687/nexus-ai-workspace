"""Resource-limited geometry worker response contract and source binding."""
from __future__ import annotations

import hashlib
import json
import unittest
from unittest.mock import patch

from nexus_ai.data_analytics import AnalyticsInputError
from nexus_ai.financial_pdf_geometry import extract_pdf_positions


class PdfGeometryTests(unittest.TestCase):
    def setUp(self):
        self.pdf = b"%PDF-1.4\nexample bytes\n"
        self.sha = hashlib.sha256(self.pdf).hexdigest()

    def call(self, **kwargs):
        defaults = dict(pdf=self.pdf, expected_sha256=self.sha, pages=(1, 2))
        defaults.update(kwargs)
        return extract_pdf_positions(**defaults)

    def test_bounded_worker_output_is_structured_by_page(self):
        payload = json.dumps({
            "status": "OK",
            "pages": {"1": [[100.5, 200.25, "2025"]],
                      "2": [[20.0, 40.0, "إجمالي الإيرادات"]]},
        }).encode("utf-8")
        with patch("nexus_ai.financial_pdf_geometry._require_platform_limits"), \
             patch("nexus_ai.financial_pdf_geometry._run_bounded_process",
                   return_value=payload) as run:
            result = self.call()
        self.assertEqual(result[1][0].text, "2025")
        self.assertEqual(result[2][0].page_number, 2)
        self.assertIn("--worker", run.call_args.args[0])
        self.assertIn("--max-boxes", run.call_args.args[0])
        self.assertLessEqual(run.call_args.kwargs["max_output_bytes"], 13000000)

    def test_digest_mismatch_rejected_before_worker(self):
        with patch("nexus_ai.financial_pdf_geometry._run_bounded_process") as worker:
            with self.assertRaises(AnalyticsInputError):
                self.call(expected_sha256="0" * 64)
            worker.assert_not_called()

    def test_invalid_page_and_resource_limits_blocked(self):
        for opts in ({"pages": (1, 1)}, {"pages": (0,)},
                     {"pages": (1, 2, 3, 4, 5, 6)},
                     {"max_boxes_per_page": 3001},
                     {"timeout_seconds": 0},
                     {"memory_limit_bytes": 100},
                     {"cpu_limit_seconds": 0}):
            with self.subTest(opts=opts), self.assertRaises(AnalyticsInputError):
                self.call(**opts)

    def test_worker_missing_pages_and_oversized_boxes_rejected(self):
        for payload in (
            {"status": "OK", "pages": {"1": [[10, 20, "text"]]}},
            {"status": "ABSTAIN"},
            {"status": "OK", "pages": {"1": [[10, 20, "text"]], "2": [[float("nan"), 1, "x"]]}},
            {"status": "OK", "pages": {"1": [[10, 20, "text"]], "2": [[1, 2, ""]]}},
        ):
            with self.subTest(payload=payload), \
                 patch("nexus_ai.financial_pdf_geometry._require_platform_limits"), \
                 patch("nexus_ai.financial_pdf_geometry._run_bounded_process",
                       return_value=json.dumps(payload).encode()):
                with self.assertRaises(AnalyticsInputError):
                    self.call()

    def test_never_relabels_worker_positions_as_reviewed_financial_facts(self):
        with patch("nexus_ai.financial_pdf_geometry._require_platform_limits"), \
             patch("nexus_ai.financial_pdf_geometry._run_bounded_process",
                   return_value=b'{"status":"OK","pages":{"1":[],"2":[]}}'):
            report = self.call()
            self.assertEqual(report, {1: (), 2: ()})


if __name__ == "__main__":
    unittest.main()
