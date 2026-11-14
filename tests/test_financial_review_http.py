"""HTTP contract tests use an in-memory fake and no credentials/database."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus_ai.financial_review_adapter import ReviewPrincipal
from nexus_ai.financial_review_http import create_financial_review_router


class StubLedger:
    workspace_id = "workspace-a"

    def __init__(self):
        self.calls = []

    def submit(self, selection):
        self.calls.append(("submit", selection))
        return 7

    def approve(self, item_id, decision):
        self.calls.append(("approve", item_id, decision))

    def reject(self, item_id, *, reviewer_id):
        self.calls.append(("reject", item_id, reviewer_id))

    def pending(self, *, limit=50):
        self.calls.append(("pending", limit))
        return [{"id": 7, "requires_visual_review": True}]

    def status(self):
        self.calls.append(("status",))
        return {"pending": 1, "approved": 0, "rejected": 0}

    def analyze(self, **kwargs):
        self.calls.append(("analyze", kwargs))
        return {"annual": [], "requires_external_authentication": True}


def make_client(*, authenticated=True, permissions=None, ledger=None):
    ledger = ledger or StubLedger()
    permissions = permissions if permissions is not None else {
        "submit", "approve", "reject", "status", "analyze", "list",
    }
    app = FastAPI()
    app.include_router(create_financial_review_router(
        workspace_id="workspace-a",
        ledger_factory=lambda: ledger,
        authenticate_request=lambda request: (
            ReviewPrincipal("trusted-reviewer") if authenticated else None
        ),
        authorize=lambda principal, workspace, action: (
            principal.subject == "trusted-reviewer"
            and workspace == "workspace-a" and action in permissions
        ),
    ))
    return TestClient(app), ledger


def sample_selection(workspace="workspace-a"):
    return {
        "citation": {
            "workspace_id": workspace, "document_id": "doc-1",
            "version_id": "v1", "source_sha256": "a" * 64,
            "source_path": "reports/annual.pdf",
            "page_number": 5, "chunk_id": "chunk-2",
            "start_char": 11, "end_char": 22,
        },
        "value": "19641705",
    }


def sample_decision():
    return {
        "company": "Mobily", "year": 2025, "metric": "revenue",
        "currency": "SAR", "unit": "thousands",
        "source_page_visually_checked": True,
        "metric_year_unit_visually_confirmed": True,
    }


def test_bounded_api_review_lifecycle_and_trusted_reviewer():
    client, ledger = make_client()
    response = client.post("/financial-reviews/selections", json=sample_selection())
    assert response.status_code == 201
    assert response.json() == {"id": 7}
    response = client.post("/financial-reviews/selections/7/approve",
                           json=sample_decision())
    assert response.status_code == 204
    assert ledger.calls[1][2].reviewer_id == "trusted-reviewer"
    response = client.post("/financial-reviews/selections/8/reject")
    assert response.status_code == 204
    assert ("reject", 8, "trusted-reviewer") in ledger.calls
    assert client.get("/financial-reviews/status").status_code == 200
    assert client.get("/financial-reviews/selections?limit=2").json()["items"][0]["id"] == 7
    assert client.post("/financial-reviews/analyze", json={
        "company": "Mobily", "metric": "revenue", "currency": "SAR",
        "unit": "thousands", "start_year": 2024, "end_year": 2025,
    }).status_code == 200


def test_unauthenticated_requests_fail_before_ledger_access():
    client, ledger = make_client(authenticated=False)
    for method, path, kwargs in [
        ("get", "/financial-reviews/status", {}),
        ("get", "/financial-reviews/selections", {}),
        ("post", "/financial-reviews/selections", {"json": sample_selection()}),
        ("post", "/financial-reviews/selections/7/approve", {"json": sample_decision()}),
        ("post", "/financial-reviews/selections/7/reject", {}),
        ("post", "/financial-reviews/analyze", {"json": {
            "company": "Mobily", "metric": "revenue", "currency": "SAR",
            "unit": "thousands", "start_year": 2024, "end_year": 2025,
        }}),
    ]:
        assert getattr(client, method)(path, **kwargs).status_code == 401
    assert ledger.calls == []


def test_per_action_policy_denials_do_not_reach_ledger():
    client, ledger = make_client(permissions={"status"})
    assert client.get("/financial-reviews/status").status_code == 200
    assert client.post("/financial-reviews/selections",
                       json=sample_selection()).status_code == 403
    assert client.post("/financial-reviews/selections/7/approve",
                       json=sample_decision()).status_code == 403
    assert client.post("/financial-reviews/selections/7/reject").status_code == 403
    assert client.post("/financial-reviews/analyze", json={
        "company": "Mobily", "metric": "revenue", "currency": "SAR",
        "unit": "thousands", "start_year": 2024, "end_year": 2025,
    }).status_code == 403
    assert client.get("/financial-reviews/selections").status_code == 403
    assert ledger.calls == [("status",)]


def test_cross_tenant_and_untrusted_reviewer_body_rejected():
    client, ledger = make_client()
    assert client.post("/financial-reviews/selections",
                       json=sample_selection("other")).status_code == 403
    with_spoofed_reviewer = dict(sample_decision(), reviewer_id="attacker")
    assert client.post("/financial-reviews/selections/7/approve",
                       json=with_spoofed_reviewer).status_code == 422
    assert ledger.calls == []


def test_strict_payloads_and_workspace_mismatch_fail_closed():
    client, ledger = make_client()
    selection = sample_selection()
    selection["citation"]["page_number"] = True
    assert client.post("/financial-reviews/selections",
                       json=selection).status_code == 422
    wrong = StubLedger()
    wrong.workspace_id = "wrong-tenant"
    other_client, _ = make_client(ledger=wrong)
    assert other_client.get("/financial-reviews/status").status_code == 503
    assert ledger.calls == []



def test_queue_limit_rejects_invalid_input():
    client, ledger = make_client()
    assert client.get("/financial-reviews/selections?limit=0").status_code == 422
    assert client.get("/financial-reviews/selections?limit=101").status_code == 422
    assert ledger.calls == []
