"""Verify original PDF attachments are source-bound, bounded and opt-in."""
from hashlib import sha256
from io import BytesIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from nexus_ai.data_analytics import AnalyticsInputError
from nexus_ai.financial_review_adapter import ReviewPrincipal
from nexus_ai.financial_review_http import create_financial_review_router
from nexus_ai.financial_review_pdf import make_review_pdf_attachment


def generated_pdf():
    stream = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=300)
    writer.write(stream)
    return stream.getvalue()


class EvidenceLedger:
    workspace_id = "tenant"

    def __init__(self, raw):
        self.raw = raw
        self.calls = []

    def evidence(self, item_id):
        self.calls.append(("evidence", item_id))
        return {
            "id": item_id,
            "document_id": "annual",
            "version_id": "v1",
            "page_number": 1,
            "citation": {
                "workspace_id": "tenant", "document_id": "annual",
                "version_id": "v1", "source_sha256": sha256(self.raw).hexdigest(),
            },
            "evidence_kind": "INDEXED_TEXT_ONLY",
            "requires_original_document_review": True,
        }


def client_for(*, raw=None, grants=None, provider=None, authenticated=True):
    raw = raw if raw is not None else generated_pdf()
    ledger = EvidenceLedger(raw)
    app = FastAPI()
    grants = grants if grants is not None else {"view_pdf"}
    app.include_router(create_financial_review_router(
        workspace_id="tenant",
        ledger_factory=lambda: ledger,
        authenticate_request=lambda request: (
            ReviewPrincipal("reviewer") if authenticated else None
        ),
        authorize=lambda principal, workspace, action: (
            workspace == "tenant" and action in grants
        ),
        pdf_bytes_provider=provider if provider is not None else
                           (lambda doc_id, version_id: raw),
    ))
    return TestClient(app), ledger, raw


def test_valid_original_pdf_is_attachment_and_never_claims_visual_review():
    client, ledger, raw = client_for()
    response = client.get("/financial-reviews/selections/7/original-pdf")
    assert response.status_code == 200
    assert response.content == raw
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["content-security-policy"] == "sandbox"
    assert ledger.calls == [("evidence", 7), ("evidence", 7)]


def test_independent_document_grant_and_auth_deny_provider_access():
    calls = []
    def provider(doc, version):
        calls.append((doc, version))
        return generated_pdf()
    client, _, _ = client_for(grants={"view_evidence"}, provider=provider)
    assert client.get("/financial-reviews/selections/7/original-pdf").status_code == 403
    anonymous, _, _ = client_for(authenticated=False, provider=provider)
    assert anonymous.get("/financial-reviews/selections/7/original-pdf").status_code == 401
    assert calls == []


def test_invalid_or_mismatched_original_pdf_denied():
    raw = generated_pdf()
    for invalid in (b"not a PDF", b"%PDF-broken", generated_pdf() + b"modified"):
        client, _, _ = client_for(raw=raw, provider=lambda doc, version: invalid)
        response = client.get("/financial-reviews/selections/7/original-pdf")
        assert response.status_code == 422
        assert "original" in response.text.lower()


def test_untrusted_provider_failure_is_generic_503():
    def failed(doc, version):
        raise RuntimeError("secret-private-path")
    client, _, _ = client_for(provider=failed)
    response = client.get("/financial-reviews/selections/7/original-pdf")
    assert response.status_code == 503
    assert "secret-private-path" not in response.text


def test_direct_pdf_validation_page_and_size_guards():
    raw = generated_pdf()
    ledger = EvidenceLedger(raw)
    evidence = ledger.evidence(1)
    assert make_review_pdf_attachment(
        indexed_evidence=evidence, pdf_bytes=raw,
    ).status_code == 200
    for value in (None, "bad", b"", b"%PDF-abc", b"%PDF-" + b"x" * (40*1024*1024)):
        with pytest.raises(AnalyticsInputError):
            make_review_pdf_attachment(indexed_evidence=evidence, pdf_bytes=value)
    evidence["page_number"] = 2
    with pytest.raises(AnalyticsInputError):
        make_review_pdf_attachment(indexed_evidence=evidence, pdf_bytes=raw)


def test_opt_in_route_is_absent_without_pdf_provider():
    app = FastAPI()
    app.include_router(create_financial_review_router(
        workspace_id="tenant",
        ledger_factory=lambda: EvidenceLedger(generated_pdf()),
        authenticate_request=lambda request: ReviewPrincipal("reviewer"),
        authorize=lambda *args: True,
    ))
    assert "/financial-reviews/selections/{item_id}/original-pdf" not in {
        route.path for route in app.routes
    }
