"""Full test-only source PDF -> authenticated review -> analytics transaction.

This suite uses an isolated localhost database and a synthetic PDF created
in memory. It never opens a real report or contacts a hosted service.
"""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, DictionaryObject, DecodedStreamObject

from nexus_ai.financial_review_access import (
    FINANCIAL_AUTH_SCHEMA_DDL, PostgresFinancialAccess,
)
from nexus_ai.financial_review_http import create_financial_review_router
from nexus_ai.financial_review_persistence import (
    FINANCIAL_REVIEW_SCHEMA_DDL, PostgresFinancialReviewLedger,
)
from nexus_ai.financial_review_provisioning import FinancialReviewProvisioner
from tests.persistence import test_postgres_integration as _guard
from tests.test_financial_review_workflow import Repo, indexed, selection


def _source_pdf() -> tuple[bytes, str]:
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    reference = writer._add_object(font)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): reference}),
    })
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 40 250 Td (FY2025 19,641,705) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    raw = output.getvalue()
    text = PdfReader(BytesIO(raw), strict=True).pages[0].extract_text()
    assert "19,641,705" in text
    return raw, text


class FullFinancialReviewStackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _guard.PostgresLiveIntegrationTests.setUpClass.__func__(cls)

    def setUp(self):
        self._schema = _guard._create_test_schema(self._psycopg, self._base_params)
        params = dict(self._base_params)
        params["options"] = f"-csearch_path={self._schema}"
        self._params = params
        with self._psycopg.connect(**params) as db:
            with db.cursor() as cur:
                for stmt in (*FINANCIAL_REVIEW_SCHEMA_DDL, *FINANCIAL_AUTH_SCHEMA_DDL):
                    cur.execute(stmt)

        self.raw, text = _source_pdf()
        digest = sha256(self.raw).hexdigest()
        original = indexed(text, doc_id="annual25", page_no=1, version="v1")
        original.document.content_sha256 = digest
        original.chunks = (replace(original.chunks[0], source_sha256=digest),)
        self.repo = Repo()
        self.repo.documents = {"annual25": original}
        factory = lambda: self._psycopg.connect(**params)
        access = PostgresFinancialAccess(factory)
        operator = FinancialReviewProvisioner(factory)
        self.token = operator.create_session(subject="reviewer", ttl_seconds=600)
        for action in ("submit", "list", "view_evidence", "view_pdf",
                       "approve", "reject", "status", "analyze"):
            operator.grant(subject="reviewer", workspace_id="tenant", action=action)
        self.operator = operator
        app = FastAPI()
        app.include_router(create_financial_review_router(
            workspace_id="tenant",
            ledger_factory=lambda: PostgresFinancialReviewLedger(
                factory, collection_repository=self.repo, workspace_id="tenant",
            ),
            authenticate_request=access.authenticate_request,
            authorize=access.authorize,
            pdf_bytes_provider=lambda doc_id, version_id: self.raw,
        ))
        self.client = TestClient(app)
        self.auth = {"Authorization": "Bearer " + self.token}

    def tearDown(self):
        if getattr(self, "_schema", None):
            _guard._drop_test_schema(self._psycopg, self._base_params, self._schema)

    def test_complete_review_from_real_pdf_bytes_to_financial_analytics(self):
        claim = selection(self.repo.documents["annual25"])
        start = self.client.post("/financial-reviews/selections",
                                 headers=self.auth,
                                 json={"citation": claim.citation, "value": claim.value})
        self.assertEqual(start.status_code, 201, start.text)
        item_id = start.json()["id"]
        queue = self.client.get("/financial-reviews/selections", headers=self.auth)
        self.assertEqual(queue.status_code, 200, queue.text)
        self.assertEqual(queue.json()["items"][0]["id"], item_id)

        evidence = self.client.get(
            f"/financial-reviews/selections/{item_id}/evidence", headers=self.auth)
        self.assertEqual(evidence.status_code, 200, evidence.text)
        self.assertIn("19,641,705", evidence.json()["indexed_excerpt"])
        self.assertFalse(evidence.json()["original_pdf_visually_checked"])
        pdf = self.client.get(
            f"/financial-reviews/selections/{item_id}/original-pdf",
            headers=self.auth)
        self.assertEqual(pdf.status_code, 200, pdf.text)
        self.assertEqual(pdf.content, self.raw)

        decision = {
            "company": "Mobily", "year": 2025, "metric": "revenue",
            "currency": "SAR", "unit": "thousands",
            "source_page_visually_checked": True,
            "metric_year_unit_visually_confirmed": True,
        }
        incomplete = dict(decision, source_page_visually_checked=False)
        self.assertEqual(self.client.post(
            f"/financial-reviews/selections/{item_id}/approve",
            json=incomplete, headers=self.auth).status_code, 422)
        self.assertEqual(self.client.post(
            f"/financial-reviews/selections/{item_id}/approve",
            json=decision, headers=self.auth).status_code, 204)
        self.assertEqual(self.client.get(
            f"/financial-reviews/selections/{item_id}/evidence",
            headers=self.auth).status_code, 422)

        analysis = self.client.post(
            "/financial-reviews/analyze", headers=self.auth,
            json={
                "company": "Mobily", "metric": "revenue",
                "currency": "SAR", "unit": "thousands",
                "start_year": 2025, "end_year": 2025,
            })
        self.assertEqual(analysis.status_code, 200, analysis.text)
        self.assertEqual(analysis.json()["annual"][0]["amount"], "19641705")
        self.assertEqual(analysis.json()["review_workflow"],
                         "DURABLE_EXPLICIT_HUMAN_APPROVAL")

        self.operator.revoke_session(
            token_sha256=sha256(self.token.encode("ascii")).hexdigest())
        self.assertEqual(self.client.get(
            "/financial-reviews/status", headers=self.auth).status_code, 401)

    def test_original_pdf_source_version_replacement_fails_closed(self):
        claim = selection(self.repo.documents["annual25"])
        item_id = self.client.post(
            "/financial-reviews/selections", headers=self.auth,
            json={"citation": claim.citation, "value": claim.value},
        ).json()["id"]
        self.repo.documents["annual25"] = indexed(
            "FY2025 19,641,705", doc_id="annual25", page_no=1, version="v2")
        self.assertEqual(self.client.get(
            f"/financial-reviews/selections/{item_id}/evidence",
            headers=self.auth).status_code, 422)
        self.assertEqual(self.client.get(
            f"/financial-reviews/selections/{item_id}/original-pdf",
            headers=self.auth).status_code, 422)


if __name__ == "__main__":
    unittest.main()
