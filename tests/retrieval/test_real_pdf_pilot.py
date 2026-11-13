"""No-model regression tests for opt-in real-PDF pilot entrypoints."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts.run_real_pdf_pilot import main, validate_pdf_path, run_pilot


class RealPdfPilotTests(unittest.TestCase):
    def test_pdf_path_must_be_absolute_existing_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "trusted.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")
            self.assertEqual(validate_pdf_path(str(pdf)), pdf.resolve())
            for candidate in ("relative.pdf", str(root), str(root / "missing.pdf"), str(root / "note.txt")):
                with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                    validate_pdf_path(candidate)

    def test_question_validation_rejects_empty_without_loading_models(self):
        with self.assertRaisesRegex(ValueError, "question must"):
            run_pilot(Path("does-not-exist.pdf"), " ")
        with self.assertRaisesRegex(ValueError, "question must"):
            run_pilot(Path("does-not-exist.pdf"), "x" * 8001)

    def test_entrypoint_requires_explicit_live_opt_in(self):
        with self.assertRaises(SystemExit) as raised:
            main(["--pdf", "x.pdf", "--question", "Q"])
        self.assertEqual(raised.exception.code, 2)

    def test_model_failure_emits_safe_blocked_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "trusted.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")
            report = root / "pilot.json"
            with patch("scripts.run_real_pdf_pilot.run_pilot", side_effect=RuntimeError("private PDF text")):
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    status = main([
                        "--run-live", "--pdf", str(pdf),
                        "--question", "What is revenue?", "--report", str(report),
                    ])
            self.assertEqual(status, 1)
            self.assertEqual(json.loads(stdout.getvalue())["status"], "BLOCKED")
            self.assertNotIn("private PDF text", report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
