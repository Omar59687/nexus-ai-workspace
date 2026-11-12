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
- Window retrieval ranks the matching chunk as its anchor and attaches only
  bounded neighboring chunks from that same document version. Metrics score
  anchors only. Reports retain document version, source reference, chunk
  digest, offsets, and expanded-window provenance.
- Provisional evaluation only accepts synthetic dev fixtures. Protected
  holdout remains on the explicit real-evaluation path and requires a separate
  explicit opt-in.
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

The PowerShell runner refuses a holdout path inside the repository tree and
requires `-AllowHoldout`. Keep `-JsonOut` repo-relative and place it under an
ignored directory such as `local_data/`. E5 is optional and requires the pinned
model weights to be cached locally. Ordinary unit tests never download or
initialize E5.

## Interpretation limits

The checked-in fixtures are synthetic. Their results test code paths and
expected mechanics only; they do not estimate retrieval quality on Nexus AI
documents. No real corpus or human-reviewed relevance labels were supplied in
this run, so real retrieval quality and live E5 measurements remain **NOT
RUN**. Keep Phase 3's formal quality gate pending until its documented owner
acceptance evidence is complete. This work does not enable production RAG.

## Verification recorded in this session

- Focused RAG suite: **102 tests run; 100 passed; 2 Windows-junction cases
  skipped** on Linux.
- `python -m compileall -q experiments scripts tests`: **PASS**.
- Synthetic provisional CLI and standard dev CLI: **PASS**. Both used only the
  checked-in synthetic fixture.
- Full repository `unittest` discovery: **111 tests collected, 9 import errors,
  2 skips**. The errors are environment blockers: SQLAlchemy, Ollama, and
  LangChain Core are not installed in this runtime. The focused RAG suite does
  not depend on those packages.
- Windows PowerShell execution and live E5 inference: **NOT RUN** in this Linux
  environment. No model was downloaded.
