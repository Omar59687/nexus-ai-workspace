"""Page-context expansion must retain source identity and honest evidence types."""
from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace

from nexus_ai.documents.types import ExtractedPage, SourceChunk
from nexus_ai.retrieval.company_metadata import MetadataIntegrityError
from nexus_ai.retrieval.page_context import expand_page_context
from nexus_ai.retrieval.schemas import EvidenceCitation, RetrievedEvidence, RetrievalResponse


def _chunk(page, text):
    return SourceChunk(
        chunk_id=f"chunk-{page}", document_id="document", version_id="version",
        source_path="report.pdf", source_sha256="sha256",
        extractor_name="pypdf", extractor_version="1", page_number=page,
        start_char=0, end_char=len(text), start_line=1, end_line=1,
        text=text, heading_path=(), offsets_reliable=True, chunker_version="v1",
    )


def _hit(chunk):
    return RetrievedEvidence(
        score=7.1, score_type="bm25", strategy="bm25_raw",
        citation=EvidenceCitation(
            workspace_id="authorized", document_id=chunk.document_id,
            document_version_id=chunk.version_id, source_path=chunk.source_path,
            source_sha256=chunk.source_sha256, page_number=chunk.page_number,
            chunk_id=chunk.chunk_id, start_char=chunk.start_char,
            end_char=chunk.end_char, matched_window_id=None,
            matched_window_start_char=None, matched_window_end_char=None,
            offsets_reliable=True, exact_text=chunk.text,
        ),
    )


class Repo:
    def __init__(self, indexed):
        self.indexed = indexed

    def get_active(self, workspace, document):
        if workspace != "authorized" or document != "document":
            return None
        return self.indexed


class PageContextTests(unittest.TestCase):
    def setUp(self):
        texts = {
            140: "١٩٬٦٤١٬٧٠٥ 2025\n18,206,447 2024\nother numbers 1,000,000",
            141: "Audit discussion about revenue recognition in 2025",
            142: "Operating segments 19,641,705 / 2025\n2024 18,206,447",
            20: "Introductory overview about annual strategy",
        }
        pages = tuple(ExtractedPage(page, text) for page, text in texts.items())
        chunks = tuple(_chunk(page, text) for page, text in texts.items())
        self.repo = Repo(SimpleNamespace(
            document=SimpleNamespace(
                workspace_id="authorized", version_id="version",
                content_sha256="sha256", source_path="report.pdf", pages=pages,
            ), chunks=chunks,
        ))
        self.raw = RetrievalResponse(
            workspace_id="authorized", status="ok", strategy="bm25_raw",
            results=[_hit(chunks[1]), _hit(chunks[3])],
        )

    def test_adjacent_pages_are_retrieved_without_gold_amount_input(self):
        result = expand_page_context(
            self.raw, repository=self.repo, workspace_id="authorized",
            top_k=5, radius=1,
        )
        self.assertEqual([hit.citation.page_number for hit in result.results[:3]],
                         [141, 140, 142])
        self.assertEqual(result.strategy, "bm25_page_context")
        self.assertEqual(result.results[0].strategy, "bm25_raw")
        self.assertTrue(all(x.strategy == "adjacent_page_context" and x.score_type == "context"
                            for x in result.results[1:3]))
        self.assertEqual(result.results[1].citation.exact_text,
                         self.repo.indexed.document.pages[0].text)

    def test_context_does_not_copy_unrelated_or_cross_tenant_pages(self):
        result = expand_page_context(
            self.raw, repository=self.repo, workspace_id="authorized", top_k=3,
        )
        self.assertEqual([x.citation.page_number for x in result.results], [141, 140, 142])
        with self.assertRaises(MetadataIntegrityError):
            expand_page_context(self.raw, repository=self.repo, workspace_id="other")

    def test_untrusted_active_source_version_rejected(self):
        original = self.repo.indexed
        self.repo.indexed = replace(original, document=replace(
            original.document, version_id="replaced"
        )) if hasattr(original, "__dataclass_fields__") else SimpleNamespace(
            document=SimpleNamespace(
                workspace_id="authorized", version_id="replaced",
                content_sha256="sha256", source_path="report.pdf",
                pages=original.document.pages,
            ),
            chunks=original.chunks,
        )
        with self.assertRaises(MetadataIntegrityError):
            expand_page_context(self.raw, repository=self.repo, workspace_id="authorized")

    def test_context_never_accepts_corrupted_offsets(self):
        source = self.repo.indexed
        corrupt = replace(source.chunks[0], text="source tampered")
        self.repo.indexed = SimpleNamespace(document=source.document,
                                            chunks=(corrupt, *source.chunks[1:]))
        with self.assertRaises(MetadataIntegrityError):
            expand_page_context(self.raw, repository=self.repo, workspace_id="authorized")

    def test_radius_zero_preserves_raw_top_k(self):
        result = expand_page_context(
            self.raw, repository=self.repo, workspace_id="authorized",
            radius=0, top_k=1,
        )
        self.assertEqual(len(result.results), 1)
        self.assertEqual(result.results[0].citation.page_number, 141)


if __name__ == "__main__":
    unittest.main()
