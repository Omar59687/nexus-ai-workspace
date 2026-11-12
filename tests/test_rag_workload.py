import copy
import unittest

from experiments.rag_prototype.evaluation import validate_fixture
from experiments.rag_prototype.workload import (
    apply_synthetic_updates,
    build_workload_fixture,
    citation_fidelity_diagnostics,
    render_workload_summary,
    run_workload,
)


class SyntheticWorkloadTests(unittest.TestCase):
    def test_fixture_is_reproducible_dev_only_and_covers_directions_and_scenarios(self):
        fixture = build_workload_fixture(
            document_count=12, chunks_per_document=3, question_count=20, seed=31
        )
        self.assertEqual(fixture, build_workload_fixture(
            document_count=12, chunks_per_document=3, question_count=20, seed=31
        ))
        checked = validate_fixture(fixture)
        self.assertEqual({row["split"] for row in checked["documents"]}, {"dev"})
        directions = {
            f"{row['query_language']}->{row['evidence_language']}"
            for row in checked["queries"] if row["answerable"]
        }
        self.assertEqual(directions, {"ar->ar", "en->en", "ar->en", "en->ar"})
        self.assertTrue(any(row["scenario"] == "no_answer" for row in checked["queries"]))
        self.assertTrue(any(row["scenario"] == "multi_document" for row in checked["queries"]))
        self.assertTrue(all(row["synthetic"] for row in [fixture]))
        self.assertIn("not semantic evidence", fixture["workload"]["cross_language_matching"])

    def test_updates_replace_versions_and_remap_every_relevance_judgment(self):
        fixture = build_workload_fixture(document_count=8, chunks_per_document=2,
                                         question_count=12, seed=3)
        updated = apply_synthetic_updates(fixture, update_count=3)
        checked = validate_fixture(updated)
        self.assertEqual(updated["dataset_version"], "1+updates-3")
        for doc_id in {row["document_id"] for row in fixture["documents"][:3]}:
            old = next(row for row in fixture["documents"] if row["document_id"] == doc_id)
            new = next(row for row in updated["documents"] if row["document_id"] == doc_id)
            self.assertNotEqual(old["version_id"], new["version_id"])
            self.assertNotEqual(old["text"], new["text"])
        current_chunk_ids = {row["chunk_id"] for row in checked["chunks"]}
        for query in checked["queries"]:
            self.assertEqual(set(query["judged_chunk_ids"]), current_chunk_ids)
            self.assertEqual(set(query["relevance"]), current_chunk_ids)
        updated_doc_ids = {row["document_id"] for row in fixture["documents"][:3]}
        old_ids = {row["chunk_id"] for row in fixture["chunks"]
                   if row["document_id"] in updated_doc_ids}
        self.assertFalse(current_chunk_ids & old_ids)

    def test_runner_measures_index_query_and_python_memory_and_checks_citations(self):
        report = run_workload(document_count=10, chunks_per_document=2,
                              question_count=12, update_count=2, seed=9, k=3)
        self.assertEqual(report["dataset"]["synthetic"], True)
        self.assertTrue(report["synthetic_workload"]["not_real_corpus_performance"])
        self.assertEqual(report["synthetic_workload"]["simulated_document_updates"], 2)
        self.assertEqual(report["synthetic_workload"]["chunk_count"], 20)
        self.assertIn("indexing", report["performance"])
        self.assertGreater(report["performance"]["resource_observations"]
                           ["peak_traced_python_bytes_from_index_build_start_through_evaluation"], 0)
        self.assertEqual(set(report["strategies"]), {"bm25_raw", "bm25_arabic_normalized"})
        for fidelity in report["citation_fidelity"].values():
            self.assertEqual(fidelity["invalid_count"], 0)
            self.assertEqual(fidelity["checked_ranked_evidence"],
                             fidelity["valid_ranked_evidence"])
        self.assertTrue(any(row["scenario"] == "multi_document"
                            for row in build_workload_fixture(document_count=10,
                                                              chunks_per_document=2,
                                                              question_count=12,
                                                              seed=9)["queries"]))
        self.assertIn("NOT REAL-CORPUS QUALITY EVIDENCE", render_workload_summary(report))

    def test_rankings_and_metrics_repeat_even_though_timings_are_measurements(self):
        kwargs = dict(document_count=8, chunks_per_document=2, question_count=12,
                      update_count=1, seed=4, k=3)
        first = run_workload(**kwargs)
        second = run_workload(**kwargs)
        for strategy in first["strategies"]:
            for key in ("metrics", "query_results", "answerable_coverage", "no_answer"):
                self.assertEqual(first["strategies"][strategy][key], second["strategies"][strategy][key])
            for query_id, result in first["strategies"][strategy]["query_results"].items():
                self.assertEqual(
                    [row["chunk_id"] for row in result["ranked_chunks"]],
                    [row["chunk_id"] for row in second["strategies"][strategy]["query_results"][query_id]["ranked_chunks"]],
                )
        self.assertEqual(first["citation_fidelity"], second["citation_fidelity"])

    def test_citation_integrity_detects_corrupted_source_span(self):
        fixture = build_workload_fixture(document_count=8, chunks_per_document=2,
                                         question_count=12, seed=5)
        report = run_workload(document_count=8, chunks_per_document=2,
                              question_count=12, seed=5)
        corrupted = copy.deepcopy(report)
        strategy = next(iter(corrupted["strategies"]))
        query = next(iter(corrupted["strategies"][strategy]["query_results"].values()))
        query["ranked_chunks"][0]["start_char"] += 1
        fidelity = citation_fidelity_diagnostics(fixture, corrupted)
        self.assertEqual(fidelity[strategy]["invalid_count"], 1)
        query["ranked_chunks"][0]["start_char"] = "malformed"
        fidelity = citation_fidelity_diagnostics(fixture, corrupted)
        self.assertEqual(fidelity[strategy]["invalid_count"], 1)

    def test_invalid_workload_sizes_and_update_counts_are_rejected(self):
        for kwargs in (
            {"document_count": 3},
            {"document_count": 151},
            {"chunks_per_document": 21},
            {"question_count": 7},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                build_workload_fixture(**kwargs)
        fixture = build_workload_fixture(document_count=4, question_count=8)
        with self.assertRaisesRegex(ValueError, "cannot exceed"):
            apply_synthetic_updates(fixture, update_count=5)


if __name__ == "__main__":
    unittest.main()
