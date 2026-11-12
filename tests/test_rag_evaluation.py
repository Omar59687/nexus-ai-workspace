import copy
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import experiments.rag_prototype.evaluation as evaluation_module

from experiments.rag_prototype.evaluation import (
    FixtureError,
    RetrieverSpec,
    load_fixture,
    render_summary,
    run_evaluation,
    serialize_report,
    validate_fixture,
    write_report,
)
from experiments.rag_prototype import ChunkHit


FIXTURE = Path(__file__).parents[1] / "benchmarks" / "rag_eval_synthetic_dev_v2.json"
HOLDOUT_FIXTURE = Path(__file__).parents[1] / "benchmarks" / "rag_eval_synthetic_holdout_v2.json"


class FixtureValidationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = load_fixture(FIXTURE)

    def test_split_fixtures_have_independent_direction_coverage_and_no_shared_docs(self):
        expected = {"ar->ar", "en->en", "ar->en", "en->ar"}
        holdout = load_fixture(HOLDOUT_FIXTURE)
        for fixture, split in ((self.fixture, "dev"), (holdout, "holdout")):
            self.assertEqual({row["split"] for row in fixture["documents"]}, {split})
            directions = {
                f"{q['query_language']}->{q['evidence_language']}"
                for q in fixture["queries"] if q["answerable"]
            }
            self.assertEqual(directions, expected)
        self.assertFalse({d["document_id"] for d in self.fixture["documents"]} & {d["document_id"] for d in holdout["documents"]})
        self.assertFalse({d["source"] for d in self.fixture["documents"]} & {d["source"] for d in holdout["documents"]})
        self.assertFalse({d["text"] for d in self.fixture["documents"]} & {d["text"] for d in holdout["documents"]})

    def test_rejects_duplicate_question_ids_and_incomplete_judgments(self):
        duplicate = copy.deepcopy(self.fixture)
        duplicate["queries"].append(duplicate["queries"][0])
        with self.assertRaisesRegex(FixtureError, "question_id"):
            validate_fixture(duplicate)

        incomplete = copy.deepcopy(self.fixture)
        incomplete["queries"][0]["judged_chunk_ids"].pop()
        with self.assertRaisesRegex(FixtureError, "judged_chunk_ids"):
            validate_fixture(incomplete)

    def test_each_split_must_cover_all_four_directions(self):
        missing = copy.deepcopy(self.fixture)
        missing["queries"] = [q for q in missing["queries"] if q["question_id"] != "q-dev-en-ar-branches"]
        with self.assertRaisesRegex(FixtureError, "dev split lacks bilingual directions"):
            validate_fixture(missing)

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

    def test_loader_rejects_duplicate_json_keys_and_oversized_fixtures(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"bad.json"
            path.write_text('{"dataset_id":"one","dataset_id":"two"}',encoding="utf-8")
            with self.assertRaisesRegex(FixtureError,"duplicate JSON object key"):
                load_fixture(path)
            with patch("experiments.rag_prototype.evaluation.MAX_FIXTURE_BYTES",2):
                with self.assertRaisesRegex(FixtureError,"MAX_FIXTURE_BYTES"):
                    load_fixture(FIXTURE)

    def test_rejects_cross_split_duplicate_document_content(self):
        duplicated = copy.deepcopy(self.fixture)
        holdout = load_fixture(HOLDOUT_FIXTURE)
        duplicated["documents"].extend(copy.deepcopy(holdout["documents"]))
        duplicated["chunks"].extend(copy.deepcopy(holdout["chunks"]))
        duplicated["queries"].extend(copy.deepcopy(holdout["queries"]))
        duplicated["documents"][-1]["text"] = duplicated["documents"][0]["text"]
        duplicated["chunks"][-1]["text"] = duplicated["documents"][0]["text"]
        with self.assertRaisesRegex(FixtureError, "duplicate document content across splits"):
            validate_fixture(duplicated)

    def test_rejects_source_path_reuse_across_document_records(self):
        duplicated = copy.deepcopy(self.fixture)
        duplicated = copy.deepcopy(self.fixture)
        holdout = load_fixture(HOLDOUT_FIXTURE)
        duplicated["documents"].extend(copy.deepcopy(holdout["documents"]))
        duplicated["chunks"].extend(copy.deepcopy(holdout["chunks"]))
        duplicated["queries"].extend(copy.deepcopy(holdout["queries"]))
        duplicated["documents"][-1]["source"] = duplicated["documents"][0]["source"]
        duplicated["chunks"][-1]["source"] = duplicated["documents"][0]["source"]
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
                    self.assertTrue(hit["document_version_id"])
                    self.assertTrue(hit["document_sha256"])

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
            run_evaluation(load_fixture(HOLDOUT_FIXTURE), split="holdout", k=3)
        report = run_evaluation(load_fixture(HOLDOUT_FIXTURE), split="holdout", k=3, allow_holdout=True)
        self.assertEqual(report["dataset"]["split"], "holdout")
        with self.assertRaisesRegex(FixtureError, "holdout-only"):
            run_evaluation(self.fixture, split="holdout", k=3, allow_holdout=True)

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

    def test_report_writer_path_based_fallback_uses_requested_destination(self):
        report = run_evaluation(self.fixture, split="dev", k=3)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "nested"
            nested.mkdir()
            destination = nested / "report.json"
            previous_cwd = Path.cwd()
            try:
                os.chdir(root)
                with patch("experiments.rag_prototype.evaluation._supports_dir_fd", return_value=False):
                    written = write_report(report, destination)
                    self.assertEqual(written, destination)
                    self.assertEqual(destination.read_text(encoding="utf-8"), serialize_report(report))
                    self.assertFalse((root / "report.json").exists())
                    with self.assertRaises(FileExistsError):
                        write_report(report, destination)
            finally:
                os.chdir(previous_cwd)

    def test_custom_retriever_metadata_is_not_mislabeled_as_bm25(self):
        report = run_evaluation(
            self.fixture,
            retrievers={"custom": lambda _q, _k: ["chunk-dev-ar-revenue"]},
        )
        self.assertEqual(
            report["strategies"]["custom"]["diagnostics"]["ordering_policy"],
            "caller-supplied order; tie behavior unspecified",
        )
        configured = run_evaluation(
            self.fixture,
            retrievers={"declared": RetrieverSpec(lambda _q, _k: [], "score desc, ID asc", 0.1)},
        )
        self.assertEqual(configured["strategies"]["declared"]["diagnostics"]["ordering_policy"], "score desc, ID asc")

    def test_report_writer_rejects_traversal_and_symlink_targets(self):
        report = run_evaluation(self.fixture)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "relative to output_root"):
                write_report(report, "../outside.json", output_root=root)
            target = root / "real.json"
            target.write_text("keep", encoding="utf-8")
            link = root / "link.json"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are unavailable")
            with self.assertRaisesRegex(ValueError, "symlink"):
                write_report(report, link, overwrite=True)
            self.assertEqual(target.read_text(encoding="utf-8"), "keep")

    def test_report_path_rejects_reparse_point_parent(self):
        report = run_evaluation(self.fixture)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = root / "parent"
            parent.mkdir()
            destination = parent / "report.json"
            original = evaluation_module._is_reparse_path
            with patch.object(
                evaluation_module,
                "_is_reparse_path",
                side_effect=lambda path: path == parent or original(path),
            ):
                with self.assertRaisesRegex(ValueError, "reparse point"):
                    write_report(report, destination)
            self.assertFalse(destination.exists())

    @unittest.skipUnless(os.name == "nt", "Windows junction coverage")
    def test_report_writer_rejects_windows_junction_parent(self):
        report = run_evaluation(self.fixture)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / "real"
            real.mkdir()
            junction = root / "junction"
            result = subprocess.run(
                ["cmd.exe", "/c", "mklink", "/J", str(junction), str(real)],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                self.skipTest(f"Could not create a Windows junction: {result.stderr or result.stdout}")
            try:
                with self.assertRaisesRegex(ValueError, "reparse point"):
                    write_report(report, junction / "report.json")
                self.assertFalse((real / "report.json").exists())
            finally:
                junction.rmdir()

    def test_no_answer_false_positive_and_answerable_coverage_are_separate(self):
        report = run_evaluation(
            self.fixture,
            retrievers={"always": lambda _q, _k: ["chunk-dev-ar-revenue"]},
        )
        strategy = report["strategies"]["always"]
        self.assertEqual(strategy["no_answer"]["false_positive_queries"], 1)
        self.assertEqual(strategy["no_answer"]["abstained_queries"], 0)
        self.assertEqual(strategy["answerable_coverage"]["retrieved_relevant_at_k"], 2)

    def test_latency_is_opt_in_and_separate_from_deterministic_metrics(self):
        standard = run_evaluation(self.fixture)
        self.assertNotIn("performance", standard)
        measured = run_evaluation(self.fixture, measure_latency=True)
        self.assertTrue(measured["performance"]["measured"])
        self.assertIn("platform", measured["performance"]["system"])
        self.assertIn("mean_query_latency_ms", measured["performance"]["by_strategy"]["bm25_raw"])

    def test_declared_score_ties_are_sorted_by_chunk_id(self):
        from experiments.rag_prototype.evaluation import _chunks
        chunks=_chunks(self.fixture,"dev")
        reverse=tuple(reversed(chunks))
        spec=RetrieverSpec(
            lambda _query,_k: tuple(ChunkHit(chunk,1.0) for chunk in reverse),
            "score descending, chunk ID ascending",
        )
        report=run_evaluation(self.fixture,retrievers={"tied":spec},k=4)
        first=next(iter(report["strategies"]["tied"]["query_results"].values()))
        ids=[row["chunk_id"] for row in first["ranked_chunks"]]
        self.assertEqual(ids,sorted(ids))

    def test_undeclared_custom_order_is_preserved_and_reported_honestly(self):
        from experiments.rag_prototype.evaluation import _chunks
        chunks=tuple(reversed(_chunks(self.fixture,"dev")))
        spec=RetrieverSpec(lambda _query,_k: tuple(ChunkHit(chunk,1.0) for chunk in chunks),"model-defined order")
        report=run_evaluation(self.fixture,retrievers={"custom":spec},k=4)
        row=next(iter(report["strategies"]["custom"]["query_results"].values()))
        self.assertEqual([hit["chunk_id"] for hit in row["ranked_chunks"]],[chunk.chunk_id for chunk in chunks])
        self.assertEqual(report["strategies"]["custom"]["diagnostics"]["ordering_policy"],"model-defined order")

    def test_ranked_result_provenance_includes_source_version_and_content_hashes(self):
        fixture=copy.deepcopy(self.fixture)
        fixture["documents"][0]["source_ref"]="corpus://annual-report/2025"
        report=run_evaluation(fixture,k=4)
        result=next(iter(report["strategies"]["bm25_raw"]["query_results"].values()))
        item=next(row for row in result["ranked_chunks"] if row["document_id"]==fixture["documents"][0]["document_id"])
        self.assertEqual(item["source_ref"],"corpus://annual-report/2025")
        self.assertEqual(len(item["document_version_id"]),2)
        self.assertEqual(len(item["document_sha256"]),64)
        self.assertEqual(len(item["chunk_sha256"]),64)
        self.assertLess(item["start_char"],item["end_char"])

    def test_all_no_answer_false_positives_are_retained_as_query_diagnostics(self):
        report=run_evaluation(self.fixture,retrievers={"always-return":lambda _query,_k:["chunk-dev-en-revenue"]})
        no_answer=report["strategies"]["always-return"]["no_answer"]
        self.assertEqual(no_answer["false_positive_queries"],1)
        self.assertEqual(no_answer["results"]["q-dev-en-unanswerable"]["false_positive"],True)
        self.assertEqual(no_answer["results"]["q-dev-en-unanswerable"]["abstained"],False)


if __name__ == "__main__":
    unittest.main()
