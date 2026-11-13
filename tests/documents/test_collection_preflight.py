"""Fast, model-free checks for explicit 50–150-file collection inventory."""
import json
import tempfile
import unittest
from pathlib import Path

from nexus_ai.documents.collection_preflight import (
    CollectionManifestError, _manifest_entries,
    load_collection_manifest, preflight_collection,
)
from scripts.preflight_document_collection import main


def doc(path, company="Mobily", year=2025):
    return {"path": path, "company": company, "year": year}


class CollectionPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "docs"
        self.root.mkdir()

    def test_valid_metadata_duplicate_bytes_and_explicit_scope(self):
        (self.root / "one.pdf").write_bytes(b"%PDF sample")
        (self.root / "two.pdf").write_bytes(b"%PDF sample")
        result = preflight_collection(
            self.root, [doc("one.pdf"), doc("two.pdf", year=2024)]
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["ready_count"], 2)
        self.assertEqual(result["duplicate_content_count"], 1)
        self.assertEqual(result["documents"][1]["duplicate_of"], "one.pdf")
        self.assertEqual(result["scope"]["model_calls"], "NONE")
        self.assertEqual(result["scope"]["directory_crawling"], "NONE")

    def test_arabic_company_labels_are_supported(self):
        (self.root / "mobily.pdf").write_bytes(b"trusted fixture")
        result = preflight_collection(
            self.root, [doc("mobily.pdf", company="شركة اتحاد اتصالات موبايلي")]
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(
            result["documents"][0]["company"], "شركة اتحاد اتصالات موبايلي"
        )

    def test_missing_and_oversized_files_are_isolated(self):
        (self.root / "small.pdf").write_bytes(b"12345")
        (self.root / "huge.pdf").write_bytes(b"123456789")
        result = preflight_collection(
            self.root, [doc("small.pdf"), doc("missing.pdf"), doc("huge.pdf")],
            max_file_bytes=7,
        )
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["ready_count"], 1)
        self.assertEqual(result["blocked_count"], 2)
        self.assertEqual(result["documents"][1]["reason"], "unreadable_unsafe_or_oversized")

    def test_rejects_unsafe_paths_duplicates_and_bad_metadata(self):
        invalid = [
            [doc("../secret.pdf")], [doc("C:/secret.pdf")],
            [doc("x\\secret.pdf")], [doc("/secret.pdf")],
            [doc("x.pdf"), doc("X.PDF")],
            [doc("x.pdf", year=True)], [doc("x.pdf", company="")],
            [doc("x.exe")], [doc("./x.pdf")],
            [doc("x//y.pdf")],
            [doc("x.pdf", year=2025)] * 151,
        ]
        for entries in invalid:
            with self.subTest(entries=entries[:2]), self.assertRaises(CollectionManifestError):
                _manifest_entries({"documents": entries})

    def test_rejects_link_and_preserves_unlisted_file(self):
        (self.root / "allowed.pdf").write_bytes(b"allowed")
        (self.root / "unlisted.pdf").write_bytes(b"not checked")
        link = self.root / "link.pdf"
        try:
            link.symlink_to(self.root / "allowed.pdf")
        except (OSError, NotImplementedError):
            self.skipTest("symlink unavailable in this environment")
        result = preflight_collection(self.root, [doc("link.pdf"), doc("allowed.pdf")])
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["ready_count"], 1)
        self.assertEqual(result["document_count"], 2)

    def test_manifest_and_cli_create_report_without_model_calls(self):
        (self.root / "report.pdf").write_bytes(b"dummy data")
        manifest = Path(self.temp.name) / "manifest.json"
        report = Path(self.temp.name) / "output.json"
        manifest.write_text(json.dumps({"documents": [doc("report.pdf")]}), encoding="utf-8")
        self.assertEqual(len(load_collection_manifest(manifest)), 1)
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            code = main(["--run-preflight", "--root", str(self.root),
                         "--manifest", str(manifest), "--report", str(report)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["ready_count"], 1)

    def test_rejects_report_inside_document_root(self):
        (self.root / "report.pdf").write_bytes(b"dummy data")
        manifest = Path(self.temp.name) / "manifest.json"
        manifest.write_text(json.dumps({"documents": [doc("report.pdf")]}), encoding="utf-8")
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            code = main(["--run-preflight", "--root", str(self.root),
                         "--manifest", str(manifest),
                         "--report", str(self.root / "inventory.json")])
        self.assertEqual(code, 1)
        self.assertFalse((self.root / "inventory.json").exists())


if __name__ == "__main__":
    unittest.main()
