"""End-to-end: geometry hints stay separate; approved source numbers reach analytics."""
from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace

from nexus_ai.documents.types import ExtractedPage, SourceChunk
from nexus_ai.data_analytics import AnalyticsInputError
from nexus_ai.financial_geometry_review import build_financial_review_inventory
from nexus_ai.financial_positioned_tables import PositionedText
from nexus_ai.financial_review_workflow import (
    FinancialReviewSession, ReviewDecision, ReviewSelection,
)


def index(doc_id: str, year: int, value: str, page: int):
    text = f"{year} {value}\n"
    chunk = SourceChunk(
        chunk_id=f"c-{doc_id}", document_id=doc_id, version_id="v1",
        source_path=f"{doc_id}.pdf", source_sha256=f"sha-{doc_id}",
        extractor_name="pypdf", extractor_version="6", page_number=page,
        start_char=0, end_char=len(text), start_line=1, end_line=1,
        text=text, heading_path=(), offsets_reliable=True, chunker_version="v1",
    )
    doc = SimpleNamespace(
        workspace_id="tenant", document_id=doc_id, version_id="v1",
        content_sha256=f"sha-{doc_id}", source_path=f"{doc_id}.pdf",
        pages=(ExtractedPage(page, text),),
    )
    return SimpleNamespace(document=doc, chunks=(chunk,))


class Repo:
    def __init__(self):
        self.items = {
            "d24": index("d24", 2024, "18,206,447", 139),
            "d25": index("d25", 2025, "19,641,705", 140),
        }
    def get_active(self, workspace, document):
        return self.items.get(document) if workspace == "tenant" else None


def boxes(page: int, year: int, amount: str):
    # The Arabic heading exists in PDF position fragments, *not* in
    # the indexed text. It must not be silently attached to the number.
    return (
        PositionedText(page, 300, 20, "إجمالي الإيرادات"),
        PositionedText(page, 300, 38, "ألف ريال سعودي"),
        PositionedText(page, 200, 70, str(year)),
        PositionedText(page, 200, 102, amount),
    )


def decision(year: int):
    return ReviewDecision(
        reviewer_id="external-auth-test-user", company="Mobily", year=year,
        metric="revenue", currency="SAR", unit="thousands",
        source_page_visually_checked=True,
        metric_year_unit_visually_confirmed=True,
    )


class EndToEndReviewTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.workflow = FinancialReviewSession(repository=self.repo,
                                               workspace_id="tenant")

    def inventory(self, doc_id, page, year, value):
        return build_financial_review_inventory(
            boxes(page, year, value), repository=self.repo,
            workspace_id="tenant", document_id=doc_id, page_number=page,
        )

    def test_realistic_unindexed_arabic_labels_to_explicit_reviewed_analysis(self):
        inv24 = self.inventory("d24", 139, 2024, "18,206,447")
        inv25 = self.inventory("d25", 140, 2025, "19,641,705")
        for inventory in (inv24, inv25):
            self.assertEqual(inventory["numeric_citation_count"], 1)
            self.assertEqual(inventory["geometry_label_band_count"], 2)
            self.assertEqual(inventory["cross_evidence_associations"], 0)
            self.assertEqual(inventory["automatically_verified_financial_facts"], 0)
        ids = []
        for inventory in (inv24, inv25):
            candidate = inventory["numeric_citations"][0]
            ids.append(self.workflow.enqueue(ReviewSelection(
                citation=candidate["citation"], value=candidate["value"],
            )))
        with self.assertRaisesRegex(AnalyticsInputError, "no explicitly approved"):
            self.workflow.analyze(
                company="Mobily", metric="revenue", currency="SAR",
                unit="thousands", start_year=2024, end_year=2025,
            )
        self.workflow.approve(ids[0], decision(2024))
        self.workflow.approve(ids[1], decision(2025))
        output = self.workflow.analyze(
            company="Mobily", metric="revenue", currency="SAR",
            unit="thousands", start_year=2024, end_year=2025,
        )
        self.assertEqual([r["amount"] for r in output["annual"]],
                         ["18206447", "19641705"])
        self.assertEqual(output["annual"][1]["yoy_percent"], "7.8832")
        self.assertEqual(len(output["provenance"]), 2)
        self.assertEqual(output["review_workflow"], "EXPLICIT_VOLATILE_HUMAN_APPROVAL")

    def test_geometry_hints_alone_never_create_reviewable_amount(self):
        inventory = self.inventory("d25", 140, 2025, "999,999,999")
        self.assertEqual(inventory["numeric_citation_count"], 0)
        self.assertGreater(inventory["geometry_label_band_count"], 0)
        with self.assertRaises(AnalyticsInputError):
            self.workflow.enqueue(ReviewSelection(
                citation={
                    "workspace_id": "tenant", "document_id": "d25",
                    "version_id": "v1", "source_sha256": "sha-d25",
                    "source_path": "d25.pdf", "page_number": 140,
                    "chunk_id": "c-d25", "start_char": 0,
                    "end_char": len("2025 19,641,705\n"),
                },
                value="999999999",
            ))
        self.assertEqual(self.workflow.summary()["approved"], 0)


if __name__ == "__main__":
    unittest.main()
