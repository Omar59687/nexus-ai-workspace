"""Deterministic PDF-to-RAG contract tests; no live model runtime is used."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from nexus_ai.retrieval.answering import AnswerModelOutput, AnswerOutputRejectedError, GroundedAnswerService
from nexus_ai.documents.service import DocumentIngestionService
from nexus_ai.retrieval.service import RetrievalConfig, RetrievalService
from scripts.run_pdf_rag_e2e import (
    PDF_FIXTURES,
    PDF_QUERY_CASES,
    WORKSPACE_ID,
    _citation_maps_to_extracted_pdf,
    _run_case,
    ingest_fixture_pdfs,
    main,
    write_pdf_fixtures,
)


class FakeMultilingualEncoder:
    model_id = "fixture/multilingual"
    revision = "0123456789abcdef0123456789abcdef01234567"
    preprocessing_id = "fixture-multilingual-v1"
    embedding_dimensions = 3

    def embed(self, texts, *, input_type):
        rows = []
        for text in texts:
            lowered = text.casefold()
            if input_type == "query" and ("employee" in lowered or "headcount" in lowered):
                rows.append((0.7, 0.7, 0.0))
            elif "revenue" in lowered or "إيرادات" in lowered:
                # Identical semantic vector for both languages exercises the
                # cross-language retrieval contract without claiming quality.
                rows.append((1.0, 0.0, 0.0))
            elif "employed" in lowered or "people" in lowered:
                rows.append((0.7, 0.7, 0.0))
            else:
                rows.append((0.0, 0.0, 1.0))
        return tuple(rows)


class FakeAnswerAdapter:
    def __init__(self, *, answer="42,000,000 dollars", fake_id=False, abstain=False):
        self.answer = answer
        self.fake_id = fake_id
        self.abstain = abstain
        self.calls = []

    def generate_structured(self, prompt, model_class, *, model=None):
        self.calls.append((prompt, model_class, model))
        rows = json.loads(prompt.split("UNTRUSTED_EVIDENCE_JSON=", 1)[1])
        ids = [row["citation_id"] for row in rows]
        if self.fake_id:
            ids = ["made_up_evidence_id"]
        return SimpleNamespace(result=AnswerModelOutput(
            answer=self.answer,
            citation_ids=[] if self.abstain else ids,
            abstain=self.abstain,
        ))


class PdfRagE2EContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nexus-pdf-e2e-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        write_pdf_fixtures(self.root)
        self.repository, self.indexed = ingest_fixture_pdfs(self.root, FakeMultilingualEncoder())
        self.retrieval = RetrievalService(
            repository=self.repository,
            embedder=FakeMultilingualEncoder(),
            config=RetrievalConfig(max_top_k=20),
        )

    def test_generated_english_arabic_pdfs_are_extracted_with_pages_and_provenance(self):
        self.assertEqual(set(self.indexed), {fixture.source_path for fixture in PDF_FIXTURES})
        for fixture in PDF_FIXTURES:
            indexed = self.indexed[fixture.source_path]
            self.assertEqual(tuple(page.text for page in indexed.document.pages), fixture.pages)
            self.assertEqual(
                tuple(page.page_number for page in indexed.document.pages),
                tuple(range(1, len(fixture.pages) + 1)),
            )
            self.assertEqual(indexed.document.source_path, fixture.source_path)
            self.assertEqual(indexed.document.media_type, "application/pdf")
            self.assertEqual(indexed.document.version_id,
                             indexed.chunks[0].version_id)
            self.assertEqual(indexed.document.content_sha256,
                             hashlib.sha256((self.root / fixture.source_path).read_bytes()).hexdigest())
            for chunk in indexed.chunks:
                page = indexed.document.pages[chunk.page_number - 1]
                self.assertEqual(page.text[chunk.start_char:chunk.end_char], chunk.text)
        self.assertIn("إيرادات", self.indexed["arabic_revenue.pdf"].document.pages[0].text)

    def test_cross_language_and_multi_document_cases_return_traceable_pdf_evidence(self):
        for case_id in ("en_to_en", "ar_to_ar", "ar_to_en", "en_to_ar", "multi_document"):
            case = next(case for case in PDF_QUERY_CASES if case.case_id == case_id)
            output = _run_case(self.retrieval, _answerer(FakeAnswerAdapter()), case, self.indexed)
            self.assertTrue(output["expected_evidence_retrieved"], output)
            self.assertTrue(output["retrieval_citations_integrity"], output)
            for evidence in output["retrieved_evidence"]:
                self.assertIn(evidence["source_path"], self.indexed)
                self.assertTrue(_citation_maps_to_extracted_pdf(
                    _citation_from_output(evidence, workspace_id=WORKSPACE_ID), self.indexed,
                ))
        multi = next(case for case in PDF_QUERY_CASES if case.case_id == "multi_document")
        output = _run_case(self.retrieval, _answerer(FakeAnswerAdapter()), multi, self.indexed)
        self.assertTrue({"english_revenue.pdf", "english_headcount.pdf"} <= {
            row["source_path"] for row in output["retrieved_evidence"]
        })
        evidence = tuple(row.citation for row in self.retrieval.retrieve(
            multi.query, workspace_id=WORKSPACE_ID, top_k=3
        ).results if row.citation.source_path in {"english_revenue.pdf", "english_headcount.pdf"})
        multi_adapter = FakeAnswerAdapter(answer="Revenue was 42 million dollars and headcount was 1,200 people.")
        multi_answer = _answerer(multi_adapter).answer(multi.query, evidence, language="en")
        self.assertEqual({citation.source_path for citation in multi_answer.citations},
                         {"english_revenue.pdf", "english_headcount.pdf"})

    def test_retrieval_is_repeatable_for_identical_fixture_inputs(self):
        first = self.retrieval.retrieve("كم بلغت إيرادات Northstar؟", workspace_id=WORKSPACE_ID, top_k=3)
        second = self.retrieval.retrieve("كم بلغت إيرادات Northstar؟", workspace_id=WORKSPACE_ID, top_k=3)
        self.assertEqual(
            [(row.citation.document_id, row.citation.document_version_id, row.citation.chunk_id)
             for row in first.results],
            [(row.citation.document_id, row.citation.document_version_id, row.citation.chunk_id)
             for row in second.results],
        )

    def test_reingestion_of_generated_pdf_is_idempotent_and_version_stable(self):
        active = self.indexed["english_revenue.pdf"]
        service = DocumentIngestionService(
            approved_root=self.root,
            repository=self.repository,
            embedder=FakeMultilingualEncoder(),
            limits=_fixture_limits(),
        )
        replay = service.ingest(WORKSPACE_ID, "english_revenue.pdf")
        self.assertEqual(replay.document_id, active.document.document_id)
        self.assertEqual(replay.version_id, active.document.version_id)
        self.assertFalse(replay.activated)
        self.assertTrue(replay.idempotent)

    def test_live_model_path_requires_explicit_opt_in(self):
        errors = StringIO()
        with redirect_stderr(errors):
            self.assertEqual(main([]), 2)
        self.assertIn("explicit_live_opt_in_required", errors.getvalue())

    def test_empty_evidence_abstains_without_generation_and_no_answer_control_is_empty(self):
        adapter = FakeAnswerAdapter()
        answerer = _answerer(adapter)
        case = next(case for case in PDF_QUERY_CASES if case.case_id == "no_answer")
        output = _run_case(self.retrieval, answerer, case, self.indexed)
        self.assertEqual(output["retrieval_status"], "empty")
        self.assertEqual(output["execution_status"], "PASS")
        self.assertTrue(output["abstained"])
        self.assertEqual(adapter.calls, [])

    def test_supported_numeric_answer_and_fabricated_citation_rejection(self):
        revenue = next(row for row in self.retrieval.retrieve(
            "Northstar revenue", workspace_id=WORKSPACE_ID, top_k=3
        ).results if row.citation.source_path == "english_revenue.pdf")
        valid_adapter = FakeAnswerAdapter()
        valid = _answerer(valid_adapter).answer("What was the revenue?", (revenue.citation,), language="en")
        self.assertEqual(valid.answer, "42,000,000 dollars")
        self.assertEqual(valid.citations, (revenue.citation,))

        bad_adapter = FakeAnswerAdapter(fake_id=True)
        with self.assertRaises(AnswerOutputRejectedError) as raised:
            _answerer(bad_adapter).answer("What was the revenue?", (revenue.citation,), language="en")
        self.assertEqual(raised.exception.reason_code, "fabricated_citation_id")


def _answerer(adapter):
    return GroundedAnswerService(adapter=adapter, default_model="fixture-model")


def _fixture_limits():
    from nexus_ai.documents.service import DocumentIngestionLimits

    return DocumentIngestionLimits(
        max_file_bytes=2 * 1024 * 1024,
        max_total_extracted_chars=100_000,
        max_pdf_page_chars=50_000,
        max_pdf_pages=10,
        max_chunks=100,
        max_windows=100,
        window_chars=500,
        window_overlap_chars=50,
        embedding_batch_size=8,
        max_vector_coordinates=100_000,
        pdf_timeout_seconds=30,
        pdf_memory_limit_bytes=512 * 1024 * 1024,
        pdf_cpu_limit_seconds=30,
    )


def _citation_from_output(row, *, workspace_id):
    from nexus_ai.retrieval.schemas import EvidenceCitation

    return EvidenceCitation(
        workspace_id=workspace_id,
        document_id=row["document_id"],
        document_version_id=row["document_version_id"],
        source_path=row["source_path"],
        source_sha256=row["source_sha256"],
        page_number=row["page_number"],
        chunk_id=row["chunk_id"],
        start_char=row["start_char"],
        end_char=row["end_char"],
        matched_window_id=None,
        matched_window_start_char=None,
        matched_window_end_char=None,
        offsets_reliable=True,
        exact_text=row["text"],
    )


if __name__ == "__main__":
    unittest.main()
