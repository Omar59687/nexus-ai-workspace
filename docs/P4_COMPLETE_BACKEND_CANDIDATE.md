# Phase 4 Complete Backend Candidate — Verification Record

**Status:** isolated experimental candidate; not production-ready.
**Parent:** `5083df9db1b7baf468251c85a1d462dfbc4bf0af` on
`feature/p4-backend-integration-a`.
**Phase 3 Quality Gate:** remains **BLOCKED**. No checkpoint or acceptance gate
is changed by this candidate.

## Candidate scope

The candidate adds bounded explicit-file ingestion, provenance-preserving
chunking and E5 windows, a fake-testable cached E5 adapter, in-memory atomic
index generations, an inert PostgreSQL DB-API persistence proposal, dense and
two-pass BM25 retrieval, citation-checked structured answering, typed backend
contracts, and a deterministic synthetic workload. It does not wire these
services into `main.py`, expose HTTP routes, change the default LLM, or apply a
database schema.

The PostgreSQL model stores document source versions separately from processing
identity and embedding index generations. Activating a new generation updates
the active pointer transactionally. Retrieval iterates one active document at
a time; BM25 is calculated in bounded passes and fails closed if a document
generation changes between passes. These contracts have fake DB-API tests but
have not been exercised against PostgreSQL.

Answering consumes the already retrieved citation tuple, permits citations
only from that tuple, supports explicit abstention, and rejects some unsupported
literal numeric claims. This is not semantic entailment verification. PDF
parsing runs in a bounded subprocess on POSIX, but the process retains the
caller's OS permissions and is not a full sandbox. PDF intake fails closed on
Windows. The service-layer workspace context is not authentication; there are
no public routes.

## Verification performed in this environment

| Check | Result |
| --- | --- |
| Focused document, retrieval, persistence, and RAG tests | **PASS** — 185 passed, 2 skipped, 70 subtests passed |
| Python compilation for candidate and RAG modules | **PASS** — `compileall -q` |
| `pyproject.toml` parse | **PASS** |
| Synthetic workload smoke run | **PASS** — 4 synthetic documents, 4 chunks, 8 questions, seed 17; raw and Arabic-normalized BM25 each had 1.000 synthetic answerable hit@3, 20/20 citation spans valid, and 1 no-answer false positive |
| Full repository pytest collection | **BLOCKED** — 9 modules fail collection because this environment lacks `sqlalchemy`, `ollama`, and `langchain_core` |
| Live PostgreSQL / Alembic | **NOT RUN** — no disposable PostgreSQL instance; DDL is proposal only |
| Live E5 / Ollama and cached model weights | **NOT RUN** — no provider runtime or verified cache |
| PDF parser integration | **NOT RUN** — optional `pypdf` is not installed |
| Windows execution / PDF Job Objects | **NOT RUN** — this runtime is Linux; Windows PDF remains fail-closed |
| Private owner corpus or human labels | **NOT RUN** — no private data or adjudication evidence used |

The synthetic workload is plumbing and timing evidence only. Its shared item
keys do not measure Arabic/English semantic retrieval and must not be cited as
real-corpus accuracy.

## Independent review

The independent security pass confirmed the newline/heading workload bounds,
two-pass BM25 generation consistency check, and current re-index idempotency
contract. It identified these remaining issues/limits:

- The idempotency cache is bounded but process-local and volatile; a durable job
  store is required before public routes or multi-process workers.
- PDF resource limits do not isolate filesystem/network privileges. Keep PDF
  processing unavailable to untrusted callers until a full platform sandbox is
  implemented and reviewed.
- Numeric-token checks do not establish that general semantic claims follow
  from citations.
- PostgreSQL compatibility and rollback require disposable-database tests.

No independent reviewer edited the implementation. Their review did not
constitute a Phase 3 or Phase 4 acceptance decision.

## Reproduction commands

From the repository root in PowerShell:

```powershell
$env:PYTHONPATH = "src"
python -m pytest -q tests/documents tests/retrieval tests/persistence tests/test_rag_prototype.py tests/test_rag_benchmark_dataset.py tests/test_rag_dense_retrieval.py tests/test_rag_evaluation.py tests/test_rag_owner_review_diagnostic.py tests/test_rag_provisional_evaluation.py tests/test_rag_window_retrieval.py tests/test_rag_workload.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m compileall -q src/nexus_ai/documents src/nexus_ai/retrieval experiments/rag_prototype tests/documents tests/retrieval tests/persistence tests/test_rag_workload.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m experiments.rag_prototype.workload --documents 4 --chunks-per-document 1 --questions 8 --updates 0 --seed 17 --k 3
```

Run the full test suite, `pip check`, and `alembic check` in the configured
Windows environment before treating repository regression as verified. Run
live PostgreSQL, cached E5/Ollama, PDF, and Windows file-isolation checks only
with the appropriate disposable environment. Never use the protected holdout
for tuning.

## Ordered blockers before acceptance or activation

1. Close the documented Phase 3 gate with owner-approved decisions, full
   Windows/PostgreSQL/Alembic evidence, cross-phase and live Ollama checks, and
   an explicit owner gate decision.
2. Obtain independent review of the final candidate diff and resolve all
   critical/high findings.
3. Add and review a migration; test transactional activation, concurrent reads,
   rollback, and bounded queries against disposable PostgreSQL.
4. Implement trusted authentication and workspace authorization, plus durable
   idempotency and background job lifecycle, before introducing routes.
5. Provide a full PDF sandbox for supported operating systems, then verify
   parser/resource behavior on Windows and POSIX.
6. Verify the pinned E5 model from cache and the existing local Ollama structured
   adapter without changing the configured default LLM.
7. Obtain real, independently reviewed bilingual judgments with development
   and protected holdout separation, then evaluate retrieval, abstention,
   semantic answers, citations, latency, and resource use against
   owner-approved criteria.

Until these conditions are met, this code remains an isolated engineering
candidate and must not be presented as accepted or production-ready.
