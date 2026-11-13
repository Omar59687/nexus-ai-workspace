"""Regression coverage for whitespace-only spans from real PDF extraction."""
import unittest
from types import SimpleNamespace

from nexus_ai.retrieval.embeddings import create_text_windows


def chunk(text: str):
    return SimpleNamespace(
        chunk_id="chunk-1",
        document_id="doc-1",
        version_id="v1",
        page_number=7,
        start_char=100,
        offsets_reliable=True,
        text=text,
    )


class PdfWhitespaceWindowTests(unittest.TestCase):
    def test_whitespace_only_windows_are_skipped_without_shifting_offsets(self):
        text = "    " + "Annual revenue 42 million." + (" " * 12)
        windows = create_text_windows((chunk(text),), window_chars=12, overlap_chars=2)
        self.assertTrue(windows)
        self.assertTrue(all(row.text.strip() for row in windows))
        for row in windows:
            self.assertEqual(row.text, text[row.local_start:row.local_end])
            self.assertEqual(row.start_char, 100 + row.local_start)
            self.assertEqual(row.end_char, 100 + row.local_end)
            self.assertEqual(row.page_number, 7)

    def test_entirely_whitespace_chunk_produces_no_embedding_windows(self):
        windows = create_text_windows(
            (chunk(" " * 22),), window_chars=10, overlap_chars=2
        )
        self.assertEqual(windows, ())

    def test_normal_chunks_keep_deterministic_window_ids(self):
        text = "Revenue was 42 million dollars."
        first = create_text_windows((chunk(text),), window_chars=15, overlap_chars=4)
        second = create_text_windows((chunk(text),), window_chars=15, overlap_chars=4)
        self.assertEqual(first, second)
        self.assertTrue(all(row.text.strip() for row in first))


if __name__ == "__main__":
    unittest.main()
