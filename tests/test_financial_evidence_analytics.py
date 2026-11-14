"""Source-linked financial analytics: validated citations, dedup and fail-closed."""
from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace

from nexus_ai.data_analytics import AnalyticsInputError
from nexus_ai.documents.types import ExtractedPage, SourceChunk
from nexus_ai.financial_evidence_analytics import (
    ReviewedFinancialObservation, analyze_reviewed_evidence,
)


def make_index(text: str, *, document_id: str, source_path: str, page_no: int):
    chunk = SourceChunk(
        chunk_id=f"chunk-{document_id}-{page_no}", document_id=document_id,
        version_id="v1", source_path=source_path, source_sha256="digest",
        extractor_name="pypdf", extractor_version="6.0",
        page_number=page_no, start_char=0, end_char=len(text),
        start_line=1, end_line=1, text=text, heading_path=(),
        offsets_reliable=True, chunker_version="chunker1",
    )
    doc = SimpleNamespace(
        workspace_id="tenant-a", document_id=document_id,
        version_id="v1", source_path=source_path, content_sha256="digest",
        pages=(ExtractedPage(page_no, text),),
    )
    return SimpleNamespace(document=doc, chunks=(chunk,))


class Repo:
    def __init__(self, indexes):
        self.indexes = indexes

    def get_active(self, workspace_id, document_id):
        if workspace_id != "tenant-a":
            return None
        return self.indexes.get(document_id)


class FinancialEvidenceAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo({
            "annual24": make_index(
                "FY2024 total revenue SAR thousands 18,206,447",
                document_id="annual24", source_path="annual24.pdf", page_no=114,
            ),
            "annual25": make_index(
                "FY2025 total revenue SAR thousands 19,641,705",
                document_id="annual25", source_path="annual25.pdf", page_no=140,
            ),
            "segment25": make_index(
                "FY2025 segment total 19,641,705",
                document_id="segment25", source_path="segment25.pdf", page_no=142,
            ),
        })

    def observation(self, document_id, year, amount, *, reviewed=True, **overrides):
        src = self.repo.indexes[document_id]
        d, c = src.document, src.chunks[0]
        fields = dict(
            workspace_id="tenant-a", document_id=d.document_id,
            document_version_id=d.version_id, source_sha256=d.content_sha256,
            source_path=d.source_path, page_number=c.page_number,
            chunk_id=c.chunk_id, start_char=c.start_char, end_char=c.end_char,
            company="Mobily", year=year, metric="revenue", amount=amount,
            currency="SAR", unit="thousands", reviewer_asserted_row=reviewed,
        )
        fields.update(overrides)
        return ReviewedFinancialObservation(**fields)

    def analyze(self, rows, **overrides):
        args = dict(repository=self.repo, workspace_id="tenant-a",
                    company="Mobily", metric="revenue", currency="SAR",
                    unit="thousands", start_year=2024, end_year=2025)
        args.update(overrides)
        return analyze_reviewed_evidence(rows, **args)

    def test_independent_2024_and_2025_source_versions_and_yoy(self):
        result = self.analyze([
            self.observation("annual24", 2024, "18206447"),
            self.observation("annual25", 2025, "19641705"),
        ])
        self.assertEqual([r["amount"] for r in result["annual"]], ["18206447", "19641705"])
        self.assertEqual(result["annual"][1]["yoy_percent"], "7.8832")
        self.assertEqual(result["unique_financial_facts"], 2)
        self.assertEqual(result["rows_selected"], 2)
        self.assertEqual(result["provenance"][1]["citations"][0]["page_number"], 140)
        self.assertIn("human-reviewed", result["provenance_policy"])

    def test_two_citations_for_same_financial_total_dedupe(self):
        result = self.analyze([
            self.observation("annual25", 2025, "19641705"),
            self.observation("segment25", 2025, "19641705"),
        ])
        self.assertEqual(result["rows_selected"], 1)
        self.assertEqual(result["unique_financial_facts"], 1)
        self.assertEqual(len(result["provenance"][0]["citations"]), 2)

    def test_exact_amount_supports_arabic_digits_and_separators(self):
        old = self.repo.indexes["annual25"]
        edited = "إجمالي الإيرادات ١٩٬٦٤١٬٧٠٥"
        replacement_chunk = replace(old.chunks[0], text=edited, end_char=len(edited))
        self.repo.indexes["annual25"] = SimpleNamespace(
            document=SimpleNamespace(**{**vars(old.document),
                "pages": (ExtractedPage(140, edited),)}),
            chunks=(replacement_chunk,),
        )
        result = self.analyze([self.observation("annual25", 2025, "19641705")])
        self.assertEqual(result["annual"][0]["amount"], "19641705")

    def test_unreviewed_stale_source_and_cross_tenant_rejected(self):
        item = self.observation("annual25", 2025, "19641705")
        for altered in (
            replace(item, reviewer_asserted_row=False),
            replace(item, workspace_id="tenant-b"),
            replace(item, document_version_id="old"),
            replace(item, source_sha256="not-current"),
            replace(item, page_number=141),
            replace(item, start_char=1),
            replace(item, chunk_id="wrong"),
        ):
            with self.subTest(altered=altered), self.assertRaises(AnalyticsInputError):
                self.analyze([altered])

    def test_number_not_in_source_rejected(self):
        item = self.observation("annual25", 2025, "18206447")
        with self.assertRaisesRegex(AnalyticsInputError, "exact stated amount"):
            self.analyze([item])

    def test_conflicting_totals_not_summed(self):
        old = self.repo.indexes["segment25"]
        updated = "2025 segment total 19,641,706"
        self.repo.indexes["segment25"] = SimpleNamespace(
            document=SimpleNamespace(**{**vars(old.document),
                "pages": (ExtractedPage(142, updated),)}),
            chunks=(replace(old.chunks[0], text=updated, end_char=len(updated)),),
        )
        with self.assertRaisesRegex(AnalyticsInputError, "conflicting reviewed"):
            self.analyze([
                self.observation("annual25", 2025, "19641705"),
                self.observation("segment25", 2025, "19641706"),
            ])

    def test_mixed_units_and_currencies_rejected_even_with_review(self):
        for change in ({"currency": "USD"}, {"unit": "millions"}):
            with self.subTest(change=change), self.assertRaises(AnalyticsInputError):
                self.analyze([self.observation("annual25", 2025, "19641705", **change)])

    def test_source_replacement_during_read_rejected(self):
        index = self.repo.indexes["annual25"]
        class ChangingRepo:
            def __init__(self):
                self.calls = 0
            def get_active(self, workspace_id, document_id):
                self.calls += 1
                if self.calls > 1:
                    return SimpleNamespace(
                        document=SimpleNamespace(**{**vars(index.document), "version_id": "v2"}),
                        chunks=index.chunks,
                    )
                return index
        with self.assertRaisesRegex(AnalyticsInputError, "source version changed"):
            analyze_reviewed_evidence(
                [self.observation("annual25", 2025, "19641705")],
                repository=ChangingRepo(), workspace_id="tenant-a",
                company="Mobily", metric="revenue", currency="SAR",
                unit="thousands", start_year=2025, end_year=2025,
            )


if __name__ == "__main__":
    unittest.main()
