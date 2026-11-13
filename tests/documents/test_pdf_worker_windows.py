"""Windows-only tests for the native Job Object PDF worker.

All PDFs are generated in memory by this module. No owner document or external
corpus is read by these tests.
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from nexus_ai.documents.pdf_worker import (
    IsolatedPdfExtractor,
    PdfWorkerExtractionError,
    PdfWorkerOutputLimitError,
    PdfWorkerTimeoutError,
)


def _generated_pdf(pages: tuple[str, ...]) -> bytes:
    """Build a small, text-layer PDF without a filesystem fixture."""
    objects: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>"]
    page_ids = [3 + index * 3 for index in range(len(pages))]
    kids = b" ".join(f"{page_id} 0 R".encode("ascii") for page_id in page_ids)
    objects.append(b"<< /Type /Pages /Kids [" + kids + f"] /Count {len(pages)} >>".encode("ascii"))
    for page_id, text in zip(page_ids, pages):
        content_id = page_id + 2
        safe_text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 30 250 Td ({safe_text}) Tj ET".encode("ascii")
        objects.extend([
            (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] "
             f"/Resources << /Font << /F1 {page_id + 1} 0 R >> >> "
             f"/Contents {content_id} 0 R >>").encode("ascii"),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
        ])
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, item in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii"))
        output.extend(item)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(output)


def _script(root: Path, name: str, body: str) -> Path:
    path = root / name
    path.write_text(body, encoding="utf-8")
    return path


@unittest.skipUnless(os.name == "nt", "Job Object enforcement requires Windows")
class WindowsPdfWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_generated_text_pdf_preserves_page_numbers_and_text(self):
        result = IsolatedPdfExtractor().extract(
            _generated_pdf(("Nexus generated fixture page one", "Page two evidence")),
            source_path="generated.pdf",
        )
        self.assertEqual([page.page_number for page in result.pages], [1, 2])
        self.assertEqual(
            [page.text.strip() for page in result.pages],
            ["Nexus generated fixture page one", "Page two evidence"],
        )

    def test_ingestion_keeps_approved_root_source_and_version_provenance(self):
        from nexus_ai.documents.service import DocumentIngestionService
        from nexus_ai.retrieval.repository import InMemoryDocumentIndex

        class FakeEmbedder:
            model_id = "fake/windows-pdf"
            revision = "0123456789abcdef0123456789abcdef01234567"
            preprocessing_id = "fake-windows-pdf-v1"
            embedding_dimensions = 2

            def embed(self, texts, *, input_type):
                return tuple((1.0, 0.25) for _ in texts)

        source = self.root / "owner-document.pdf"
        source.write_bytes(_generated_pdf(("Trusted local source has 42 units",)))
        repository = InMemoryDocumentIndex()
        service = DocumentIngestionService(
            approved_root=self.root,
            repository=repository,
            embedder=FakeEmbedder(),
        )
        result = service.ingest("windows-pdf-test", "owner-document.pdf")
        active = repository.get_active("windows-pdf-test", result.document_id)
        self.assertEqual(active.document.source_path, "owner-document.pdf")
        self.assertEqual(active.document.content_sha256, result.source_sha256)
        self.assertEqual([page.page_number for page in active.document.pages], [1])
        self.assertIn("Trusted local source has 42 units", active.document.pages[0].text)

        empty_path = self.root / "generated-empty.pdf"
        empty_path.write_bytes(_generated_pdf(("",)))
        with self.assertRaisesRegex(ValueError, "no extractable text"):
            service.ingest("windows-pdf-test", "generated-empty.pdf")

    def test_rejects_corrupt_encrypted_empty_oversized_page_and_input(self):
        with self.assertRaises(PdfWorkerExtractionError) as corrupt:
            IsolatedPdfExtractor().extract(b"not a PDF", source_path="generated-corrupt.pdf")
        self.assertEqual(corrupt.exception.reason_code, "corrupt")

        from pypdf import PdfWriter

        encrypted = PdfWriter()
        encrypted.add_blank_page(width=72, height=72)
        encrypted.encrypt("test-password")
        encrypted_bytes = io.BytesIO()
        encrypted.write(encrypted_bytes)
        with self.assertRaises(PdfWorkerExtractionError) as encrypted_error:
            IsolatedPdfExtractor().extract(encrypted_bytes.getvalue(), source_path="generated-encrypted.pdf")
        self.assertEqual(encrypted_error.exception.reason_code, "encrypted")

        empty = IsolatedPdfExtractor().extract(_generated_pdf(("",)), source_path="generated-empty.pdf")
        self.assertEqual(empty.pages[0].text.strip(), "")
        self.assertTrue(empty.warnings)
        with self.assertRaises(PdfWorkerExtractionError) as page_limit:
            IsolatedPdfExtractor(max_pages=1).extract(
                _generated_pdf(("one", "two")), source_path="generated-two-page.pdf"
            )
        self.assertEqual(page_limit.exception.reason_code, "page_limit")
        with self.assertRaises(PdfWorkerExtractionError) as page_chars:
            IsolatedPdfExtractor(max_page_chars=8).extract(
                _generated_pdf(("text is too long",)), source_path="generated-page-limit.pdf"
            )
        self.assertEqual(page_chars.exception.reason_code, "page_char_limit")
        with self.assertRaises(PdfWorkerExtractionError) as total_chars:
            IsolatedPdfExtractor(max_total_chars=10).extract(
                _generated_pdf(("12345678", "abcdefgh")), source_path="generated-total-limit.pdf"
            )
        self.assertEqual(total_chars.exception.reason_code, "total_char_limit")
        with self.assertRaisesRegex(ValueError, "byte limit"):
            IsolatedPdfExtractor(max_input_bytes=8).extract(
                _generated_pdf(("too many bytes",)), source_path="generated-input-limit.pdf"
            )

    def test_timeout_kills_worker_and_descendant(self):
        marker = self.root / "descendant-survived.txt"
        descendant = (
            "import pathlib,time; time.sleep(0.6); "
            f"pathlib.Path({str(marker)!r}).write_text('survived')"
        )
        worker = _script(
            self.root, "spawn_child.py",
            "import subprocess,sys,time\n"
            f"subprocess.Popen([sys.executable, '-c', {descendant!r}])\n"
            "time.sleep(20)\n",
        )
        with self.assertRaises(PdfWorkerTimeoutError):
            IsolatedPdfExtractor(worker_script=worker, timeout_seconds=0.2).extract(
                b"fixture", source_path="generated-timeout.pdf"
            )
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            self.assertFalse(marker.exists(), "a worker descendant survived Job Object termination")
            time.sleep(0.02)

    def test_output_flood_and_memory_exhaustion_are_bounded(self):
        flood = _script(
            self.root, "flood.py",
            "import sys\nsys.stdin.buffer.read()\nsys.stdout.write('x' * 10000000)\nsys.stdout.flush()\n",
        )
        with self.assertRaises(PdfWorkerOutputLimitError):
            IsolatedPdfExtractor(
                worker_script=flood, max_total_chars=1, max_pages=1, timeout_seconds=5,
            ).extract(b"fixture", source_path="generated-flood.pdf")

        exhaust = _script(
            self.root, "allocate.py",
            "import sys\nsys.stdin.buffer.read()\nblocks=[]\n"
            "while True: blocks.append(bytearray(8 * 1024 * 1024))\n",
        )
        with self.assertRaises(PdfWorkerExtractionError):
            IsolatedPdfExtractor(
                worker_script=exhaust, memory_limit_bytes=256 * 1024 * 1024,
                timeout_seconds=20,
            ).extract(b"fixture", source_path="generated-memory-limit.pdf")

    def test_job_cpu_time_limit_terminates_worker(self):
        busy = _script(
            self.root, "busy.py",
            "import sys\nsys.stdin.buffer.read()\nwhile True: pass\n",
        )
        started = time.monotonic()
        with self.assertRaises(PdfWorkerExtractionError):
            IsolatedPdfExtractor(
                worker_script=busy, cpu_limit_seconds=1, timeout_seconds=10,
            ).extract(b"fixture", source_path="generated-cpu-limit.pdf")
        self.assertLess(time.monotonic() - started, 6.0)

    def test_concurrent_generated_pdf_ingestions_remain_isolated(self):
        from nexus_ai.documents.service import DocumentIngestionService
        from nexus_ai.retrieval.repository import InMemoryDocumentIndex

        class FakeEmbedder:
            model_id = "fake/windows-pdf-concurrency"
            revision = "0123456789abcdef0123456789abcdef01234567"
            preprocessing_id = "fake-windows-pdf-concurrency-v1"
            embedding_dimensions = 2

            def embed(self, texts, *, input_type):
                return tuple((1.0, 0.25) for _ in texts)

        repo = InMemoryDocumentIndex()
        service = DocumentIngestionService(
            approved_root=self.root,
            repository=repo,
            embedder=FakeEmbedder(),
        )
        for index in range(4):
            (self.root / f"generated-{index}.pdf").write_bytes(
                _generated_pdf((f"parallel generated document {index}",))
            )

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = tuple(pool.map(
                lambda index: service.ingest("parallel-pdf-test", f"generated-{index}.pdf"),
                range(4),
            ))
        self.assertEqual(len(results), 4)
        active = repo.list_active("parallel-pdf-test")
        self.assertEqual(len(active), 4)
        self.assertEqual(
            {document.document.source_path for document in active},
            {f"generated-{index}.pdf" for index in range(4)},
        )


if __name__ == "__main__":
    unittest.main()
