# P4 Company and Financial-Year Metadata Contract

This slice adds a model-independent filter to `RetrievalService`. It uses exact
registered names and active source identities; it does not infer company or year
from filenames, document text, embeddings, or an LLM.

## Current implementation

`CompanyYearMetadataCatalog` is a bounded in-memory reference catalog. A
collection snapshot is scoped by `(workspace_id, collection_id)`, has a stable
revision digest, and contains:

- A stable lowercase ASCII company ID and explicit display-name aliases. Add
  both Arabic and English names where both should resolve to one company.
- For each document: workspace, collection, document ID, immutable source
  version ID, normalized workspace-relative source path, source SHA-256,
  company ID, and financial year.
- For exact duplicate file content: exactly one canonical document and an
  explicit `duplicate_of_document_id` on each duplicate. Duplicate content
  cannot silently collapse distinct document identities.

The catalog rejects duplicate document IDs and case-insensitive paths,
ambiguous aliases, unsupported years, unknown company IDs, unsafe paths, and
collections larger than 150 documents. Replacing a collection creates a new
revision when any metadata or source identity changes. Re-register a full
snapshot after changing a document version or its company/year assignment.

## Retrieval call

```python
from nexus_ai.retrieval.company_metadata import (
    CompanyYearDocument,
    CompanyYearFilter,
    CompanyYearMetadataCatalog,
)
from nexus_ai.retrieval.service import RetrievalService

catalog = CompanyYearMetadataCatalog()
catalog.replace_collection(
    workspace_id=authorized_workspace_id,
    collection_id="annual-reports-2025",
    companies={
        "mobily": ("Mobily", "شركة اتحاد اتصالات موبايلي"),
        "acme": ("Acme Holdings", "أكمي القابضة"),
    },
    documents=metadata_rows,  # construct from trusted manifest + ingestion results
)
retrieval = RetrievalService(
    repository=document_index,
    embedder=embedder,
    company_metadata=catalog,
)
response = retrieval.retrieve(
    "revenue in the annual report",
    workspace_id=authorized_workspace_id,
    strategy="bm25_raw",  # or the existing windowed_e5 strategy
    company_year_filter=CompanyYearFilter(
        collection_id="annual-reports-2025",
        company="شركة اتحاد اتصالات موبايلي",  # exact normalized alias or company ID
        financial_year=2025,
    ),
)
```

The caller must derive `workspace_id` from its trusted authorization context,
never from an untrusted request field. The catalog verifies every declared
member against the repository's active document ID, version, path, and digest
before filtering. A missing catalog, stale or missing member, unknown alias, or
workspace mismatch raises an error instead of falling back to unfiltered
retrieval. Selected identities are checked again during retrieval. Result
citations are produced and validated by the existing retrieval service.

## Integration work for the primary branch

1. Copy the metadata module and retrieval-service changes without changing the
   protected collection preflight/extraction implementation.
2. Build metadata rows only after ingestion has returned a document ID and the
   repository can provide the active version and digest. Join the trusted
   manifest path to that indexed identity exactly; reject missing or ambiguous
   joins. Never derive company/year from model output.
3. Configure one catalog per application lifecycle and inject it into
   `RetrievalService`. Expose optional `collection_id`, `company`, and
   `financial_year` fields only through an authorized request adapter; retain
   `AuthorizedWorkspaceContext.workspace_id` as the scope.
4. Refresh the complete collection snapshot after source replacement, document
   deletion, or metadata reassignment. Until refresh completes, retrieval
   intentionally fails closed.
5. Before production use, implement a durable transactional catalog with
   workspace-scoped uniqueness and audit history, then test it against the
   same contract. This branch adds no database schema or migration; the current
   in-memory catalog does not survive process restart and is not production
   persistence.

## Scope and limitations

Company aliases use Unicode NFKC, case-folding, and whitespace normalization,
then exact matching. There is no fuzzy matching, transliteration, automatic
entity resolution, financial-year inference, or LLM involvement. Alias quality
must be reviewed by the collection owner. Filtered retrieval validates the
whole registered collection and is intentionally bounded to 150 documents.
