# Phase 4 window retrieval and benchmark readiness

This work is a **reconstructed implementation** on baseline
`4076077335c82bcac1140ee712c443fde1d99233`. It is not byte-identical to the
previous handoff patch. The prior patch and its ZIP were unavailable in this
session, so this document records the recovered design and verification for
the replacement.

## What is implemented

- Dev and holdout are validated as separate releases. Pair validation checks
  document identity, source identity, normalized document and chunk content,
  question IDs, and normalized query text. Each split must independently cover
  AR→AR, EN→EN, AR→EN, and EN→AR.
- Human review exports contain blank judgment fields. Imports remain submitted
  until two independent matching reviews or an independent adjudicator accepts
  the result. The tools do not create human judgments.
- Local retrieval remains opt-in. Raw BM25, Arabic-normalized BM25, a pinned
  local E5 adapter, and BM25/E5 reciprocal-rank fusion use the same fixture and
  relevance rules. Dense and hybrid paths enforce corpus and vector limits and
  reject invalid embeddings before ranking.
- The earlier context-expansion retriever still attaches bounded neighboring
  chunks to a BM25 anchor. The corrective addition separately implements
  actual windowed E5: deterministic overlapping 500-character text windows,
  semantic retrieval, max-cosine aggregation to original chunks/pages, and
  exact source and matched-subwindow offsets. Windowed E5 and weighted-RRF
  windowed hybrid are separate opt-in strategies; E5-only remains available.
- The standard provisional evaluator remains synthetic-only. A separate
  owner-review diagnostic requires an explicit `--allow-provisional` flag,
  accepts only a schema-v2 dev manifest and submitted `reviewer-a` records,
  requires complete answerability and chunk votes (and complete document votes
  when document-level judgments are supplied), and labels all output as not
  independently adjudicated. It does not create formal accepted labels or
  load holdout data.
- JSON and CSV outputs reject traversal and symlink/reparse-point components.
  JSON publication is staged and exclusive where the filesystem supports
  atomic hard-link publication. Windows path-based fallback still has a
  same-user directory replacement race; keep output directories owner-controlled.

## Reproduction commands

Run the offline focused suite from the repository root:

```sh
python -m unittest -v \
  tests.test_rag_prototype \
  tests.test_rag_benchmark_dataset \
  tests.test_rag_dense_retrieval \
  tests.test_rag_evaluation \
  tests.test_rag_window_retrieval \
  tests.test_rag_provisional_evaluation
```

Run the synthetic development check without weights or network access:

```sh
python scripts/run_provisional_rag_validation.py --fixture benchmarks/rag_eval_synthetic_dev_v2.json -k 3
```

For a real Windows evaluation, keep real fixtures and outputs outside Git unless
they are explicitly approved for publication. Freeze the development-selected
strategy before opening a protected holdout:

```powershell
.\scripts\run_real_rag_validation.ps1 -Fixture C:\private\nexus\dev.json -Split dev -K 5 -JsonOut local_data\rag-evaluation\dev.json
.\scripts\run_real_rag_validation.ps1 -Fixture C:\private\nexus\holdout.json -Split holdout -AllowHoldout -K 5
```

The formal PowerShell runner refuses a holdout path inside the repository tree and
requires `-AllowHoldout`. Keep `-JsonOut` repo-relative and place it under an
ignored directory such as `local_data/`. E5 is optional and requires the pinned
model weights to be cached locally. Ordinary unit tests never download or
initialize E5.

Run the distinct provisional comparison on the owner's Windows-local dev data
with already cached pinned E5 weights (it never downloads weights):

```powershell
.\scripts\run_provisional_owner_review_diagnostic.ps1 -AllowProvisional
```

The command compares original raw BM25, original full-chunk E5, actual
windowed E5, and windowed hybrid at K=3. It writes an exclusive JSON report to
LocalAppData. Use a new `-Output` path for a later run because existing reports
are not overwritten.

## Interpretation limits

The checked-in fixtures are synthetic. Their results test code paths and
expected mechanics only; they do not estimate retrieval quality on Nexus AI
documents. The private Windows dev manifest and cached E5 runtime were not
available in this Linux session, so the owner-review diagnostic and live E5
measurements are **NOT RUN** here. The diagnostic can produce provisional
results only; those do not satisfy the formal acceptance gate. Keep Phase 3's
quality gate pending until its documented owner acceptance evidence is
complete. This work does not enable production RAG.

## Verification recorded in this session

- Focused RAG suite after correction: **115 tests run, passed; 2 Windows
  junction-specific tests skipped** on Linux.
- `python -m compileall -q experiments/rag_prototype scripts/run_provisional_owner_review_diagnostic.py`: **PASS**.
- Fake-encoder CLI comparison and provisional review safeguards: **PASS**.
  No actual E5 weights or private owner dataset were loaded.
- Full repository `unittest` discovery with `PYTHONPATH=src`: **124 tests
  executed, 9 import errors, 2 skips**. The import errors are environment
  blockers because SQLAlchemy, Ollama, and LangChain Core are unavailable.
- Windows PowerShell execution and live E5 inference: **NOT RUN** in this Linux
  environment. No model was downloaded.
