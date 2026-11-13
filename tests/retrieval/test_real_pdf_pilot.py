"""No-model regression tests for opt-in real-PDF pilot entrypoints."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts.run_real_pdf_pilot import main, validate_pdf_path, run_pilot, PilotStageError


class RealPdfPilotTests(unittest.TestCase):
    def test_pdf_path_must_be_absolute_existing_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "trusted.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")
            self.assertEqual(validate_pdf_path(str(pdf)), pdf.resolve())
            self.assertEqual(validate_pdf_path('  "' + str(pdf) + '"  '), pdf.resolve())
            self.assertEqual(validate_pdf_path(str(pdf) + "  "), pdf.resolve())
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

    def test_safe_stage_error_classification_does_not_expose_pdf_text(self):
        limited = PilotStageError(
            "ingestion", ValueError("index exceeds max_vector_coordinates before embedding")
        )
        self.assertEqual(limited.stage, "ingestion")
        self.assertEqual(limited.reason_code, "vector_coordinate_budget_exceeded")
        private = PilotStageError("ingestion", ValueError("confidential PDF revenue value: 123"))
        self.assertEqual(private.reason_code, "value_error_unclassified")
        self.assertNotIn("confidential", str(private))

    def test_stage_and_reason_are_in_blocked_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "trusted.pdf"
            pdf.write_bytes(b"%PDF-1.4\\n")
            with patch("scripts.run_real_pdf_pilot.run_pilot",
                       side_effect=PilotStageError(
                           "ingestion", ValueError("index exceeds max_windows before embedding"))):
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    status = main(["--run-live", "--pdf", str(pdf), "--question", "Revenue?"])
            result = json.loads(stdout.getvalue())
            self.assertEqual(status, 1)
            self.assertEqual(result["failed_stage"], "ingestion")
            self.assertEqual(result["reason_code"], "text_window_limit_exceeded")

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
