import copy
import unittest
from pathlib import Path

from experiments.rag_prototype.evaluation import FixtureError
from experiments.rag_prototype.provisional_evaluation import (
    load_provisional_fixture,
    run_provisional_evaluation,
)


ROOT=Path(__file__).parents[1]
DEV=ROOT/"benchmarks"/"rag_eval_synthetic_dev_v2.json"
HOLDOUT=ROOT/"benchmarks"/"rag_eval_synthetic_holdout_v2.json"


class ProvisionalEvaluationTests(unittest.TestCase):
    def test_loads_only_the_labeled_synthetic_dev_fixture(self):
        fixture=load_provisional_fixture(DEV)
        self.assertTrue(fixture["synthetic"])
        self.assertEqual({row["split"] for row in fixture["documents"]},{"dev"})

    def test_holdout_fixture_is_rejected_before_evaluation(self):
        with self.assertRaisesRegex(FixtureError,"holdout is protected"):
            run_provisional_evaluation(HOLDOUT)

    def test_mixed_dev_and_holdout_documents_are_rejected(self):
        from experiments.rag_prototype.evaluation import load_fixture
        fixture=copy.deepcopy(load_fixture(DEV))
        fixture["documents"].append({**fixture["documents"][0],"document_id":"holdout-doc","split":"holdout"})
        with self.assertRaisesRegex(FixtureError,"dev-only"):
            run_provisional_evaluation(fixture)

    def test_non_synthetic_fixture_is_not_called_provisional(self):
        from experiments.rag_prototype.evaluation import load_fixture
        fixture=copy.deepcopy(load_fixture(DEV))
        fixture["synthetic"]=False
        with self.assertRaisesRegex(FixtureError,"synthetic fixture"):
            run_provisional_evaluation(fixture)

    def test_report_labels_stage_and_reports_all_four_directions(self):
        report=run_provisional_evaluation(DEV,k=2)
        self.assertEqual(report["evaluation_stage"],"provisional-development")
        self.assertIn("not evidence",report["interpretation"])
        self.assertEqual(report["dataset"]["split"],"dev")
        self.assertEqual(set(report["strategies"]["bm25_raw"]["metrics"]["by_direction"]),
                         {"ar->ar","en->en","ar->en","en->ar"})

    def test_invalid_k_is_rejected_by_the_standard_runner(self):
        with self.assertRaisesRegex(ValueError,"k must be a positive"):
            run_provisional_evaluation(DEV,k=0)


if __name__ == "__main__":
    unittest.main()
