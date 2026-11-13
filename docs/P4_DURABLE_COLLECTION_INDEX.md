# Phase 4 — Durable Model-Independent Collection Index

**Status:** isolated implementation candidate on `feature/p4-durable-collection-index`. It has not been connected to an application route, applied to a database, or accepted for deployment.

## Contract

`CollectionIndexService` accepts an approved root, a workspace identity, and an explicit document manifest. It reads only manifest-listed `.txt`, `.md`, or `.pdf` files, using the existing manifest validation and `read_approved_file` safety boundary. Per-file and aggregate byte limits, PDF page/text limits, and per-document chunk limits are bounded by the established collection ceilings.

The service extracts page text through the existing local extractors, requires the existing isolated PDF worker for PDFs, chunks with `SourceAwareChunker`, and stores:

- workspace-scoped document ID derived from normalized relative path;
- source version ID derived from source-byte SHA-256;
- processing ID derived from extractor, format, offsets-reliability, and chunker fingerprint;
- extracted page text and parser warnings;
- chunk text, deterministic chunk IDs, source path/hash, extractor and chunker provenance, heading path, page, line and character offsets.

No embeddings, model calls, company/year retrieval filtering, vector storage, or application API wiring are part of this milestone. Same bytes at two different paths remain two distinct document identities so citation sources do not collapse. Duplicate paths in one manifest are rejected by existing manifest validation.

## Lifecycle and failure behavior

- Re-ingesting the same path, source bytes, extractor identity, and chunker fingerprint produces the same version and processing identities. The repository compares a canonical payload digest and treats an exact match as unchanged; a same-identity/different-payload attempt fails closed.
- A changed source, extractor, or chunker generation is prepared first. PostgreSQL inserts version metadata and all chunks, switches the active pointer, and prunes the previous generation in one transaction. A failed transaction leaves the prior active generation intact.
- The PostgreSQL candidate binds one relative source path to one workspace/document identity with unique and composite foreign-key constraints. Activation first creates the identity row, then locks it, so first-time concurrent writes are serialized as well as replacements. A document ID cannot be rebound to a different path.
- Each generation stores a SHA-256 digest of its canonical source, chunk, window, and vector payload. Replaying the same generation identity with different payload bytes fails closed instead of silently reusing stale windows. Window vectors are constrained to one-dimensional, non-empty arrays of at most 4096 values.
- Each source-version row also stores a digest of the extracted document record. A retry cannot silently associate different extracted pages or warnings with an already-used source-version/processing identity, even if it requests a new embedding generation.
- The adapter rejects DB-API connections that expose `autocommit=True`; transaction rollback guarantees depend on a fresh connection with autocommit disabled.
- Each manifest item is handled in an independent repository transaction. An extraction or persistence failure produces a generic per-item failure result; processing continues for later entries. Failure telemetry stores only workspace, relative source path, and exception class, never exception messages or source text.
- The candidate PostgreSQL schema and adapter are separate from the application task database. `COLLECTION_SCHEMA_DDL` is inert documentation/code data and is never run by import or repository construction. No Alembic migration was added or applied, and no production database was contacted.
- Deletion removes the active document and dependent text/chunks. The candidate currently retains only the active source/processing generation; it is not an archival document-version store.

## Interfaces and files

- `src/nexus_ai/documents/collection_index.py` — bounded explicit-file orchestration.
- `src/nexus_ai/documents/collection_types.py` — model-independent records, limits, and repository protocol.
- `src/nexus_ai/retrieval/collection_repository.py` — copy-on-write in-memory reference and injected DB-API PostgreSQL adapter with candidate DDL.
- `tests/documents/test_collection_index.py` — synthetic extraction and fake DB-API lifecycle tests.

## Focused verification

From the repository root with the development environment and `PYTHONPATH=src`:

```sh
python -m pytest -q \
  tests/documents/test_collection_preflight.py \
  tests/documents/test_collection_extraction.py \
  tests/documents/test_collection_index.py
```

The new DB tests use fake DB-API connections. They verify parameter binding, that chunk rows precede active-pointer replacement, idempotency, and rollback with the old pointer preserved. They do not establish PostgreSQL syntax/runtime compatibility.

## Remaining deployment requirements

1. Independently review the DDL and convert it into an explicit reversible Alembic migration before any deployment. No migration is appropriate yet because this schema remains a proposal and no database is approved for applying it.
2. Apply and test that migration in a newly created disposable PostgreSQL database; verify FK behavior, row-lock and concurrent-first-insert behavior, transaction rollback, JSONB serialization, count limits, and deletion cascades against the supported PostgreSQL version.
3. Define backup, retention, privacy, encryption, storage quotas, and deletion/restore policy for extracted text. The adapter stores full extracted source text and chunks.
4. Define trusted workspace authorization before any route or CLI exposes persistence. The `workspace_id` is only a scope key, not authentication.
5. Verify Windows and POSIX input behavior, including PDF worker limits, on the actual supported environments.
6. Reconcile this service with the separately owned company/year metadata and retrieval-filtering work before integration. This change does not edit that filtering implementation.
7. Keep Phase 3 and Phase 4 quality-gate decisions separate; passing these focused tests does not accept either gate.
