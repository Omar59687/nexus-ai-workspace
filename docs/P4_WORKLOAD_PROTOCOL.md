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

## Interpretation of no-answer false positives

The two BM25 baselines are *rankers*, not calibrated evidence-relevance or
abstention classifiers. They return top-k chunks even when a synthetic query's
identifier is absent from every document. Thus the reported
`no_answer_false_positives=10` for each strategy means 10 unanswerable questions
had non-empty top-k results. It does **not** prove the answering service would
hallucinate. Nor does `answerable_hit@k=1.0` prove real multilingual retrieval:
the fixture deliberately shares exact ASCII item identifiers between languages.

Do not retrofit a score cutoff to this benchmark and declare the problem fixed:
a threshold needs independent development calibration and holdout validation.
For actual PDFs, separately review whether retrieved pages support the answer,
and verify that the generator abstains on unsupported questions.

## Real single-PDF pilot (separate from the synthetic workload)

The new `scripts/run_real_pdf_pilot.py` opt-in runner processes exactly one
explicitly selected, trusted local text-layer PDF into an in-memory index. It
uses the existing Windows bounded PDF parser, cached E5 and loopback-only Ollama.
It neither crawls directories nor modifies PostgreSQL. The owner should put the
selected PDF outside Git and use the cached E5 virtual environment, with the
repository root, src, and existing main virtualenv dependencies on PYTHONPATH.
For example, using their own local paths:

```powershell
$env:OLLAMA_MODEL = 'gemma3:4b'
$env:PYTHONPATH = "$PWD;$PWD\src;C:\AI Projects\Nexus AI\.venv\Lib\site-packages"
$env:HF_HOME = Join-Path $env:LOCALAPPDATA 'NexusAI\huggingface'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
& (Join-Path $env:LOCALAPPDATA 'NexusAI\rag-e5-venv\Scripts\python.exe') scripts/run_real_pdf_pilot.py --run-live --pdf 'C:\private\trusted-report.pdf' --question 'What was revenue in 2025?' --report (Join-Path $env:LOCALAPPDATA 'NexusAI\reports\real-pdf-pilot.json')
```

The output includes source hash, extraction counts, page references, answer and
citation metadata, but makes no claim of financial correctness. Review amounts,
year, reporting units, comparative columns, and source pages manually. Scanned
PDFs may fail because OCR is not provided; tables may flatten incorrectly.
A Windows Job Object is **not** a hostile-PDF filesystem/network sandbox.
