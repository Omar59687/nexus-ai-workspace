# Phase 4 Backend Integration — Slice A

Status: experimental backend integration. This slice does not close the Phase 3
Quality Gate and does not activate retrieval in the application.

## Scope

This slice adds an explicit-file ingestion and retrieval core behind replaceable
interfaces. It has no FastAPI route, no frontend integration, no database
migration, and no production activation. The in-memory index is volatile and
exists for deterministic integration work. PostgreSQL persistence remains a
separate future adapter.

## Data path

1. `DocumentIngestionService` accepts a workspace ID and one path relative to
   an explicitly approved root. It never crawls a directory.
2. The filesystem reader rejects traversal, unsupported suffixes, symlinks, and
   Windows reparse points where detectable. It opens a regular file and enforces
   the byte cap while reading, even if the file's reported size is inaccurate.
3. UTF-8 text and Markdown use built-in extractors. PDF support is optional and
   uses the replaceable extractor protocol. Extraction retains page references,
   warnings, parser identity, and whether offsets are reliable.
4. `SourceAwareChunker` makes stable overlapping chunks while retaining exact
   source offsets where the extractor guarantees them. Window generation makes
   smaller deterministic spans over those chunks for E5 indexing.
5. `E5EmbeddingProvider` wraps the existing pinned E5 adapter, requires cached
   local weights, validates vectors, and batches embedding calls. Ordinary tests
   inject a deterministic fake provider and never download weights.
6. The repository builds a complete candidate index before atomically swapping
   the active document version. Failed embedding or validation leaves the prior
   active version intact. Index content and failure history are bounded by
   experimental limits.
7. `RetrievalService` searches only the requested workspace's active versions.
   Windowed E5 is the default strategy in this isolated service; raw BM25 is an
   explicit opt-in. Results deduplicate to source chunks and include verifiable
   document, version, hash, page, chunk, and window provenance.

## Contracts and safety boundaries

- Ingestion input: workspace ID plus one relative `.txt`, `.md`, or `.pdf` path.
- Ingestion output: stable document/version IDs, SHA-256, chunk/window counts,
  activation/idempotency state, and extractor warnings.
- Retrieval input: workspace ID, non-empty query, bounded `top_k`, optional
  document/page filters, and an explicit supported strategy.
- Retrieval output: `ok` or `empty`, ranked evidence, score type, strategy, and
  exact citation text. A missing embedding runtime raises a distinct unavailable
  error; it is not reported as an empty result.
- Citation checks fail closed if the active version, chunk identity, exact text,
  page span, or matched-window provenance cannot be validated.
- Workspace scoping here is a data-layer filter, not authorization. A future
  authenticated caller must derive the workspace ID from its authorized
  principal rather than trusting an arbitrary request field.
- Ingestion treats document text as data. Prompt-injection defenses for any
  future answer-generation layer must be implemented and tested there too.
- PDF character limits are checked after extraction returns text. This does not
  provide parser CPU/RSS isolation; production PDF processing should use an
  appropriately sandboxed worker with time and memory limits.
- Windows reparse-point checks and before/after file identity checks reduce risk,
  but the standard-library fallback cannot eliminate every concurrent
  same-user filesystem replacement race. A handle-based Windows implementation
  is a future hardening option.
- All count and size defaults are experimental safeguards, not approved
  production capacity limits. The in-memory vector-coordinate cap is kept low
  because Python tuple-backed vectors carry high object overhead.

## Testing

`tests/documents/test_ingestion.py` and `tests/retrieval/test_service.py` use
temporary files and fake extractors/encoders. They cover UTF-8 and PDF behavior,
chunk provenance, traversal and symlink rejection, byte/page/window/vector
limits, idempotency, replacement rollback, deletion, citation validation,
workspace isolation, unavailable embeddings, and concurrent readers during
atomic version replacement. Existing Phase 4 retrieval tests remain separate.

## Not included

- PostgreSQL repository implementation or schema changes.
- FastAPI activation route, authentication/authorization middleware, or UI.
- Durable queueing, worker sandboxing, persistence, or production lifecycle.
- Production benchmark claims or Phase 3 acceptance evidence.

## Recommended next slice

Design the persistence adapter contract and authenticated application boundary
against the Phase 3 gate. Then implement a disposable PostgreSQL integration
slice with transactional version activation and workspace authorization tests.
Do not enable the route until those gates and the Phase 3 Quality Gate have
documented acceptance evidence.
