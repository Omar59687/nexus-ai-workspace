import tempfile
import threading
import unittest
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from nexus_ai.documents.chunking import ChunkingConfig, SourceAwareChunker
from nexus_ai.documents.service import DocumentIngestionLimits, DocumentIngestionService
from nexus_ai.documents.types import RetrievalFilters
from nexus_ai.retrieval.embeddings import EmbeddingUnavailableError
from nexus_ai.retrieval.repository import InMemoryDocumentIndex, RepositoryLimits
from nexus_ai.retrieval.schemas import RetrievalRequest
from nexus_ai.retrieval.service import (
    CitationValidationError,
    IndexGenerationMismatchError,
    RetrievalConfig,
    RetrievalService,
    validate_citation,
)
from tests.documents.test_ingestion import FakeEmbedder


class RetrievalServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repository = InMemoryDocumentIndex()
        self.embedder = FakeEmbedder()
        self.ingestion = DocumentIngestionService(
            approved_root=self.root, repository=self.repository, embedder=self.embedder,
            chunker=SourceAwareChunker(ChunkingConfig(max_chars=44, overlap_chars=8)),
            limits=DocumentIngestionLimits(window_chars=18, window_overlap_chars=4),
        )
        self.retriever = RetrievalService(repository=self.repository, embedder=self.embedder)

    def _write_and_ingest(self, filename, content, workspace="workspace-a"):
        path = self.root / filename
        path.write_text(content, encoding="utf-8")
        return self.ingestion.ingest(workspace, filename)

    def test_windowed_e5_returns_verified_exact_citation_and_matched_window_offsets(self):
        english = "English report: needle supports revenue of 44 million. " * 3
        arabic = "تقرير عربي: الإيرادات ٧٧ مليون في هذا المصدر. " * 3
        en_result = self._write_and_ingest("en.md", english)
        ar_result = self._write_and_ingest("ar.md", arabic)
        response = self.retriever.retrieve("إيرادات", workspace_id="workspace-a", top_k=4)
        self.assertEqual(response.status, "ok")
        first = response.results[0]
        self.assertEqual(first.citation.document_id, ar_result.document_id)
        self.assertEqual(first.citation.document_version_id, ar_result.version_id)
        self.assertEqual(first.citation.source_path, "ar.md")
        active_ar = self.repository.get_active("workspace-a", ar_result.document_id)
        cited_chunk = next(chunk for chunk in active_ar.chunks if chunk.chunk_id == first.citation.chunk_id)
        page_text = active_ar.document.pages[0].text
        self.assertEqual(page_text[first.citation.start_char:first.citation.end_char], first.citation.exact_text)
        self.assertTrue(first.citation.offsets_reliable)
        self.assertEqual(first.score_type, "cosine_similarity")
        self.assertNotEqual(en_result.document_id, ar_result.document_id)
        self.assertIsNotNone(first.citation.matched_window_id)
        self.assertGreaterEqual(first.citation.matched_window_start_char, first.citation.start_char)
        self.assertLessEqual(first.citation.matched_window_end_char, first.citation.end_char)
        validate_citation(first.citation, active_ar.document.pages, cited_chunk)

    def test_bm25_is_an_explicit_opt_in_fallback_and_does_not_embed_query(self):
        result = self._write_and_ingest("facts.txt", "needle source has the verified answer 431.")
        call_count = len(self.embedder.calls)
        response = self.retriever.retrieve("needle", workspace_id="workspace-a", strategy="bm25_raw", top_k=2)
        self.assertEqual(response.status, "ok")
        self.assertEqual(response.results[0].citation.document_id, result.document_id)
        self.assertEqual(response.results[0].score_type, "bm25")
        self.assertEqual(len(self.embedder.calls), call_count)

    def test_streaming_bm25_matches_complete_corpus_reference_scores(self):
        self._write_and_ingest("one.txt", "needle revenue 42 and operating profit.")
        self._write_and_ingest("two.txt", "needle revenue 57 and expenses.")
        active = self.repository.list_active("workspace-a")
        from experiments.rag_prototype import BM25Index
        from nexus_ai.retrieval.service import _to_prototype_chunk
        all_chunks = [chunk for indexed in active for chunk in indexed.chunks]
        reference = BM25Index(tuple(_to_prototype_chunk(chunk) for chunk in all_chunks)).search("needle revenue", top_k=5)
        actual = self.retriever.retrieve("needle revenue", workspace_id="workspace-a", strategy="bm25_raw", top_k=5)
        self.assertEqual([row.citation.chunk_id for row in actual.results],
                         [hit.chunk.chunk_id for hit in reference])
        self.assertEqual([row.score for row in actual.results], [hit.score for hit in reference])

    def test_streaming_bm25_fails_if_active_generation_changes_between_passes(self):
        self._write_and_ingest("one.txt", "needle first pass snapshot.")
        original = self.repository.list_active("workspace-a")[0]

        class ChangingRepository:
            def __init__(self): self.passes = 0
            def iter_active(self, workspace_id, filters=None):
                self.passes += 1
                row = original if self.passes == 1 else replace(original, index_generation_id="f" * 64)
                yield row
            def list_active(self, workspace_id, filters=None):
                raise AssertionError("streaming BM25 must not materialize the corpus")

        service = RetrievalService(repository=ChangingRepository(), embedder=self.embedder)
        with self.assertRaisesRegex(RuntimeError, "changed during BM25"):
            service.retrieve("needle", workspace_id="workspace-a", strategy="bm25_raw")

    def test_empty_results_filters_and_workspace_isolation(self):
        result = self._write_and_ingest("facts.md", "needle evidence lives here.")
        other = self.retriever.retrieve("needle", workspace_id="workspace-b")
        self.assertEqual(other.status, "empty")
        self.assertEqual(other.results, [])
        by_document = self.retriever.retrieve("needle", workspace_id="workspace-a",
                                              filters=RetrievalFilters(document_id=result.document_id))
        self.assertEqual([row.citation.document_id for row in by_document.results], [result.document_id])
        by_other_doc = self.retriever.retrieve("needle", workspace_id="workspace-a",
                                               filters=RetrievalFilters(document_id="not-owned"))
        self.assertEqual(by_other_doc.status, "empty")
        by_page = self.retriever.retrieve("needle", workspace_id="workspace-a",
                                          filters=RetrievalFilters(page_number=2))
        self.assertEqual(by_page.status, "empty")

    def test_top_k_and_strategy_are_bounded_and_validated(self):
        self._write_and_ingest("facts.txt", "needle evidence")
        for top_k in (0, 21, True, 1.2):
            with self.subTest(top_k=top_k), self.assertRaises(ValueError):
                self.retriever.retrieve("needle", workspace_id="workspace-a", top_k=top_k)
        with self.assertRaisesRegex(ValueError, "unsupported"):
            self.retriever.retrieve("needle", workspace_id="workspace-a", strategy="hybrid")
        with self.assertRaisesRegex(ValueError, "non-empty"):
            self.retriever.retrieve("  ", workspace_id="workspace-a")
        self.assertEqual(RetrievalRequest(workspace_id="w", query="q").strategy, "windowed_e5")
        with self.assertRaises(ValueError):
            RetrievalRequest(workspace_id="w", query="q", top_k=99)

    def test_embedding_unavailable_is_distinct_from_empty_retrieval(self):
        self._write_and_ingest("facts.txt", "needle evidence")
        broken = RetrievalService(repository=self.repository, embedder=FakeEmbedder(fail=True))
        with self.assertRaises(EmbeddingUnavailableError):
            broken.retrieve("needle", workspace_id="workspace-a")
        self.assertEqual(self.retriever.retrieve("absent", workspace_id="workspace-a").status, "ok")

    def test_stale_source_version_and_offset_mismatch_fail_closed(self):
        result = self._write_and_ingest("facts.txt", "needle citation source text.")
        response = self.retriever.retrieve("needle", workspace_id="workspace-a")
        evidence = response.results[0]
        indexed = self.repository.get_active("workspace-a", result.document_id)
        stale = evidence.citation.model_copy(update={"document_version_id": "stale"})
        with self.assertRaisesRegex(CitationValidationError, "identity"):
            validate_citation(stale, indexed.document.pages, indexed.chunks[0])
        wrong = evidence.citation.model_copy(update={"start_char": evidence.citation.start_char + 1})
        with self.assertRaisesRegex(CitationValidationError, "offsets"):
            validate_citation(wrong, indexed.document.pages, indexed.chunks[0])

    def test_unreliable_extractor_spans_remain_unavailable_in_citations(self):
        from nexus_ai.documents.types import ExtractionResult, ExtractedPage
        class UnlocatedExtractor:
            name = "unlocated"
            version = "1"
            def extract(self, content, *, source_path):
                return ExtractionResult(self.name, self.version, "text/plain",
                                        (ExtractedPage(None, "needle source without reliable offsets"),),
                                        offsets_reliable=False)
        (self.root / "opaque.txt").write_text("ignored by extractor", encoding="utf-8")
        service = DocumentIngestionService(
            approved_root=self.root, repository=self.repository, embedder=self.embedder,
            extractors={".txt": UnlocatedExtractor()},
            limits=DocumentIngestionLimits(window_chars=20, window_overlap_chars=4),
        )
        result = service.ingest("workspace-a", "opaque.txt")
        response = self.retriever.retrieve("needle", workspace_id="workspace-a",
                                           filters=RetrievalFilters(document_id=result.document_id))
        citation = response.results[0].citation
        self.assertFalse(citation.offsets_reliable)
        self.assertIsNone(citation.start_char)
        self.assertIsNone(citation.end_char)
        self.assertIsNone(citation.matched_window_start_char)
        self.assertIsNone(citation.matched_window_end_char)

    def test_copy_on_write_repository_is_safe_for_concurrent_readers(self):
        versions = {f"needle source version {number}." for number in range(21)}
        self._write_and_ingest("stable.txt", "needle source version 0.")
        path = self.root / "stable.txt"
        start = threading.Barrier(8)
        def read_snapshots(_):
            observed = []
            start.wait(timeout=5)
            for _ in range(30):
                response = self.retriever.retrieve("needle", workspace_id="workspace-a", strategy="bm25_raw")
                observed.append(response.results[0].citation.exact_text)
            return observed

        def replace_versions():
            start.wait(timeout=5)
            for number in range(1, 21):
                staging = self.root / f"staging-{number}.txt"
                staging.write_text(f"needle source version {number}.", encoding="utf-8")
                staging.replace(path)
                self.ingestion.ingest("workspace-a", "stable.txt")

        with ThreadPoolExecutor(max_workers=8) as pool:
            reader_futures = [pool.submit(read_snapshots, idx) for idx in range(7)]
            writer_future = pool.submit(replace_versions)
            observed = [text for future in reader_futures for text in future.result()]
            writer_future.result()
        self.assertTrue(observed)
        self.assertTrue(set(observed) <= versions)
        after = self.retriever.retrieve("needle", workspace_id="workspace-a", strategy="bm25_raw")
        self.assertEqual(after.results[0].citation.exact_text, "needle source version 20.")

    def test_index_generation_changes_for_model_window_and_chunker_config(self):
        path = self.root / "identity.txt"
        path.write_text("needle source with enough content for multiple windows and chunks. " * 3,
                        encoding="utf-8")
        first = self.ingestion.ingest("workspace-a", "identity.txt")
        first_index = self.repository.get_active("workspace-a", first.document_id)

        changed_provider = FakeEmbedder()
        changed_provider.revision = "fedcba9876543210fedcba9876543210fedcba98"
        model_service = DocumentIngestionService(
            approved_root=self.root, repository=self.repository, embedder=changed_provider,
            chunker=self.ingestion.chunker,
            limits=DocumentIngestionLimits(window_chars=18, window_overlap_chars=4),
        )
        model_result = model_service.ingest("workspace-a", "identity.txt")
        model_index = self.repository.get_active("workspace-a", model_result.document_id)
        self.assertEqual(model_result.version_id, first.version_id)
        self.assertNotEqual(model_index.index_generation_id, first_index.index_generation_id)
        with self.assertRaises(IndexGenerationMismatchError):
            self.retriever.retrieve("needle", workspace_id="workspace-a")
        changed_retriever = RetrievalService(repository=self.repository, embedder=changed_provider)
        self.assertEqual(changed_retriever.retrieve("needle", workspace_id="workspace-a").status, "ok")

        window_service = DocumentIngestionService(
            approved_root=self.root, repository=self.repository, embedder=changed_provider,
            chunker=self.ingestion.chunker,
            limits=DocumentIngestionLimits(window_chars=22, window_overlap_chars=5),
        )
        window_result = window_service.ingest("workspace-a", "identity.txt")
        window_index = self.repository.get_active("workspace-a", window_result.document_id)
        self.assertEqual(window_result.version_id, first.version_id)
        self.assertNotEqual(window_index.index_generation_id, model_index.index_generation_id)

        chunker = SourceAwareChunker(ChunkingConfig(max_chars=32, overlap_chars=6))
        chunker_service = DocumentIngestionService(
            approved_root=self.root, repository=self.repository, embedder=changed_provider,
            chunker=chunker,
            limits=DocumentIngestionLimits(window_chars=22, window_overlap_chars=5),
        )
        chunker_result = chunker_service.ingest("workspace-a", "identity.txt")
        chunker_index = self.repository.get_active("workspace-a", chunker_result.document_id)
        self.assertEqual(chunker_result.version_id, first.version_id)
        self.assertNotEqual(chunker_index.index_generation_id, window_index.index_generation_id)
        self.assertNotEqual(
            {chunk.chunk_id for chunk in chunker_index.chunks},
            {chunk.chunk_id for chunk in window_index.chunks},
        )

        from nexus_ai.documents.types import ExtractedPage, ExtractionResult
        class ChangedExtractor:
            name = "utf8-text"
            version = "extractor-v2"
            def extract(self, content, *, source_path):
                text = content.decode("utf-8-sig", errors="strict")
                return ExtractionResult(
                    self.name, self.version, "text/plain",
                    (ExtractedPage(None, text),), offsets_reliable=True,
                )
        extraction_service = DocumentIngestionService(
            approved_root=self.root, repository=self.repository, embedder=changed_provider,
            chunker=chunker,
            extractors={".txt": ChangedExtractor()},
            limits=DocumentIngestionLimits(window_chars=22, window_overlap_chars=5),
        )
        extraction_result = extraction_service.ingest("workspace-a", "identity.txt")
        extraction_index = self.repository.get_active("workspace-a", extraction_result.document_id)
        self.assertEqual(extraction_result.version_id, first.version_id)
        self.assertNotEqual(extraction_index.document.processing_id, chunker_index.document.processing_id)
        self.assertNotEqual(extraction_index.index_generation_id, chunker_index.index_generation_id)

    def test_preflight_vector_coordinate_budget_avoids_embedding(self):
        path = self.root / "bounded.txt"
        path.write_text("needle content that creates more than one window", encoding="utf-8")
        bounded = FakeEmbedder()
        service = DocumentIngestionService(
            approved_root=self.root, repository=self.repository, embedder=bounded,
            limits=DocumentIngestionLimits(window_chars=8, window_overlap_chars=2,
                                           max_vector_coordinates=2),
        )
        with self.assertRaisesRegex(ValueError, "before embedding"):
            service.ingest("workspace-a", "bounded.txt")
        self.assertEqual(bounded.calls, [])

    def test_dense_retrieval_consumes_streaming_repository_without_list_materialization(self):
        source = self._write_and_ingest("stream.md", "needle evidence in a streamed source.")
        rows = self.repository.list_active("workspace-a")

        class StreamingRepository:
            def iter_active(self, workspace_id, filters=None):
                for row in rows:
                    yield row
            def list_active(self, workspace_id, filters=None):
                raise AssertionError("dense retrieval must use iter_active")

        streaming = RetrievalService(repository=StreamingRepository(), embedder=self.embedder)
        response = streaming.retrieve("needle", workspace_id="workspace-a")
        self.assertEqual(response.status, "ok")
        self.assertEqual(response.results[0].citation.document_id, source.document_id)
