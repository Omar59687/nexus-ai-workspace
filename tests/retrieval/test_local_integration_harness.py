import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.run_local_rag_integration import (
    FIXTURE_DOCUMENTS,
    QUERY_CASES,
    _case_result,
    _write_fixture_corpus,
    main,
)


class FakeRetrieval:
    def __init__(self):
        self.calls = []

    def retrieve(self, query, *, workspace_id, top_k, filters=None):
        self.calls.append((query, workspace_id, top_k, filters))
        citation = SimpleNamespace(
            document_id="doc-fixture",
            document_version_id="version-fixture",
            source_path="en_revenue.txt",
            chunk_id="chunk-fixture",
        )
        row = SimpleNamespace(citation=citation, score=0.9, score_type="cosine_similarity")
        return SimpleNamespace(status="ok", results=(row,))


class FakeAnswerer:
    def __init__(self):
        self.calls = []

    def answer(self, query, evidence, *, language):
        self.calls.append((query, evidence, language))
        return SimpleNamespace(answer="fixture response", abstained=False, citations=evidence)


class LocalIntegrationHarnessTests(unittest.TestCase):
    def test_fixtures_are_written_as_exact_utf8_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_fixture_corpus(root)
            for fixture in FIXTURE_DOCUMENTS:
                path = root / fixture.source_path
                self.assertEqual(path.read_bytes(), fixture.text.encode("utf-8"))
            self.assertIn(b"\n", (root / "en_revenue.txt").read_bytes())
            self.assertIn("بلغت".encode("utf-8"), (root / "ar_revenue.txt").read_bytes())

    def test_direction_cases_cover_all_four_query_evidence_languages(self):
        observed = {(case.direction, case.language, case.evidence_path) for case in QUERY_CASES[:4]}
        self.assertEqual(observed, {
            ("EN→EN", "en", "en_revenue.txt"),
            ("AR→AR", "ar", "ar_revenue.txt"),
            ("AR→EN", "ar", "en_revenue.txt"),
            ("EN→AR", "en", "ar_revenue.txt"),
        })

    def test_case_runner_filters_evidence_then_passes_only_retrieved_citations(self):
        retrieval = FakeRetrieval()
        answerer = FakeAnswerer()
        case = QUERY_CASES[2]
        output = _case_result(
            retrieval, answerer, case, workspace_id="fixture-workspace",
            document_ids={"en_revenue.txt": "en-doc-id"},
        )
        self.assertEqual(retrieval.calls[0][3].document_id, "en-doc-id")
        self.assertEqual(len(answerer.calls[0][1]), 1)
        self.assertEqual(answerer.calls[0][1][0].source_path, "en_revenue.txt")
        self.assertEqual(output["case_id"], "ar_to_en")
        self.assertEqual(output["answer_citations"][0]["source_path"], "en_revenue.txt")

    def test_no_live_provider_load_without_explicit_opt_in(self):
        with patch("sys.stdout") as stdout, patch("sys.stderr") as stderr:
            self.assertEqual(main([]), 2)
            self.assertTrue(stderr.write.called)
            self.assertFalse(stdout.write.called)


if __name__ == "__main__":
    unittest.main()
