"""Reviewed-financial CSV export: exact values, provenance and formula safety."""
import csv
import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus_ai.data_analytics import AnalyticsInputError
from nexus_ai.financial_review_adapter import ReviewPrincipal
from nexus_ai.financial_review_export import render_reviewed_financial_csv
from nexus_ai.financial_review_http import create_financial_review_router


def sample():
    return {
        "company": "Example & Co", "metric": "revenue",
        "currency": "SAR", "unit": "thousands",
        "annual": [
            {"year": 2024, "amount": "18206447", "yoy_percent": None,
             "yoy_unavailable_reason": None},
            {"year": 2025, "amount": "19641705", "yoy_percent": "7.8832",
             "yoy_unavailable_reason": None},
        ],
        "provenance": [
            {"year": 2024, "amount": "18206447",
             "citations": [{"document_id": "report-2024", "page_number": 139}]},
            {"year": 2025, "amount": "19641705",
             "citations": [{"document_id": "report-2025", "page_number": 140}]},
        ],
    }


def test_reviewed_export_preserves_exact_decimals_and_source_pages():
    response = render_reviewed_financial_csv(sample())
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert "attachment" in response.headers["content-disposition"]
    text = response.body.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    assert len(rows) == 2
    assert rows[0]["amount_decimal"] == "18206447"
    assert rows[1]["yoy_percent"] == "7.8832"
    assert rows[1]["citation_document_ids"] == "report-2025"
    assert rows[1]["citation_pages"] == "140"


def test_formula_cells_are_escaped_and_linebreaks_denied():
    data = sample()
    data["company"] = "=HYPERLINK(\"http://example.invalid\")"
    data["provenance"][1]["citations"][0]["document_id"] = "@SUM(1,1)"
    rows = list(csv.DictReader(io.StringIO(
        render_reviewed_financial_csv(data).body.decode("utf-8-sig"))))
    assert rows[1]["company"].startswith("'=")
    assert rows[1]["citation_document_ids"].startswith("'@")
    data["company"] = "multiline\nunsafe"
    with pytest.raises(AnalyticsInputError):
        render_reviewed_financial_csv(data)


@pytest.mark.parametrize("change", [
    lambda d: d.update(annual=[]),
    lambda d: d.update(provenance=[]),
    lambda d: d["provenance"][0].update(citations=[]),
    lambda d: d["provenance"][0].update(year=2030),
    lambda d: d["annual"][0].update(year=True),
    lambda d: d["annual"][0].update(amount="1e7"),
    lambda d: d["annual"][0].update(amount="=1+2"),
    lambda d: d["annual"][0].update(amount="--1"),
    lambda d: d["annual"][0].update(amount="1..2"),
    lambda d: d["annual"][0].update(amount="00"),
    lambda d: d["annual"][0].update(amount="99999999999999999999999999999"),
    lambda d: d["annual"][1].update(yoy_percent="--7"),
    lambda d: d["annual"][1].update(yoy_percent="1..2"),
    lambda d: d["provenance"][0]["citations"][0].update(page_number=0),
    lambda d: d["provenance"][0]["citations"][0].update(document_id="bad\r\nformula"),
])
def test_export_invalid_or_ambiguous_data_fails_closed(change):
    data = sample()
    change(data)
    with pytest.raises(AnalyticsInputError):
        render_reviewed_financial_csv(data)


class FakeLedger:
    workspace_id = "tenant"

    def __init__(self):
        self.calls = []

    def analyze(self, **kwargs):
        self.calls.append(kwargs)
        return sample()


def client(permissions):
    ledger = FakeLedger()
    app = FastAPI()
    app.include_router(create_financial_review_router(
        workspace_id="tenant",
        ledger_factory=lambda: ledger,
        authenticate_request=lambda request: ReviewPrincipal("reviewer"),
        authorize=lambda principal, workspace, action: (
            workspace == "tenant" and action in permissions
        ),
    ))
    return TestClient(app), ledger


def payload():
    return {
        "company": "Example & Co", "metric": "revenue",
        "currency": "SAR", "unit": "thousands",
        "start_year": 2024, "end_year": 2025,
    }


def test_http_export_requires_existing_analyze_permission():
    denied, ledger = client({"status"})
    assert denied.post("/financial-reviews/analyze/export.csv", json=payload()).status_code == 403
    assert ledger.calls == []
    granted, ledger = client({"analyze"})
    response = granted.post("/financial-reviews/analyze/export.csv", json=payload())
    assert response.status_code == 200
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert len(ledger.calls) == 1
