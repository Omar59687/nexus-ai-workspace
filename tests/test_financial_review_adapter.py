"""Model-independent authorization boundary tests; no live database."""
from dataclasses import replace
import unittest

from nexus_ai.financial_review_adapter import (
    AuthorizedFinancialReviewAdapter, ReviewPrincipal,
)
from nexus_ai.financial_review_workflow import ReviewDecision, ReviewSelection


class FakeLedger:
    workspace_id = "workspace-a"

    def __init__(self):
        self.calls = []

    def submit(self, selection):
        self.calls.append(("submit", selection))
        return 42

    def approve(self, item_id, decision):
        self.calls.append(("approve", item_id, decision.reviewer_id))

    def reject(self, item_id, *, reviewer_id):
        self.calls.append(("reject", item_id, reviewer_id))

    def status(self):
        self.calls.append(("status",))
        return {"pending": 0}

    def analyze(self, **kwargs):
        self.calls.append(("analyze", kwargs))
        return {"annual": []}


class AuthorizedReviewAdapterTests(unittest.TestCase):
    def setUp(self):
        self.ledger = FakeLedger()
        self.principal = ReviewPrincipal("reviewer-1")
        self.allowed = {"submit", "approve", "reject", "status", "analyze"}
        self.audit = []
        self.adapter = AuthorizedFinancialReviewAdapter(
            ledger=self.ledger,
            resolve_principal=lambda: self.principal,
            authorize=self.policy,
        )

    def policy(self, principal, workspace, action):
        self.audit.append((principal.subject, workspace, action))
        return workspace == "workspace-a" and action in self.allowed

    def decision(self):
        return ReviewDecision(
            reviewer_id="reviewer-1", company="Mobily", year=2025,
            metric="revenue", currency="SAR", unit="thousands",
            source_page_visually_checked=True,
            metric_year_unit_visually_confirmed=True,
        )

    def test_allowed_workflow_binds_reviewer_identity_and_scope(self):
        selection = ReviewSelection({"example": "citation"}, "123")
        self.assertEqual(self.adapter.submit(selection), 42)
        self.adapter.approve(42, self.decision())
        self.adapter.reject(43)
        self.assertEqual(self.adapter.status(), {"pending": 0})
        self.assertEqual(self.adapter.analyze(
            company="Mobily", metric="revenue", currency="SAR",
            unit="thousands", start_year=2025, end_year=2025,
        ), {"annual": []})
        self.assertEqual([x[2] for x in self.audit],
                         ["submit", "approve", "reject", "status", "analyze"])
        self.assertTrue(all(x[1] == "workspace-a" for x in self.audit))
        self.assertIn(("reject", 43, "reviewer-1"), self.ledger.calls)

    def test_denied_operation_never_touches_ledger(self):
        self.allowed.discard("analyze")
        with self.assertRaises(PermissionError):
            self.adapter.analyze(company="Mobily", metric="revenue",
                currency="SAR", unit="thousands", start_year=2025,
                end_year=2025)
        self.assertEqual(self.ledger.calls, [])

    def test_untrusted_principal_and_broken_policy_fail_closed(self):
        for principal in (None, "reviewer-1", ReviewPrincipal(""), ReviewPrincipal("x" * 129)):
            self.principal = principal
            with self.assertRaises(PermissionError):
                self.adapter.status()
        self.assertEqual(self.ledger.calls, [])
        self.principal = ReviewPrincipal("reviewer-1")
        self.adapter = AuthorizedFinancialReviewAdapter(
            ledger=self.ledger, resolve_principal=lambda: self.principal,
            authorize=lambda *_: None,
        )
        with self.assertRaises(PermissionError):
            self.adapter.submit(ReviewSelection({}, "1"))
        self.assertEqual(self.ledger.calls, [])

    def test_untrusted_reviewer_identity_cannot_be_submitted(self):
        with self.assertRaises(PermissionError):
            self.adapter.approve(12, replace(self.decision(), reviewer_id="someone-else"))
        self.assertEqual(self.ledger.calls, [])

    def test_policy_is_checked_every_time_not_cached(self):
        self.adapter.status()
        self.allowed.clear()
        with self.assertRaises(PermissionError):
            self.adapter.status()
        self.assertEqual(self.ledger.calls, [("status",)])

    def test_throws_when_trusted_resolver_or_policy_missing(self):
        with self.assertRaises(ValueError):
            AuthorizedFinancialReviewAdapter(ledger=self.ledger,
                resolve_principal=None, authorize=self.policy)
        failing = AuthorizedFinancialReviewAdapter(
            ledger=self.ledger,
            resolve_principal=lambda: (_ for _ in ()).throw(RuntimeError("auth down")),
            authorize=self.policy,
        )
        with self.assertRaises(PermissionError):
            failing.status()
        self.assertEqual(self.ledger.calls, [])


if __name__ == "__main__":
    unittest.main()
