"""Phase 5 explicit review decisions, citation integrity and analytics handoff."""
from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace

from nexus_ai.data_analytics import AnalyticsInputError
from nexus_ai.documents.types import ExtractedPage, SourceChunk
from nexus_ai.financial_review_workflow import (
    FinancialReviewSession, ReviewDecision, ReviewSelection,
)


def indexed(text: str, *, doc_id: str, page_no: int = 140, version: str = "v1"):
    chunk = SourceChunk(
        chunk_id="c-" + doc_id, document_id=doc_id, version_id=version,
        source_path=doc_id + ".pdf", source_sha256="sha-" + doc_id,
        extractor_name="pypdf", extractor_version="6", page_number=page_no,
        start_char=0, end_char=len(text), start_line=1, end_line=1,
        text=text, heading_path=(), offsets_reliable=True, chunker_version="v1",
    )
    doc = SimpleNamespace(
        workspace_id="tenant", document_id=doc_id, version_id=version,
        content_sha256="sha-" + doc_id, source_path=doc_id + ".pdf",
        pages=(ExtractedPage(page_no, text),),
    )
    return SimpleNamespace(document=doc, chunks=(chunk,))


class Repo:
    def __init__(self):
        self.documents = {
            "annual24": indexed("FY2024 18,206,447", doc_id="annual24", page_no=139),
            "annual25": indexed("FY2025 19,641,705", doc_id="annual25"),
            "repeat25": indexed("total 2025 19,641,705", doc_id="repeat25", page_no=142),
        }

    def get_active(self, workspace, doc_id):
        return self.documents.get(doc_id) if workspace == "tenant" else None


def selection(item, *, amount=None):
    doc, chunk = item.document, item.chunks[0]
    return ReviewSelection({
        "workspace_id": "tenant",
        "document_id": doc.document_id,
        "version_id": doc.version_id,
        "source_sha256": doc.content_sha256,
        "source_path": doc.source_path,
        "page_number": chunk.page_number,
        "chunk_id": chunk.chunk_id,
        "start_char": chunk.start_char,
        "end_char": chunk.end_char,
    }, amount if amount is not None else
       ("18206447" if doc.document_id == "annual24" else "19641705"))


def decision(*, year=2025, **override):
    values = dict(reviewer_id="human-reviewer-1", company="Mobily", year=year,
                  metric="revenue", currency="SAR", unit="thousands",
                  source_page_visually_checked=True,
                  metric_year_unit_visually_confirmed=True)
    values.update(override)
    return ReviewDecision(**values)


class FinancialReviewWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.queue = FinancialReviewSession(repository=self.repo, workspace_id="tenant")

    def test_explicit_review_handoff_to_exact_analytics_and_provenance(self):
        first = self.queue.enqueue(selection(self.repo.documents["annual24"]))
        second = self.queue.enqueue(selection(self.repo.documents["annual25"]))
        self.assertEqual(self.queue.summary()["pending"], 2)
        with self.assertRaises(AnalyticsInputError):
            self.queue.analyze(company="Mobily", metric="revenue", currency="SAR",
                               unit="thousands", start_year=2024, end_year=2025)
        self.queue.approve(first, decision(year=2024))
        self.queue.approve(second, decision(year=2025))
        outcome = self.queue.analyze(
            company="Mobily", metric="revenue", currency="SAR", unit="thousands",
            start_year=2024, end_year=2025,
        )
        self.assertEqual([row["amount"] for row in outcome["annual"]],
                         ["18206447", "19641705"])
        self.assertEqual(outcome["annual"][1]["yoy_percent"], "7.8832")
        self.assertEqual(outcome["unique_financial_facts"], 2)
        self.assertEqual(len(outcome["provenance"]), 2)
        self.assertEqual(outcome["review_workflow"], "EXPLICIT_VOLATILE_HUMAN_APPROVAL")
        self.assertEqual(self.queue.summary()["approved"], 2)
        self.assertEqual(self.queue.summary()["automatically_verified_financial_facts"], 0)

    def test_approval_must_explicitly_confirm_visual_row_and_fields(self):
        key = self.queue.enqueue(selection(self.repo.documents["annual25"]))
        for kwargs in (
            {"source_page_visually_checked": False},
            {"metric_year_unit_visually_confirmed": False},
            {"metric": "invented_metric"},
            {"year": 205},
            {"currency": "BTC"},
            {"reviewer_id": " "},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(AnalyticsInputError):
                self.queue.approve(key, decision(**kwargs))
            self.assertEqual(self.queue.summary()["pending"], 1)
        self.queue.approve(key, decision())
        with self.assertRaises(AnalyticsInputError):
            self.queue.approve(key, decision())

    def test_rejection_never_enters_approved_analytics(self):
        key = self.queue.enqueue(selection(self.repo.documents["annual25"]))
        self.queue.reject(key, reviewer_id="reviewer")
        self.assertEqual(self.queue.summary()["rejected"], 1)
        self.assertEqual(self.queue.summary()["approved"], 0)
        with self.assertRaises(AnalyticsInputError):
            self.queue.approve(key, decision())
        with self.assertRaises(AnalyticsInputError):
            self.queue.analyze(company="Mobily", metric="revenue", currency="SAR",
                               unit="thousands", start_year=2025, end_year=2025)

    def test_source_replacement_invalidates_pending_and_previously_approved(self):
        key = self.queue.enqueue(selection(self.repo.documents["annual25"]))
        self.repo.documents["annual25"] = indexed("FY2025 19,641,705",
                                                 doc_id="annual25", version="v2")
        with self.assertRaisesRegex(AnalyticsInputError, "generation changed"):
            self.queue.approve(key, decision())
        self.assertEqual(self.queue.summary()["pending"], 1)
        self.repo.documents["annual25"] = indexed("FY2025 19,641,705",
                                                 doc_id="annual25", version="v1")
        self.queue.approve(key, decision())
        self.repo.documents["annual25"] = indexed("FY2025 19,641,705",
                                                 doc_id="annual25", version="v3")
        with self.assertRaises(AnalyticsInputError):
            self.queue.analyze(company="Mobily", metric="revenue", currency="SAR",
                               unit="thousands", start_year=2025, end_year=2025)

    def test_forged_amount_and_cross_workspace_citation_rejected(self):
        with self.assertRaises(AnalyticsInputError):
            self.queue.enqueue(selection(self.repo.documents["annual25"], amount="999999"))
        forged = selection(self.repo.documents["annual25"])
        forged.citation["workspace_id"] = "other"
        with self.assertRaisesRegex(AnalyticsInputError, "cross-workspace"):
            self.queue.enqueue(forged)
        self.assertEqual(self.queue.summary()["pending"], 0)

    def test_queue_snapshot_prevents_caller_mutation(self):
        original = selection(self.repo.documents["annual25"])
        key = self.queue.enqueue(original)
        original.citation["chunk_id"] = "forged"
        self.queue.approve(key, decision())
        self.assertEqual(self.queue.summary()["approved"], 1)

    def test_duplicate_source_totals_count_once_after_approval(self):
        for doc_id in ("annual25", "repeat25"):
            key = self.queue.enqueue(selection(self.repo.documents[doc_id]))
            self.queue.approve(key, decision())
        result = self.queue.analyze(
            company="Mobily", metric="revenue", currency="SAR",
            unit="thousands", start_year=2025, end_year=2025,
        )
        self.assertEqual(result["unique_financial_facts"], 1)
        self.assertEqual(result["rows_selected"], 1)
        self.assertEqual(len(result["provenance"][0]["citations"]), 2)

    def test_conflicting_year_totals_rejected_not_summed(self):
        first = self.queue.enqueue(selection(self.repo.documents["annual25"]))
        self.queue.approve(first, decision())
        self.repo.documents["repeat25"] = indexed("FY2025 19,641,706", doc_id="repeat25")
        new_sel = selection(self.repo.documents["repeat25"], amount="19641706")
        second = self.queue.enqueue(new_sel)
        self.queue.approve(second, decision())
        with self.assertRaisesRegex(AnalyticsInputError, "conflicting"):
            self.queue.analyze(company="Mobily", metric="revenue", currency="SAR",
                               unit="thousands", start_year=2025, end_year=2025)

    def test_queue_capacity_is_bounded(self):
        queue = FinancialReviewSession(repository=self.repo, workspace_id="tenant",
                                       max_pending=1)
        queue.enqueue(selection(self.repo.documents["annual25"]))
        with self.assertRaises(AnalyticsInputError):
            queue.enqueue(selection(self.repo.documents["annual24"]))


if __name__ == "__main__":
    unittest.main()
