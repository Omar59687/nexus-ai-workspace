import copy
import json
import tempfile
import unittest
from pathlib import Path

from experiments.rag_prototype.evaluation import (
    FixtureError,
    load_fixture,
    render_summary,
    run_evaluation,
    serialize_report,
    validate_fixture,
    write_report,
)


FIXTURE = Path(__file__).parents[1] / "benchmarks" / "rag_eval_synthetic_v1.json"


class FixtureValidationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = load_fixture(FIXTURE)

    def test_fixture_has_all_four_bilingual_directions_and_disjoint_splits(self):
        queries = [q for q in self.fixture["queries"] if q["answerable"]]
        directions = {f"{q['query_language']}->{q['evidence_language']}" for q in queries}
        self.assertEqual(directions, {"ar->ar", "en->en", "ar->en", "en->ar"})
        self.assertEqual(len([q for q in queries if q["split"] == "dev"]), 5)
        self.assertEqual(len([q for q in queries if q["split"] == "holdout"]), 4)

    def test_rejects_duplicate_question_ids_and_incomplete_judgments(self):
        duplicate = copy.deepcopy(self.fixture)
        duplicate["queries"].append(duplicate["queries"][0])
        with self.assertRaisesRegex(FixtureError, "question_id"):
            validate_fixture(duplicate)

        incomplete = copy.deepcopy(self.fixture)
        incomplete["queries"][0]["judged_chunk_ids"].pop()
        with self.assertRaisesRegex(FixtureError, "judged_chunk_ids"):
            validate_fixture(incomplete)

    def test_rejects_invalid_foreign_keys_and_boolean_relevance_grades(self):
        bad_fk = copy.deepcopy(self.fixture)
        bad_fk["chunks"][0]["document_id"] = "missing-document"
        with self.assertRaisesRegex(FixtureError, "unknown document"):
            validate_fixture(bad_fk)

        bad_grade = copy.deepcopy(self.fixture)
        bad_grade["queries"][0]["relevance"]["chunk-dev-ar-revenue"] = True
        with self.assertRaisesRegex(FixtureError, "non-negative integer"):
            validate_fixture(bad_grade)

    def test_rejects_chunk_span_past_end_of_source(self):
        out_of_bounds = copy.deepcopy(self.fixture)
        out_of_bounds["chunks"][0]["end_char"] = len(out_of_bounds["documents"][0]["text"]) + 100
        with self.assertRaisesRegex(FixtureError, "source span"):
            validate_fixture(out_of_bounds)

    def test_rejects_cross_split_duplicate_document_content(self):
        duplicated = copy.deepcopy(self.fixture)
        duplicated["documents"][4]["text"] = duplicated["documents"][0]["text"]
        duplicated["chunks"][4]["text"] = duplicated["documents"][0]["text"]
        with self.assertRaisesRegex(FixtureError, "duplicate document content across splits"):
            validate_fixture(duplicated)

    def test_rejects_source_path_reuse_across_document_records(self):
        duplicated = copy.deepcopy(self.fixture)
        duplicated["documents"][4]["source"] = duplicated["documents"][0]["source"]
        duplicated["chunks"][4]["source"] = duplicated["documents"][0]["source"]
        with self.assertRaisesRegex(FixtureError, "duplicate document source"):
            validate_fixture(duplicated)


class EvaluationRunnerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = load_fixture(FIXTURE)

    def test_runner_reports_metrics_by_language_and_direction(self):
        report = run_evaluation(self.fixture, split="dev", k=3)
        self.assertEqual(report["dataset"]["split"], "dev")
        self.assertTrue(report["dataset"]["synthetic"])
        self.assertEqual(report["query_count"], 6)
        self.assertEqual(report["answerable_query_count"], 5)
        self.assertEqual(report["no_answer_query_count"], 1)

        for strategy in report["strategies"].values():
            self.assertEqual(strategy["metrics"]["overall"]["query_count"], 5)
            self.assertEqual(set(strategy["metrics"]["by_direction"]), {"ar->ar", "en->en", "ar->en", "en->ar"})
            self.assertEqual(strategy["no_answer"]["false_positive_queries"], 0)
            self.assertEqual(strategy["no_answer"]["abstained_queries"], 1)
            self.assertEqual(strategy["diagnostics"]["unjudged_retrieved_chunk_count"], 0)
            for result in strategy["query_results"].values():
                for hit in result["ranked_chunks"]:
                    self.assertLessEqual(hit["start_char"], hit["end_char"])

    def test_repeated_run_has_identical_json_and_summary(self):
        first = run_evaluation(self.fixture, split="dev", k=3)
        second = run_evaluation(self.fixture, split="dev", k=3)
        self.assertEqual(serialize_report(first), serialize_report(second))
        self.assertEqual(render_summary(first), render_summary(second))

    def test_normalization_ablation_finds_the_fixture_spelling_variant(self):
        report = run_evaluation(self.fixture, split="dev", k=3)
        raw = report["strategies"]["bm25_raw"]["metrics"]["by_direction"]["ar->ar"]
        normalized = report["strategies"]["bm25_arabic_normalized"]["metrics"]["by_direction"]["ar->ar"]
        self.assertEqual(raw["query_count"], 2)
        self.assertEqual(normalized["query_count"], 2)
        self.assertEqual(raw["recall_at_k"], 0.5)
        self.assertEqual(normalized["recall_at_k"], 1.0)
        self.assertEqual(report["dataset"]["synthetic"], True)

    def test_no_answer_metrics_are_separate_from_answerable_retrieval_metrics(self):
        report = run_evaluation(self.fixture, split="dev", k=3)
        for strategy in report["strategies"].values():
            metrics = strategy["metrics"]["overall"]
            self.assertEqual(metrics["query_count"], 5)
            self.assertNotIn("q-dev-en-unanswerable", strategy["query_results"])
            self.assertEqual(strategy["no_answer"]["query_count"], 1)

    def test_holdout_requires_explicit_opt_in(self):
        with self.assertRaisesRegex(ValueError, "allow_holdout"):
            run_evaluation(self.fixture, split="holdout", k=3)
        report = run_evaluation(self.fixture, split="holdout", k=3, allow_holdout=True)
        self.assertEqual(report["dataset"]["split"], "holdout")

    def test_invalid_strategy_output_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "duplicate chunk IDs"):
            run_evaluation(self.fixture, split="dev", k=3, retrievers={"duplicate": lambda _q, _k: ["chunk-dev-ar-revenue"] * 2})
        with self.assertRaisesRegex(ValueError, "unknown chunk ID"):
            run_evaluation(self.fixture, split="dev", k=3, retrievers={"unknown": lambda _q, _k: ["not-in-corpus"]})

    def test_json_writer_refuses_overwrite_by_default(self):
        report = run_evaluation(self.fixture, split="dev", k=3)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            write_report(report, path)
            expected = serialize_report(report)
            self.assertEqual(path.read_text(encoding="utf-8"), expected)
            with self.assertRaises(FileExistsError):
                write_report(report, path)
            write_report(report, path, overwrite=True)
            self.assertEqual(path.read_text(encoding="utf-8"), expected)


if __name__ == "__main__":
    unittest.main()
