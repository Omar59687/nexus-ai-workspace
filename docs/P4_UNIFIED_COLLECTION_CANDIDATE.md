# Phase 4 unified collection integration candidate

**Status:** candidate only; unified tests and real PostgreSQL acceptance are pending.
No migration or hosted writes. No PR, main merge, or LLM integration.

## Combined components

- Source-first collection intake, extraction, deterministic chunking
- Model-free source and chunk persistence (PostgreSQL adapter + in-memory fake)
- Explicit company/year metadata linked to active source identity
- Fail-closed owner-approved manifest metadata registration
- Source citation filtering and metadata revision fencing
- **New** `CollectionLexicalRetriever`: deterministic BM25 ranking over the
  durable model-free collection with mandatory company or year selector

This lexical path uses existing `experiments.rag_prototype.tokenize`, without
embedding providers, model calls or vector generation. It ranks chunks from
the registered subset only, validates source-offset provenance and checks
source versions and catalog revision before returning. Scores are not relevance
probabilities and empty hits are **not** sufficient to establish no answer.
Financial amount/year/currency accuracy is not certified.

## Example use

```python
from nexus_ai.retrieval.collection_registration import register_indexed_manifest
from nexus_ai.retrieval.collection_lexical import CollectionLexicalRetriever

# Construct index_repository using the bounded in-memory implementation
# or injected approved PostgreSQL connection; workspace from trusted auth.
index_service.index(authorized_workspace_id, validated_manifest_entries)
register_indexed_manifest(
    catalog=metadata_catalog,
    repository=index_repository,
    workspace_id=authorized_workspace_id,
    collection_id="annual-reports",
    entries=validated_manifest_entries,
    companies={"mobily": ("Mobily", "موبايلي")},
)
retriever = CollectionLexicalRetriever(
    repository=index_repository, catalog=metadata_catalog,
    workspace_id=authorized_workspace_id,
    collection_id="annual-reports",
)
response = retriever.retrieve("revenue", company="Mobily", financial_year=2025)
```

## Focused test gate

```powershell
$env:PYTHONPATH = "$PWD;$PWD\src"
& "C:\AI Projects\Nexus AI\.venv\Scripts\python.exe" -m pytest -q `
 tests/documents/test_collection_preflight.py `
 tests/documents/test_collection_extraction.py `
 tests/documents/test_collection_index.py `
 tests/retrieval/test_company_year_metadata.py `
 tests/retrieval/test_collection_registration.py `
 tests/retrieval/test_collection_lexical.py
```

Tests must pass on the unified branch before any other promotion. Durable
PostgreSQL requires an approved reversible migration, testing in a disposable
database and documented source-text privacy/retention policy.

Do not present the combined implementation as production-ready 150-file RAG.
A reviewer must independently label real PDF financial-source evidence and
measure retrieval coverage, missing-text handling, Arabic table integrity,
cross-company/year isolation and unsupported-number rejection.
