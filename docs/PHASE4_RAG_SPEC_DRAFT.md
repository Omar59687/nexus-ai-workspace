# Phase 4 Production-Oriented RAG — First Slice Specification (Draft)

**Status:** Proposal only. Phase 4 production implementation is not authorized until Phase 3 formally passes its quality gate and the owner approves Phase 4. No code, dependency, extension, or migration is introduced by this specification.

## Goal

Deliver a local, reproducible document-to-evidence retrieval slice that answers a query with source-grounded excerpts and stable citations. This slice proves ingestion, provenance, chunking, local embedding, retrieval, and evaluation before an answer-generation workflow is added.

## First vertical slice boundary

**Input:** one PDF, DOCX, or UTF-8 text file under an explicitly selected local workspace root.

**Output:** extracted document metadata, deterministic chunks, local embeddings, ranked retrieval results, and citations containing document identity, page/section where available, chunk ID, and exact source text. The first slice does not summarize, generate an answer, crawl folders automatically, implement UI/auth, or claim factual accuracy.

## Proposed flow

1. Validate the source path against an explicit configured root; reject symlinks escaping the root and unsupported/oversized inputs.
2. Extract text and structure. Keep page number, heading path, paragraph/table boundaries, and extraction warnings as provenance.
3. Normalize only for retrieval; preserve source text byte-for-byte or as faithfully as extractor output allows for citations.
4. Chunk along page/heading/paragraph/table boundaries with bounded token/character size and documented overlap. Avoid splitting table rows where practical.
5. Compute document content SHA-256 and a stable chunk ID from canonical document identity, content digest, extractor/chunker version, ordinal, and chunk text digest. Re-indexing unchanged content must produce the same IDs.
6. Generate embeddings locally behind an `EmbeddingProvider` protocol. Record provider/model/version/dimensions and normalization settings with each index run.
7. Store document versions, chunks, provenance, and vectors in PostgreSQL. Use pgvector only after checking the installed server image/extension and obtaining owner approval for its migration.
8. Retrieve initial top-k candidates using exact vector distance as a baseline. Add lexical/hybrid retrieval as a separate measured method, not an unverified assumption.
9. Return ranked chunks with stable citations. No LLM-generated claims are included in this slice.
10. Evaluate against a frozen bilingual dataset containing answerable and unanswerable queries, relevant chunk IDs, language, and expected source spans.

## Proposed contracts

```text
ingest_document(path, *, root, extractor, chunker, embedder, repository)
    -> IngestionResult(document_id, version_id, chunk_count, warnings)

retrieve(query, *, filters, top_k, embedder, repository)
    -> list[RetrievedChunk(chunk_id, document_id, score, text, citation)]
```

The first slice may keep orchestration in one application service. Do not add LangGraph or a job queue until measured workloads require them.

## Data and provenance requirements

- Document identity and version identity are distinct; changed bytes create a new version.
- Chunk identity is deterministic within recorded extractor/chunker versions.
- Persist original filename, canonical relative path, MIME/type, content digest, extraction timestamp, extractor/version, language detection result/confidence if available, page/heading locators, and warnings.
- Do not persist absolute paths outside the approved workspace root.
- Re-ingest of the same source digest and pipeline versions is idempotent.
- Failed extraction/index runs are recorded as failures and cannot replace a previous successful version.
- Citation text must come from stored extracted source, not generated paraphrase.

## Arabic and English retrieval

- Treat language as metadata, not a hard filter by default.
- Establish exact vector search as the quality baseline and preserve separate evaluation slices for Arabic, English, and cross-language queries.
- Compare at least one multilingual local embedding model and one alternative only after recording machine resources and license/model-card constraints.
- Add lexical retrieval with language-aware normalization, Arabic orthographic variants, and controlled query expansion only as separately switchable experiments.
- Evaluate hybrid fusion against each parent retriever; keep the simpler method if fusion does not reliably improve recall and ranking quality.
- Include OCR-noisy text, mixed-language documents, numeric identifiers, and no-answer cases in the frozen evaluation set.

## PostgreSQL and retrieval decision

The project already uses PostgreSQL, making pgvector a plausible option, not an approved selection. Begin with exact vector search for a transparent quality baseline. Benchmark HNSW and IVFFlat only after the corpus and latency targets are defined. PostgreSQL full-text search can support lexical candidates, but the built-in text-search configurations and dictionaries must be assessed for Arabic; do not assume English stemming/tokenization provides Arabic quality. A dedicated lexical representation may be needed.

No extension install, schema migration, or index choice is authorized by this proposal. Resolve TQ-14 and inspect the target PostgreSQL image before writing migrations.

## Evaluation and acceptance criteria

Freeze a dataset before tuning. Record dataset version, document/chunk inventory hash, embedding model/version, machine, runtime, database version, and query settings.

- Retrieval: Recall@5/10, MRR@10, nDCG@10, and per-language/cross-language breakdown.
- Evidence: citation chunk ID validity, source-span correctness, and duplicate/near-duplicate rate.
- No-answer safety: abstention quality measured separately from retrieval recall.
- Operations: ingestion success/failure rates, re-ingest idempotency, latency p50/p95, peak memory, and index/storage footprint.
- Regression: changed chunk IDs, ranks, or metrics require a versioned evaluation report; no benchmark-label edits to improve results.

Acceptance requires deterministic re-ingestion tests, path-safety tests, provenance/citation tests, bilingual retrieval evaluations, unanswerable queries, and a reviewable local resource report. Numerical thresholds must be approved before performance tuning.

## Candidate file ownership for implementation

| Area | Candidate files | Owner boundary |
| --- | --- | --- |
| Source extraction and metadata | `src/nexus_ai/documents/extractors.py`, `tests/documents/test_extractors.py` | Extractor protocol and format-specific adapters |
| Chunking and IDs | `src/nexus_ai/documents/chunking.py`, `tests/documents/test_chunking.py` | Deterministic segmentation and provenance spans |
| Embedding interface | `src/nexus_ai/retrieval/embeddings.py`, tests | Local provider protocol only; no default model until reviewed |
| Persistence | new document/chunk models and migrations, separately reviewed | No pgvector migration before TQ-14 and owner approval |
| Retrieval and citations | `src/nexus_ai/retrieval/service.py`, tests | Deterministic top-k result and source citation contract |
| Evaluation | `benchmarks/rag/`, `scripts/evaluate_rag.py`, tests | Frozen dataset; scoring separate from production code |

These paths are proposals and may be revised after Phase 4 is authorized.

## Primary references

- pgvector project documentation: <https://github.com/pgvector/pgvector> (exact search, HNSW/IVFFlat options, iterative scans; verify against the chosen release and server image).
- PostgreSQL full-text search documentation: <https://www.postgresql.org/docs/current/textsearch.html> and <https://www.postgresql.org/docs/current/textsearch-dictionaries.html> (language configurations/dictionaries and lexical search behavior).
- PostgreSQL text-search table/index guidance: <https://www.postgresql.org/docs/current/textsearch-tables.html>.

These references inform the proposal; they do not resolve the project's vector-store, embedding-model, or Arabic lexical-search decisions.
