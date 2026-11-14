"""Disposable PostgreSQL approval-ledger integration tests.

Uses the Phase 4 suite's opt-in loopback DSN guard and freshly generated
schema. No live production tables, credentials, or application DSNs.
"""
from __future__ import annotations

import unittest

from nexus_ai.data_analytics import AnalyticsInputError
from nexus_ai.financial_review_persistence import (
    FINANCIAL_REVIEW_SCHEMA_DDL, PostgresFinancialReviewLedger,
)
from tests.persistence import test_postgres_integration as _p4_guard
from tests.test_financial_review_workflow import Repo, selection, decision, indexed


class FinancialReviewLedgerLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Reuse the exact catalog-emptiness, loopback-only and disposable-DB
        # checks from Phase 4; do not weaken its operational guardrails.
        _p4_guard.PostgresLiveIntegrationTests.setUpClass.__func__(cls)

    def setUp(self):
        self._schema = _p4_guard._create_test_schema(self._psycopg, self._base_params)
        params = dict(self._base_params)
        params["options"] = f"-csearch_path={self._schema}"
        self._params = params
        with self._psycopg.connect(**params) as connection:
            with connection.cursor() as cursor:
                for statement in FINANCIAL_REVIEW_SCHEMA_DDL:
                    cursor.execute(statement)
        self.collection = Repo()
        self.store = self.ledger()

    def tearDown(self):
        schema = getattr(self, "_schema", None)
        if schema:
            _p4_guard._drop_test_schema(self._psycopg, self._base_params, schema)

    def ledger(self, workspace_id="tenant", **kwargs):
        return PostgresFinancialReviewLedger(
            lambda: self._psycopg.connect(**self._params),
            collection_repository=self.collection,
            workspace_id=workspace_id,
            **kwargs,
        )

    def test_restart_survives_and_exact_reviewed_totals(self):
        one = self.store.submit(selection(self.collection.documents["annual24"]))
        two = self.store.submit(selection(self.collection.documents["annual25"]))
        self.assertEqual(self.store.status()["pending"], 2)
        self.store.approve(one, decision(year=2024))
        self.store.approve(two, decision(year=2025))
        reopened = self.ledger()
        self.assertEqual(reopened.status()["approved"], 2)
        self.assertEqual(reopened.status()["pending"], 0)
        out = reopened.analyze(company="Mobily", metric="revenue",
                               currency="SAR", unit="thousands",
                               start_year=2024, end_year=2025)
        self.assertEqual([row["amount"] for row in out["annual"]],
                         ["18206447", "19641705"])
        self.assertEqual(out["annual"][1]["yoy_percent"], "7.8832")
        self.assertEqual(out["unique_financial_facts"], 2)
        self.assertEqual(out["review_workflow"], "DURABLE_EXPLICIT_HUMAN_APPROVAL")

    def test_rejected_and_double_decided_items_not_reused(self):
        item = self.store.submit(selection(self.collection.documents["annual25"]))
        self.store.reject(item, reviewer_id="reviewer")
        self.assertEqual(self.ledger().status()["rejected"], 1)
        with self.assertRaises(AnalyticsInputError):
            self.store.approve(item, decision())
        with self.assertRaises(AnalyticsInputError):
            self.store.reject(item, reviewer_id="reviewer")
        with self.assertRaises(AnalyticsInputError):
            self.store.analyze(company="Mobily", metric="revenue", currency="SAR",
                               unit="thousands", start_year=2025, end_year=2025)

    def test_decision_validation_rolls_back_and_keeps_pending(self):
        item = self.store.submit(selection(self.collection.documents["annual25"]))
        with self.assertRaises(AnalyticsInputError):
            self.store.approve(item, decision(source_page_visually_checked=False))
        self.assertEqual(self.ledger().status()["pending"], 1)
        with self.assertRaises(AnalyticsInputError):
            self.store.approve(item, decision(reviewer_id=""))
        self.assertEqual(self.ledger().status()["pending"], 1)
        self.store.approve(item, decision())
        self.assertEqual(self.store.status()["approved"], 1)

    def test_source_version_change_fails_pending_and_approved(self):
        item = self.store.submit(selection(self.collection.documents["annual25"]))
        self.collection.documents["annual25"] = indexed(
            "FY2025 19,641,705", doc_id="annual25", version="v2")
        with self.assertRaises(AnalyticsInputError):
            self.store.approve(item, decision())
        self.assertEqual(self.store.status()["pending"], 1)
        self.collection.documents["annual25"] = indexed(
            "FY2025 19,641,705", doc_id="annual25", version="v1")
        self.store.approve(item, decision())
        self.collection.documents["annual25"] = indexed(
            "FY2025 19,641,705", doc_id="annual25", version="v3")
        with self.assertRaises(AnalyticsInputError):
            self.ledger().analyze(company="Mobily", metric="revenue",
                                  currency="SAR", unit="thousands",
                                  start_year=2025, end_year=2025)

    def test_cross_workspace_and_constrained_ledger(self):
        a = self.store.submit(selection(self.collection.documents["annual25"]))
        other = self.ledger(workspace_id="another")
        self.assertEqual(other.status()["pending"], 0)
        with self.assertRaises(AnalyticsInputError):
            other.approve(a, decision())
        with self.assertRaises(AnalyticsInputError):
            other.submit(selection(self.collection.documents["annual25"]))
        constrained = self.ledger(max_records=1)
        with self.assertRaisesRegex(AnalyticsInputError, "capacity"):
            constrained.submit(selection(self.collection.documents["annual24"]))

    def test_duplicate_totals_dedupe_and_conflicts_reject(self):
        for doc_id in ("annual25", "repeat25"):
            key = self.store.submit(selection(self.collection.documents[doc_id]))
            self.store.approve(key, decision())
        outcome = self.ledger().analyze(
            company="Mobily", metric="revenue", currency="SAR",
            unit="thousands", start_year=2025, end_year=2025,
        )
        self.assertEqual(outcome["rows_selected"], 1)
        self.assertEqual(len(outcome["provenance"][0]["citations"]), 2)
        self.collection.documents["repeat25"] = indexed(
            "FY2025 19,641,706", doc_id="repeat25", version="v2")
        with self.assertRaises(AnalyticsInputError):
            self.ledger().analyze(
                company="Mobily", metric="revenue", currency="SAR",
                unit="thousands", start_year=2025, end_year=2025,
            )


if __name__ == "__main__":
    unittest.main()
