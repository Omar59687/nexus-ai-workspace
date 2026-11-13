# Phase 4 — Owner-approved manifest to indexed metadata integration

**Status:** review-branch implementation committed. Focused Windows tests are
pending; this is not a production persistence release.

## Goal

Join **existing indexed source versions** to owner-supplied collection metadata
without inferring financial years or companies from PDFs or file names.

The bridge is intentionally model-independent and never calls E5, Gemma or
cloud providers. The manifest format is the existing bounded 1–150-file
`documents` array with `path`, `company`, `year`. All entries must already
have been ingested into the authorized `DocumentIndexRepository` using its
existing document identity and version contracts.

## Integration API

```python
from nexus_ai.retrieval.collection_registration import register_indexed_manifest
from nexus_ai.retrieval.company_metadata import CompanyYearFilter
from nexus_ai.retrieval.service import RetrievalService

snapshot = register_indexed_manifest(
    catalog=metadata_catalog,
    repository=document_repository,
    workspace_id=authorized_workspace_id,
    collection_id="annual-reports",
    entries=validated_manifest_entries,
    companies={
        "mobily": ("Mobily", "شركة اتحاد اتصالات موبايلي"),
        "aramco": ("Aramco", "أرامكو"),
    },
)

retriever = RetrievalService(
    repository=document_repository,
    embedder=embedding_provider,
    company_metadata=metadata_catalog,
)
result = retriever.retrieve(
    "revenue",
    workspace_id=authorized_workspace_id,
    strategy="bm25_raw",
    company_year_filter=CompanyYearFilter(
        "annual-reports", "Mobily", 2025
    ),
)
```

The helper does not authorize the workspace; **the caller must use a trusted
authorized workspace ID**. All declared source paths must be active with
matching exact document and version identities. Registration is atomic: a
missing source or invalid alias prevents publishing a partial snapshot. Identical
bytes associated with different company/year metadata fail closed; identical
bytes with matching metadata create an explicit canonical duplicate link.

## Verification

Locally on Windows (after inspecting branch/worktree status and selecting an
isolated checkout), with the existing project virtual environment:

```powershell
$env:PYTHONPATH = "$PWD;$PWD\src"
& "C:\AI Projects\Nexus AI\.venv\Scripts\python.exe" -m pytest -q `
  tests/documents/test_collection_preflight.py `
  tests/documents/test_collection_extraction.py `
  tests/retrieval/test_company_year_metadata.py `
  tests/retrieval/test_collection_registration.py `
  tests/retrieval/test_service.py
```

Do not run the real-PDF or Ollama pilot for this acceptance gate.

## Known remaining work

- Catalog is in-memory only. Durable transactional metadata persistence and
  collection indexing need integration with the separate Work branch.
- Existing HTTP request schemas do not expose authorized collection filters.
  Do not infer workspace scope from untrusted HTTP input.
- Existing `RetrievalService` remains able to run unfiltered retrieval when
  the caller chooses not to pass a collection filter. Applications requiring
  company isolation must enforce filtering at the authorized request adapter.
- No claim of real Arabic financial-table accuracy, OCR coverage, or 150-file
  end-to-end retrieval performance is made by this slice.
- Review and test the separate durable-indexing branch before any integration
  into `main`.
