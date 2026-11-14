"""Pinned local PDF provider enforces document ACLs and filesystem safety."""
from hashlib import sha256

import pytest

from nexus_ai.financial_review_adapter import ReviewPrincipal
from nexus_ai.financial_review_source_store import PinnedLocalPdfStore
from tests.test_financial_review_pdf import client_for, generated_pdf


def store_for(tmp_path, *, authorize=None, name="annual.pdf", digest=None):
    raw = generated_pdf()
    (tmp_path / "annual.pdf").write_bytes(raw)
    store = PinnedLocalPdfStore(
        approved_root=tmp_path,
        pinned={("tenant", "annual", "v1"): (
            name, digest if digest is not None else sha256(raw).hexdigest(),
        )},
        authorize_document=authorize if authorize is not None
            else (lambda principal, workspace, doc, action:
                  principal.subject == "reviewer"
                  and workspace == "tenant" and doc == "annual"
                  and action == "view_pdf"),
    )
    return store, raw


def test_pinned_source_is_digest_checked_and_http_downloadable(tmp_path):
    store, raw = store_for(tmp_path)
    assert store(ReviewPrincipal("reviewer"), "tenant", "annual", "v1") == raw
    client, _, _ = client_for(raw=raw, provider=store)
    response = client.get("/financial-reviews/selections/7/original-pdf")
    assert response.status_code == 200
    assert response.content == raw


def test_missing_document_grant_returns_forbidden_not_source_path(tmp_path):
    store, raw = store_for(tmp_path, authorize=lambda *args: False)
    client, _, _ = client_for(raw=raw, provider=store)
    response = client.get("/financial-reviews/selections/7/original-pdf")
    assert response.status_code == 403
    assert str(tmp_path) not in response.text
    with pytest.raises(PermissionError):
        store(ReviewPrincipal("other"), "tenant", "annual", "v1")


def test_cross_workspace_and_wrong_version_fail_closed(tmp_path):
    store, raw = store_for(tmp_path)
    for workspace, version in (("other", "v1"), ("tenant", "v2")):
        with pytest.raises(PermissionError):
            store(ReviewPrincipal("reviewer"), workspace, "annual", version)


def test_pinned_source_rejects_mutated_file(tmp_path):
    store, raw = store_for(tmp_path)
    (tmp_path / "annual.pdf").write_bytes(raw + b"modified")
    with pytest.raises(ValueError, match="unavailable"):
        store(ReviewPrincipal("reviewer"), "tenant", "annual", "v1")


def test_pinned_source_rejects_traversal_and_links(tmp_path):
    outside = tmp_path.parent / "outside-source.pdf"
    outside.write_bytes(generated_pdf())
    try:
        traversal, _ = store_for(tmp_path, name="../outside-source.pdf")
        with pytest.raises(ValueError):
            traversal(ReviewPrincipal("reviewer"), "tenant", "annual", "v1")
        symlink = tmp_path / "linked.pdf"
        try:
            symlink.symlink_to(outside)
        except (OSError, NotImplementedError):
            pytest.skip("symlink not supported in test environment")
        linked, _ = store_for(tmp_path, name="linked.pdf")
        with pytest.raises(ValueError):
            linked(ReviewPrincipal("reviewer"), "tenant", "annual", "v1")
    finally:
        outside.unlink(missing_ok=True)


def test_inventory_cannot_accept_arbitrary_or_empty_bindings(tmp_path):
    with pytest.raises(ValueError):
        PinnedLocalPdfStore(
            approved_root=tmp_path, pinned={},
            authorize_document=lambda *args: True,
        )
    with pytest.raises(ValueError):
        PinnedLocalPdfStore(
            approved_root=tmp_path,
            pinned={("tenant", "annual", "v1"): ("a.pdf", "fake")},
            authorize_document=lambda *args: True,
        )
    with pytest.raises(ValueError):
        PinnedLocalPdfStore(
            approved_root=tmp_path,
            pinned={("tenant", "annual", "v1"): (
                "a.pdf", "0" * 64)},
            authorize_document=None,
        )
