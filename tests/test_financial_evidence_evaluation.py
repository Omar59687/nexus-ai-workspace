from __future__ import annotations

import copy
import json
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from nexus_ai.benchmark import financial_evidence as evaluation


FIXTURE = Path(__file__).parents[1] / "benchmarks" / "financial_evidence_synthetic_v1.json"


class FinancialEvidenceEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = evaluation.load_financial_fixture(FIXTURE)

    def test_synthetic_financial_cases_run_through_collection_index_and_lexical_path(self):
        report = evaluation.run_financial_evaluation(self.fixture)
        self.assertTrue(report["dataset"]["synthetic"])
        self.assertEqual(report["execution"]["index_status"], "PASS")
        self.assertEqual(report["execution"]["retriever"], "CollectionLexicalRetriever")
        self.assertEqual((report["execution"]["model_calls"], report["execution"]["embedding_calls"],
                          report["execution"]["database_connections"]), (0, 0, 0))
        self.assertEqual(report["metrics"]["recall_at_5"]["value"], 1.0)
        self.assertEqual(report["metrics"]["recall_at_10"]["value"], 1.0)
        provenance = report["metrics"]["citation_provenance_integrity"]
        self.assertEqual(provenance["valid"], provenance["total"])
        self.assertEqual(provenance["rate"], 1.0)
        self.assertEqual(report["metrics"]["company_year_leakage"]["count"], 0)
        missing = report["metrics"]["missing_evidence"]
        self.assertEqual(missing["cases"], 1)
        self.assertEqual(missing["explicit_absence_evidence_retrieved"], 1)
        self.assertGreater(report["metrics"]["incorrect_currency_candidates"], 0)

    def test_report_is_deterministic_and_compact_json_keeps_citation_identity(self):
        first = evaluation.run_financial_evaluation(self.fixture)
        second = evaluation.run_financial_evaluation(self.fixture)
        self.assertEqual(first, second)
        summary = evaluation.summarize_financial_report(first)
        encoded = json.dumps(summary, ensure_ascii=False, sort_keys=True)
        self.assertEqual(json.loads(encoded), summary)
        conflict = next(row for row in summary["cases"]
                        if row["case_id"] == "nexa_conflicting_revenue_2025_en_en")
        self.assertEqual(len(conflict["expected_evidence"]), 2)
        self.assertTrue(all("source_path" in row and "page_number" in row
                            for row in conflict["relevant_citations"]))

    def test_comparative_table_conflict_and_missing_fact_cases_are_explicit(self):
        report = evaluation.run_financial_evaluation(self.fixture)
        comparative = next(row for row in report["cases"]
                           if row["case_id"] == "nexa_comparative_2024_en_ar")
        self.assertEqual(comparative["expected_evidence"][0]["fact_year"], 2024)
        self.assertEqual(comparative["financial_year_filter"], 2025)
        conflict = next(row for row in report["cases"]
                        if row["case_id"] == "nexa_conflicting_revenue_2025_en_en")
        self.assertEqual(conflict["retrieved_expected_passage_count"], 2)
        absence = next(row for row in report["cases"]
                       if row["case_id"] == "atlas_eps_missing_2024_en_en")
        self.assertEqual(absence["case_kind"], "missing_fact")
        self.assertTrue(absence["explicit_absence_retrieved"])
        self.assertEqual(absence["retrieved"][0]["page_number"], 2)

    def test_metadata_mismatch_is_reported_as_incorrect_metadata_and_leakage(self):
        fixture = copy.deepcopy(self.fixture)
        document = next(row for row in fixture["documents"]
                        if row["path"] == "nexa_2025_comparative_ar.txt")
        document["company_id"] = "cedar_energy"
        report = evaluation.run_financial_evaluation(fixture)
        self.assertIn(document["path"], report["metadata_fault_paths"])
        self.assertGreater(report["metrics"]["company_year_leakage"]["count"], 0)
        self.assertGreater(report["failure_causes"]["incorrect_metadata"], 0)

    def test_chunking_failure_is_distinguished_from_source_missing_evidence(self):
        fixture = copy.deepcopy(self.fixture)
        document = next(row for row in fixture["documents"]
                        if row["path"] == "nexa_2025_comparative_ar.txt")
        source = document["pages"][0]
        # Keep identity on the first side of the default chunk boundary and the
        # table on the other side; all labels remain present on the source page.
        document["pages"][0] = source.replace(
            "قائمة الدخل المقارنة", "جدول " + ("بيانات " * 180) + "قائمة الدخل المقارنة"
        )
        report = evaluation.run_financial_evaluation(fixture)
        case = next(row for row in report["cases"]
                    if row["case_id"] == "nexa_revenue_2025_ar_ar")
        self.assertIn("chunking", case["failure_causes"])

    def test_extraction_failure_is_distinguished_from_chunking(self):
        original = evaluation.PageDelimitedFixtureExtractor.extract

        def damaged(extractor, content, *, source_path):
            result = original(extractor, content, source_path=source_path)
            if source_path == "nexa_2025_comparative_ar.txt":
                return replace(result, pages=(replace(result.pages[0], text="page text lost"), *result.pages[1:]))
            return result

        with patch.object(evaluation.PageDelimitedFixtureExtractor, "extract", damaged):
            report = evaluation.run_financial_evaluation(self.fixture)
        case = next(row for row in report["cases"]
                    if row["case_id"] == "nexa_revenue_2025_ar_ar")
        self.assertIn("extraction", case["failure_causes"])

    def test_missing_fact_label_and_retriever_failure_are_reported(self):
        fixture = copy.deepcopy(self.fixture)
        case = next(row for row in fixture["cases"] if row["case_id"] == "atlas_revenue_2024_en_en")
        case["expected_evidence"][0]["amount_aliases"] = ["9999 quadrillion"]
        missing_report = evaluation.run_financial_evaluation(fixture)
        case_report = next(row for row in missing_report["cases"]
                           if row["case_id"] == "atlas_revenue_2024_en_en")
        self.assertIn("missing_evidence", case_report["failure_causes"])

        with patch.object(evaluation.CollectionLexicalRetriever, "retrieve",
                          side_effect=RuntimeError("private detail must not appear")):
            retrieval_report = evaluation.run_financial_evaluation(self.fixture)
        failed = retrieval_report["cases"][0]
        self.assertIn("retrieval", failed["failure_causes"])
        self.assertEqual(failed["retrieval_error_category"], "RuntimeError")
        self.assertNotIn("private detail", json.dumps(retrieval_report))

    def test_invalid_unlabeled_or_ambiguous_fixtures_are_rejected(self):
        fixture = copy.deepcopy(self.fixture)
        fixture["synthetic"] = False
        with self.assertRaisesRegex(evaluation.FinancialFixtureError, "only fixtures"):
            evaluation.validate_financial_fixture(fixture)
        fixture = copy.deepcopy(self.fixture)
        fixture["documents"].append(copy.deepcopy(fixture["documents"][0]))
        with self.assertRaisesRegex(evaluation.FinancialFixtureError, "unique"):
            evaluation.validate_financial_fixture(fixture)
        fixture = copy.deepcopy(self.fixture)
        fixture["cases"][0]["company"] = "Unknown entity"
        with self.assertRaisesRegex(evaluation.FinancialFixtureError, "exactly match"):
            evaluation.validate_financial_fixture(fixture)
        fixture = copy.deepcopy(self.fixture)
        for row in fixture["cases"]:
            row["query_language"] = "en"
        with self.assertRaisesRegex(evaluation.FinancialFixtureError, "directions"):
            evaluation.validate_financial_fixture(fixture)


if __name__ == "__main__":
    unittest.main()
