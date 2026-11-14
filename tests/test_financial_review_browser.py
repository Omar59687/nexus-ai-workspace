"""Real Chromium smoke test for the *opt-in* financial-review browser.

This test serves the actual FastAPI router on a random loopback port, with
an in-memory fake ledger and a generated noncustomer PDF. It does not claim
to verify real annual reports or any PostgreSQL integration.
"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import socket
import threading

import pytest
from fastapi import FastAPI, Request
from pypdf import PdfWriter
from uvicorn import Config, Server
from playwright.sync_api import sync_playwright

from nexus_ai.financial_review_adapter import ReviewPrincipal
from nexus_ai.financial_review_http import create_financial_review_router

TEST_TOKEN = "synthetic-browser-token-not-a-real-credential"
WORKSPACE = "synthetic-test"


class BrowserLedger:
    workspace_id = WORKSPACE

    def __init__(self, pdf_bytes: bytes):
        self.pdf_bytes = pdf_bytes
        self.state = {7: "PENDING", 8: "PENDING"}
        self.decisions = []

    def _source(self, item_id: int):
        if self.state.get(item_id) != "PENDING":
            raise ValueError("not pending")
        return {
            "id": item_id,
            "document_id": "sample-2025",
            "version_id": "v1",
            "page_number": 1,
            "amount": "19641705",
            "citation": {
                "workspace_id": WORKSPACE,
                "document_id": "sample-2025",
                "version_id": "v1",
                "source_sha256": sha256(self.pdf_bytes).hexdigest(),
            },
            "evidence_kind": "INDEXED_TEXT_ONLY",
            "requires_original_document_review": True,
            "original_pdf_visually_checked": False,
            "indexed_excerpt": "Synthetic FY2025 figure: 19,641,705",
        }

    def pending(self, *, limit=50):
        return [
            {
                "id": item_id, "document_id": "sample-2025",
                "version_id": "v1", "page_number": 1,
                "amount": "19641705",
            }
            for item_id, state in self.state.items()
            if state == "PENDING"
        ][:limit]

    def evidence(self, item_id):
        from nexus_ai.data_analytics import AnalyticsInputError
        if self.state.get(item_id) != "PENDING":
            raise AnalyticsInputError("item resolved")
        return self._source(item_id)

    def approve(self, item_id, decision):
        from nexus_ai.data_analytics import AnalyticsInputError
        if self.state.get(item_id) != "PENDING":
            raise AnalyticsInputError("item resolved")
        if not (decision.source_page_visually_checked
                and decision.metric_year_unit_visually_confirmed):
            raise AnalyticsInputError("visual review required")
        self.decisions.append((item_id, decision))
        self.state[item_id] = "APPROVED"

    def reject(self, item_id, *, reviewer_id):
        self.decisions.append((item_id, reviewer_id))
        self.state[item_id] = "REJECTED"

    def analyze(self, **kwargs):
        from nexus_ai.data_analytics import AnalyticsInputError
        if not any(state == "APPROVED" for state in self.state.values()):
            raise AnalyticsInputError("no approved facts")
        return {
            "company": kwargs["company"], "metric": kwargs["metric"],
            "currency": kwargs["currency"], "unit": kwargs["unit"],
            "unique_financial_facts": 1,
            "annual": [{"year": 2025, "amount": "19641705",
                        "yoy_percent": None, "yoy_unavailable_reason": None}],
            "provenance": [{"year": 2025, "amount": "19641705",
                            "citations": [{"document_id": "sample-2025",
                                           "page_number": 1}]}],
            "provenance_policy": "Synthetic evidence, manually attributed.",
        }


@pytest.fixture
def running_server():
    stream = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=300)
    writer.write(stream)
    pdf_bytes = stream.getvalue()
    ledger = BrowserLedger(pdf_bytes)
    app = FastAPI()

    def authenticate(request: Request):
        if request.headers.get("authorization") != f"Bearer {TEST_TOKEN}":
            raise PermissionError("no valid test session")
        return ReviewPrincipal("synthetic-reviewer")

    app.include_router(create_financial_review_router(
        workspace_id=WORKSPACE,
        ledger_factory=lambda: ledger,
        authenticate_request=authenticate,
        authorize=lambda principal, workspace, action: (
            principal.subject == "synthetic-reviewer" and workspace == WORKSPACE
            and action in {"list", "view_evidence", "view_pdf", "approve", "reject", "analyze"}
        ),
        pdf_bytes_provider=lambda principal, workspace, doc_id, version_id: (
            pdf_bytes if principal.subject == "synthetic-reviewer"
            and workspace == WORKSPACE and doc_id == "sample-2025"
            and version_id == "v1" else None
        ),
        enable_review_page=True,
    ))

    server = Server(Config(app, host="127.0.0.1", port=0, log_level="warning"))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(128)
        port = sock.getsockname()[1]
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        try:
            import time
            for _ in range(100):
                if server.started:
                    break
                if not thread.is_alive():
                    pytest.fail("test-only HTTP server failed")
                time.sleep(0.05)
            assert server.started
            yield f"http://127.0.0.1:{port}", ledger, pdf_bytes
        finally:
            server.should_exit = True
            thread.join(timeout=10)


def test_real_chromium_review_workflow(running_server):
    base_url, ledger, pdf_bytes = running_server
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(accept_downloads=True)
            page.goto(base_url + "/financial-reviews/reviewer")
            assert page.get_by_text("Not connected.").count() == 1
            page.locator("#refresh").click()
            page.get_by_role("status").get_by_text("Enter your reviewer token first.").wait_for()

            page.locator("#token").fill(TEST_TOKEN)
            page.locator("#connect").click()
            page.get_by_role("status").get_by_text("Loaded 2 pending items.").wait_for()
            assert page.locator("#token").input_value() == ""

            page.locator("#queue button").first.click()
            page.get_by_role("status").get_by_text(
                "Indexed excerpt loaded. Original PDF still requires inspection."
            ).wait_for()
            assert "Synthetic FY2025" in page.locator("#excerpt").inner_text()
            assert not page.locator("#approve").is_disabled()

            with page.expect_download() as download_info:
                page.locator("#pdf").click()
            download = download_info.value
            assert download.suggested_filename == "financial-source.pdf"
            assert download.path().read_bytes() == pdf_bytes

            page.locator("#company").fill("Example Company")
            page.locator("#year").fill("2025")
            page.locator("#approve").click()
            assert ledger.decisions == []
            page.locator("#pageChecked").check()
            page.locator("#rowChecked").check()
            page.locator("#approve").click()
            page.get_by_role("status").get_by_text("Review decision recorded.").wait_for()
            assert ledger.state[7] == "APPROVED"
            assert ledger.decisions[0][1].reviewer_id == "synthetic-reviewer"

            page.locator("#analysisCompany").fill("Example Company")
            page.locator("#analysisStart").fill("2025")
            page.locator("#analysisEnd").fill("2025")
            page.locator("#analysisUnit").select_option("thousands")
            page.locator("#runAnalysis").click()
            page.get_by_role("status").get_by_text(
                "Reviewed financial analysis loaded."
            ).wait_for()
            analysis = page.locator("#analysisResults")
            assert analysis.get_by_text("19641705").count() == 1
            assert analysis.get_by_text("sample-2025 p.1").count() == 1

            page.locator("#queue button").first.click()
            page.get_by_role("status").get_by_text(
                "Indexed excerpt loaded. Original PDF still requires inspection."
            ).wait_for()
            page.on("dialog", lambda dialog: dialog.accept())
            page.locator("#reject").click()
            page.get_by_role("status").get_by_text("Selection rejected.").wait_for()
            assert ledger.state[8] == "REJECTED"
            page.locator("#disconnect").click()
            page.get_by_role("status").get_by_text("Reviewer token cleared.").wait_for()
            assert page.locator("#queue button").count() == 0
            assert page.locator("#analysisResults").inner_text() == ""
        finally:
            browser.close()


def test_real_chromium_cannot_read_queue_without_authentication(running_server):
    base_url, ledger, _ = running_server
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(base_url + "/financial-reviews/reviewer")
            page.locator("#token").fill("wrong-token")
            page.locator("#connect").click()
            page.get_by_role("status").get_by_text("Request failed (401).").wait_for()
            assert page.locator("#queue button").count() == 0
            assert ledger.decisions == []
        finally:
            browser.close()

def test_switching_to_invalid_token_clears_prior_review_data(running_server):
    base_url, ledger, _ = running_server
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(base_url + "/financial-reviews/reviewer")
            page.locator("#token").fill(TEST_TOKEN)
            page.locator("#connect").click()
            page.get_by_role("status").get_by_text("Loaded 2 pending items.").wait_for()
            page.locator("#queue button").first.click()
            page.get_by_role("status").get_by_text(
                "Indexed excerpt loaded. Original PDF still requires inspection."
            ).wait_for()
            assert "Synthetic FY2025" in page.locator("#excerpt").inner_text()

            page.locator("#token").fill("invalid-token")
            page.locator("#connect").click()
            page.get_by_role("status").get_by_text("Request failed (401).").wait_for()
            assert page.locator("#queue button").count() == 0
            assert "Synthetic FY2025" not in page.locator("#excerpt").inner_text()
            assert page.locator("#analysisResults").inner_text() == ""
            page.locator("#refresh").click()
            page.get_by_role("status").get_by_text("Enter your reviewer token first.").wait_for()
            assert ledger.decisions == []
        finally:
            browser.close()
