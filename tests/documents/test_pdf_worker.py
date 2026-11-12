import os
import tempfile
import unittest
from pathlib import Path

from nexus_ai.documents.pdf_worker import (
    IsolatedPdfExtractor,
    PdfIsolationUnavailableError,
    PdfWorkerExtractionError,
    PdfWorkerOutputLimitError,
    PdfWorkerTimeoutError,
)


def _script(root: Path, name: str, body: str) -> Path:
    path = root / name
    path.write_text(body, encoding="utf-8")
    return path


@unittest.skipUnless(os.name == "posix", "the POSIX worker runner is intentionally fail-closed elsewhere")
class IsolatedPdfWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_returns_page_aware_result_from_child_json(self):
        worker = _script(
            self.root,
            "fake_success.py",
            "import sys\n"
            "sys.stdin.buffer.read()\n"
            "sys.stdout.write('{\"pages\":[{\"page_number\":1,\"text\":\"English\"},{\"page_number\":2,\"text\":\"عربي\"}],\"warnings\":[\"page 3 empty\"],\"parser_version\":\"fake-1\"}')\n",
        )
        result = IsolatedPdfExtractor(worker_script=worker).extract(b"fake-pdf", source_path="report.pdf")
        self.assertEqual([page.page_number for page in result.pages], [1, 2])
        self.assertEqual([page.text for page in result.pages], ["English", "عربي"])
        self.assertEqual(result.warnings, ("page 3 empty",))
        self.assertEqual(result.extractor_version, "fake-1")

    def test_maps_known_parser_errors_without_exposing_worker_output(self):
        worker = _script(self.root, "fake_error.py", "import sys\nsys.stdin.buffer.read()\nprint('{\"error\":\"encrypted\"}')\nsys.exit(2)\n")
        with self.assertRaisesRegex(PdfWorkerExtractionError, "encrypted PDFs") as raised:
            IsolatedPdfExtractor(worker_script=worker).extract(b"pdf", source_path="private.pdf")
        self.assertEqual(raised.exception.reason_code, "encrypted")

    def test_wall_clock_timeout_kills_child(self):
        worker = _script(self.root, "fake_slow.py", "import sys,time\nsys.stdin.buffer.read()\ntime.sleep(5)\n")
        with self.assertRaises(PdfWorkerTimeoutError):
            IsolatedPdfExtractor(worker_script=worker, timeout_seconds=0.1).extract(b"pdf", source_path="slow.pdf")

    def test_stdout_is_capped_even_for_a_misbehaving_worker(self):
        worker = _script(self.root, "fake_flood.py", "import sys\nsys.stdin.buffer.read()\nsys.stdout.write('x'*100000)\nsys.stdout.flush()\n")
        extractor = IsolatedPdfExtractor(
            worker_script=worker, max_total_chars=1, max_pages=1,
            timeout_seconds=2,
        )
        with self.assertRaises(PdfWorkerOutputLimitError):
            extractor.extract(b"pdf", source_path="large.pdf")

    def test_input_cap_rejects_before_starting_worker(self):
        worker = _script(self.root, "must_not_run.py", "raise RuntimeError('must not execute')\n")
        extractor = IsolatedPdfExtractor(worker_script=worker, max_input_bytes=2)
        with self.assertRaisesRegex(ValueError, "byte limit"):
            extractor.extract(b"three", source_path="large.pdf")

    def test_invalid_worker_payload_fails_closed(self):
        worker = _script(self.root, "fake_invalid.py", "import sys\nsys.stdin.buffer.read()\nprint('{}')\n")
        with self.assertRaises(PdfWorkerExtractionError):
            IsolatedPdfExtractor(worker_script=worker).extract(b"pdf", source_path="bad.pdf")


class PdfWorkerConfigurationTests(unittest.TestCase):
    def test_invalid_limits_are_rejected(self):
        for kwargs in (
            {"max_input_bytes": 0},
            {"max_total_chars": -1},
            {"timeout_seconds": float("inf")},
            {"memory_limit_bytes": 0},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                IsolatedPdfExtractor(**kwargs)

    def test_windows_platform_fails_closed_without_job_object_support(self):
        from unittest.mock import patch
        extractor = IsolatedPdfExtractor()
        with patch("nexus_ai.documents.pdf_worker.os.name", "nt"):
            with self.assertRaises(PdfIsolationUnavailableError):
                extractor.extract(b"pdf", source_path="report.pdf")


if __name__ == "__main__":
    unittest.main()
