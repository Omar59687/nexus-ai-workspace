# Phase 4 Synthetic Workload Protocol

This tool exercises corpus-scale indexing and evaluation plumbing with generated
documents. It is not a substitute for the private bilingual development set,
independent human relevance judgments, a protected holdout, or production-like
hardware measurements.

## Reproducible commands

Run the default workload (50 documents, 4 chunks per document, 32 questions):

```powershell
$env:PYTHONPATH = "src"
python -m experiments.rag_prototype.workload --seed 17 --k 3 --json-out workload-report.json
```

Exercise a larger collection and version replacement scenarios (150 documents,
4 chunks each, 128 questions, with 10 documents updated before a full index
rebuild):

```powershell
$env:PYTHONPATH = "src"
python -m experiments.rag_prototype.workload --documents 150 --chunks-per-document 4 --questions 128 --updates 10 --seed 17 --k 3 --json-out workload-150-report.json
```

The report separates fixture preparation, index-build time, query latency, and
Python traced allocation peak. Query rankings and metrics are deterministic for
the same seed and inputs; latency and memory measurements vary by runtime and
host. `tracemalloc` excludes native allocations and is not process RSS.

## What the workload covers

- A single synthetic `dev` split with explicit document, version, chunk, and
  source-span identities.
- All four language-direction labels: AR→AR, EN→EN, AR→EN, and EN→AR.
- Single-document, multi-document, and no-answer questions.
- Version replacement with old chunk IDs removed and query judgments remapped.
- Raw and Arabic-normalized BM25 indexing and retrieval.
- Indexing throughput, per-query latency, and source-span/hash integrity checks.

Cross-language queries and evidence share ASCII item identifiers. This is
intentional for deterministic load testing; it does not measure multilingual
semantic retrieval. No relevance labels are human-reviewed. A citation integrity
pass verifies that returned identities and offsets map to generated source text;
it does not establish that the retrieved passage answers the question.

## Limits and acceptance boundary

The default workload stays within 50–150 documents and up to 1000 questions.
Each generated document has 1–20 chunks. This harness rebuilds in-memory BM25
indexes after applying synthetic updates; it does not measure PostgreSQL
transactions, incremental indexing, PDF parsing, E5 model latency, process RSS,
or production throughput. Those checks require the target deployment
environment and actual reviewed documents. Do not tune on a protected holdout.
