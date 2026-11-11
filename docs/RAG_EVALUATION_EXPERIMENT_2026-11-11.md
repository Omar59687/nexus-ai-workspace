# Phase 4 Retrieval Evaluation Experiment — 2026-11-11

**Status:** Experimental evidence only. This does not activate RAG in the application or pass the Phase 3 quality gate. The source baseline is `dbabc7e5c9f8fb7cd171057bf76a8bada14a1710` on `experiment/p4-rag-prototype`.

## What this adds

- `benchmarks/rag_eval_synthetic_v1.json`: an explicitly synthetic, versioned bilingual fixture with eight documents, eight explicit chunk IDs, eleven query IDs, graded labels, six development questions, and five held-out questions. Each split contains Arabic→Arabic, English→English, Arabic→English, and English→Arabic answerable cases plus one unanswerable case.
- `experiments/rag_prototype/evaluation.py`: strict fixture validation, stable report serialization, per-query-language/evidence-language/direction aggregation, diagnostic failure lists, provenance references, and separate no-answer false-positive/abstention counts.
- `scripts/run_rag_eval.py`: a repeatable CLI. It defaults to the development split, requires explicit holdout opt-in, and refuses to overwrite an existing JSON report unless `--overwrite` is passed.
- `tests/test_rag_evaluation.py`: deterministic, schema, leakage, malformed-label, holdout-guard, output-integrity, and failure-closed checks.

The fixture is not a corpus of real Nexus or financial documents. Its labels are complete for the small candidate pool and are validated before retrieval. Development and holdout use disjoint document IDs, paths, and exact content. Near-duplicate detection is not claimed.

## Reproduction

From the repository root, with Python 3.12:

```sh
python scripts/run_rag_eval.py --split dev -k 3 --json-out benchmarks/results/rag_eval_synthetic_dev_v1_k3.json
python -B -m unittest -v tests.test_rag_evaluation tests.test_rag_prototype
```

To evaluate a frozen candidate on holdout later, explicitly add `--split holdout --allow-holdout`. Do not tune using holdout results. The checked-in development report records fixture SHA-256 and the Python runtime; it has no timestamp or latency field, so identical fixture/config/runtime runs serialize identically.

## Development-split results

Measured in the isolated Linux scratch runtime with Python 3.12.14, `k=3`, four development documents/chunks, five answerable questions, and one unanswerable question (six queries total). No Ollama, PostgreSQL, embedding model, or external model was used.

| Strategy | Slice | n | Precision@3 | Recall@3 | MRR@3 | nDCG@3 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Raw BM25 | Arabic→Arabic | 2 | 0.1667 | 0.5000 | 0.5000 | 0.5000 |
| Raw BM25 | English→English | 1 | 0.3333 | 1.0000 | 1.0000 | 1.0000 |
| Raw BM25 | Arabic→English | 1 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| Raw BM25 | English→Arabic | 1 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| Raw BM25 | Overall answerable | 5 | 0.1333 | 0.4000 | 0.4000 | 0.4000 |
| Normalized BM25 | Arabic→Arabic | 2 | 0.3333 | 1.0000 | 1.0000 | 1.0000 |
| Normalized BM25 | English→English | 1 | 0.3333 | 1.0000 | 1.0000 | 1.0000 |
| Normalized BM25 | Arabic→English | 1 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| Normalized BM25 | English→Arabic | 1 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| Normalized BM25 | Overall answerable | 5 | 0.2000 | 0.6000 | 0.6000 | 0.6000 |

The Arabic normalization ablation retrieves one fixture spelling variant that raw BM25 misses. Both lexical strategies miss both cross-language questions. On the one unanswerable development query, both return no result: one abstention and zero false positives each. These values are hand-authored fixture behavior, not estimates of real-world quality and not evidence for an acceptance threshold.

## Failure cases and interpretation

- `q-dev-ar-en-revenue`: Arabic query against English evidence; neither lexical strategy returns the relevant chunk in its top 3.
- `q-dev-en-ar-branches`: English query against Arabic evidence; neither strategy returns the relevant chunk in its top 3.
- `q-dev-ar-ar-normalization`: raw BM25 returns no candidate; the existing symmetric Arabic normalization switch retrieves the labeled chunk.
- The normalized strategy still returns a wrong-language candidate for the two cross-language questions. This is recorded as a missed relevant result, not treated as success because a result exists.

The first data-backed retrieval conclusion is narrow: lexical-only retrieval is insufficient for the synthetic cross-language cases; the already-implemented Arabic normalization option helps this one orthographic fixture. That justifies a future pinned multilingual dense-retrieval comparison on an owner-approved project dataset. It does not justify adding a model, hybrid fusion, or reranker now. Research notes identify `intfloat/multilingual-e5-small` as a possible candidate; it was not downloaded, run, or benchmarked here. Test BM25 and dense parents independently before evaluating RRF, and keep Arabic normalization as an explicit ablation until real-data evidence supports a default.

## Review and verification limits

- Focused verification: `python3 -B -m unittest -v tests.test_rag_evaluation tests.test_rag_prototype` — 35 tests passed in the isolated scratch snapshot after the provenance-span correction.
- Compilation: `python3 -m compileall -q experiments/rag_prototype scripts/run_rag_eval.py tests/test_rag_evaluation.py` — passed.
- The repository-wide pytest suite was not run in this runtime: `pytest`, SQLAlchemy, Alembic, and LangChain packages are unavailable here, and the owner’s Windows checkout is not mounted. No package installation was attempted. The reported Windows regression totals remain owner-reported evidence, not a result of this run.
- PostgreSQL, Ollama, model memory, ingestion latency, retrieval latency, throughput, and RSS were not measured. The fixture is too small to serve as a meaningful performance workload.
- Independent review: APPROVE for the experimental slice. The reviewer confirmed the out-of-bounds provenance fix and noted limitations: direction coverage is checked across the fixture rather than separately per split; dev and holdout judgments share one file, so holdout is opt-in but not sealed; custom retriever tie-break metadata can be inaccurate; provenance omits `version_id`; and `overwrite=True` follows a caller-selected symlink path. These do not invalidate the synthetic experimental runner, but should be addressed before using a sealed benchmark or custom strategy reports.

## Security and reliability boundaries

The evaluator rejects duplicate IDs, dangling references, inconsistent language/split/source metadata, incomplete relevance judgments, cross-split reused paths, and exact duplicate document text across splits. It does not identify near-duplicate paraphrases or independently validate human relevance labels. Retrieved source text remains data; this slice does not invoke an LLM or tools.

The underlying prototype still has its documented filesystem TOCTOU limitation when another actor can mutate a parent directory during ingestion, caller-selected per-file/per-chunk bounds but no corpus-wide size cap, and caller-constructible provenance records. These are prototype limitations and require separate hardening before production ingestion.
