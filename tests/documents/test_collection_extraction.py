"""Focused model-free extraction tests, including fail-closed PDF worker gate."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nexus_ai.documents.collection_extraction import extract_collection
from nexus_ai.documents.types import ExtractedPage, ExtractionResult
from scripts.extract_document_collection import main


def item(path, company="Mobily", year=2025):
    return {"path": path, "company": company, "year": year}


class CollectionExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "reports"
        self.root.mkdir()

    def test_multilingual_text_and_metadata_without_model(self):
        (self.root / "ar.txt").write_text("إيرادات الشركة ٤٢ مليون", encoding="utf-8")
        (self.root / "en.md").write_text("Revenue was 42 million.", encoding="utf-8")
        results = extract_collection(
            self.root, [item("ar.txt", company="موبايلي"), item("en.md", year=2024)]
        )
        self.assertEqual(results["status"], "PASS")
        self.assertEqual(results["extracted_count"], 2)
        self.assertEqual(results["documents"][0]["text_pages"], 1)
        self.assertEqual(results["scope"]["embeddings"], "NONE")
        self.assertNotIn("إيرادات الشركة", json.dumps(results, ensure_ascii=False))

    def test_duplicate_avoids_second_extraction(self):
        (self.root / "one.txt").write_text("revenue 42", encoding="utf-8")
        (self.root / "two.txt").write_text("revenue 42", encoding="utf-8")
        results = extract_collection(self.root, [item("one.txt"), item("two.txt")])
        self.assertEqual(results["extracted_count"], 1)
        self.assertEqual(results["duplicate_count"], 1)
        self.assertEqual(results["documents"][1]["duplicate_of"], "one.txt")

    def test_failed_document_does_not_block_other_documents(self):
        (self.root / "valid.txt").write_text("revenue", encoding="utf-8")
        (self.root / "bad.txt").write_bytes(b"\xff\xfe")
        result = extract_collection(self.root, [
            item("missing.pdf"), item("bad.txt"), item("valid.txt")
        ])
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["blocked_count"], 2)
        self.assertEqual(result["extracted_count"], 1)
        self.assertEqual(result["documents"][1]["reason"], "extraction_failed_or_no_text")

    def test_rejects_pdf_without_isolated_worker(self):
        (self.root / "a.pdf").write_bytes(b"%PDF-1.4")
        class Unsafe:
            isolation_enforced = False
            def extract(self, content, *, source_path):
                raise AssertionError("must not parse")
        with patch("nexus_ai.documents.collection_extraction.extractor_for_path", return_value=Unsafe()):
            result = extract_collection(self.root, [item("a.pdf")])
        self.assertEqual(result["blocked_count"], 1)
        self.assertEqual(result["documents"][0]["reason"], "extraction_failed_or_no_text")

    def test_worker_metadata_never_persists_pdf_text(self):
        (self.root / "a.pdf").write_bytes(b"%PDF-1.4")
        class Safe:
            isolation_enforced = True
            def extract(self, content, *, source_path):
                return ExtractionResult(
                    "test-worker", "1", "application/pdf",
                    (ExtractedPage(1, "CONFIDENTIAL FACT 100"), ExtractedPage(2, "")),
                    ("one warning",), True,
                )
        with patch("nexus_ai.documents.collection_extraction.extractor_for_path", return_value=Safe()):
            result = extract_collection(self.root, [item("a.pdf")])
        self.assertEqual(result["documents"][0]["page_count"], 2)
        self.assertEqual(result["documents"][0]["text_pages"], 1)
        self.assertEqual(result["documents"][0]["source_warning_count"], 1)
        self.assertNotIn("CONFIDENTIAL", json.dumps(result))

    def test_cli_writes_outside_root_only(self):
        (self.root / "a.txt").write_text("revenue", encoding="utf-8")
        manifest = Path(self.temp.name) / "manifest.json"
        report = Path(self.temp.name) / "result.json"
        manifest.write_text(json.dumps({"documents": [item("a.txt")]}), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            code = main(["--run-extraction", "--root", str(self.root),
                         "--manifest", str(manifest), "--report", str(report)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(report.read_text())["extracted_count"], 1)
        with contextlib.redirect_stdout(io.StringIO()):
            code = main(["--run-extraction", "--root", str(self.root),
                         "--manifest", str(manifest),
                         "--report", str(self.root / "out.json")])
        self.assertEqual(code, 1)
        self.assertFalse((self.root / "out.json").exists())


if __name__ == "__main__":
    unittest.main()
