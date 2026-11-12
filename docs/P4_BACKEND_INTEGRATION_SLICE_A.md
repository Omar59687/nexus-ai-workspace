# Phase 4 Backend Integration — Experimental Candidate

This candidate adds backend engineering for review. It does not close the
Phase 3 Quality Gate, enable a production route, or approve Phase 4.

## Current implementation

- Explicit-root ingestion accepts one workspace-relative `.txt`, `.md`, or
  `.pdf` file at a time. It validates paths, rejects link/reparse-point
  components where detectable, checks opened-file identity, and enforces the
  byte cap while streaming.
- Text and Markdown extraction are local. PDF extraction is assigned to a
  bounded child process on POSIX. That worker is not a full OS sandbox and
  inherits the caller's filesystem/network authority. It fails closed on
  Windows until a Job Object or equivalent isolation implementation is tested.
- Stable chunk and window identities preserve source hashes, version and
  processing identities, model revision, preprocessing, and source offsets.
  Limits bound pages, lines, headings, chunks, windows, vector coordinates,
  batches, reads, and retrieval scans.
- The in-memory repository atomically swaps a complete document generation.
  A PostgreSQL DB-API adapter and candidate DDL now model the same generation
  boundary and bounded reads. The DDL is inert: no migration was added or
  applied, and no live PostgreSQL compatibility has been demonstrated.
- Retrieval offers opt-in raw BM25 and cached-model windowed E5. It checks
  embedding identity, streams document indexes, computes BM25 in two bounded
  passes, detects active-generation changes between passes, and validates
  returned citation provenance before producing evidence.
- The answer service accepts evidence from one prior retrieval call, returns
  only citations present in that evidence, supports abstention and conflict
  prompts, and rejects unsupported literal numbers. This does not prove
  semantic entailment or broader factual correctness.
- Typed service contracts cover registration, re-indexing, bounded document
  listing, status, deletion, search, evidence lookup, and grounded answers.
  They are not FastAPI routes or authentication. The workspace context must be
  supplied by a future trusted authorization layer; its current idempotency
  cache is bounded and process-local.
- A synthetic workload tool records fixture/index/query timing, traced Python
  allocations, citation integrity, and four language-direction labels. Shared
  synthetic identifiers exercise plumbing only; the measurements do not
  establish multilingual retrieval quality or production throughput.

## Verification and limitations

Focused candidate tests use fake encoders and in-memory/fake DB-API connections.
They do not download model weights. A successful fake-based test is not a live
PostgreSQL, E5, Ollama, pypdf, Windows, or owner-corpus result. The full suite
also requires base application dependencies absent from the isolated runner.

Before any deployment consideration, require disposable PostgreSQL integration
and migration review, a real authentication/authorization boundary, durable
idempotency/job storage, a full PDF sandbox for each supported OS, Windows
validation, live cached E5/Ollama tests, approved real-corpus relevance labels,
and independent semantic-answer evaluation. Keep the candidate disconnected
from application routes until the Phase 3 gate is formally closed.
