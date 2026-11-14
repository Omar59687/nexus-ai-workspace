"""Optional reviewer workbench security/registration contract."""
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus_ai.financial_review_adapter import ReviewPrincipal
from nexus_ai.financial_review_http import create_financial_review_router


def app_for(*, enabled):
    app = FastAPI()
    app.include_router(create_financial_review_router(
        workspace_id="tenant",
        ledger_factory=lambda: object(),
        authenticate_request=lambda request: ReviewPrincipal("reviewer"),
        authorize=lambda *_: False,
        enable_review_page=enabled,
    ))
    return TestClient(app)


def test_default_is_not_mountable_public_page():
    client = app_for(enabled=False)
    response = client.get("/financial-reviews/reviewer")
    assert response.status_code == 404


def test_opt_in_reviewer_is_csp_protected_and_never_persists_token():
    client = app_for(enabled=True)
    response = client.get("/financial-reviews/reviewer")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-content-type-options"] == "nosniff"
    csp = response.headers["content-security-policy"]
    assert "default-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp
    nonce = re.search(r"script-src 'nonce-([^']+)'", csp)
    assert nonce
    assert '<script nonce="' + nonce.group(1) + '">' in response.text
    assert "__NONCE__" not in response.text
    assert "localStorage" not in response.text
    assert "sessionStorage" not in response.text
    assert "innerHTML" not in response.text
    assert "eval(" not in response.text
    assert "indexed_excerpt" in response.text
    assert "source_page_visually_checked" in response.text
    assert "metric_year_unit_visually_confirmed" in response.text
    assert "Download verified original PDF" in response.text


def test_nonce_rotates_per_request():
    client = app_for(enabled=True)
    first = client.get("/financial-reviews/reviewer")
    second = client.get("/financial-reviews/reviewer")
    assert first.headers["content-security-policy"] != second.headers["content-security-policy"]


def test_reviewer_page_does_not_mutate_review_records():
    client = app_for(enabled=True)
    assert client.get("/financial-reviews/reviewer").status_code == 200
    # No auth principal or ledger session is needed to serve HTML itself,
    # but all data endpoints still fail closed for these fake dependencies.
    assert client.get("/financial-reviews/selections").status_code == 503
