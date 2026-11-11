# Nexus AI RAG hardening and benchmark preparation

**Baseline:** `9d174a0dada7b4560676046546db8848ed4feee2` on `experiment/p4-rag-prototype`
**State:** experimental only; no commit, push, PR, or production activation
**Benchmark status:** synthetic fixtures exercised; no real labeled corpus available

## Changes

- Evaluation now requires a single explicit split per fixture and independent coverage of AR→AR, EN→EN, AR→EN, and EN→AR. The CLI defaults to development only; holdout use requires an explicit fixture and opt-in flag. A release-time pair check detects shared IDs, sources, normalized document text, and normalized chunk text.
- Rankings use declared strategy tie policies and custom retrievers retain their own metadata. Reports include per-query/evidence language and direction metrics, provenance including document version IDs and SHA-256 values, missed relevant IDs, answerable retrieval coverage, and no-answer false-positive/abstention results.
- Annotation tooling creates bounded unjudged corpus manifests; exports reviewable query/evidence pairs with source/version/content hashes; imports only under an assigned reviewer ID; and keeps votes submitted until independent agreement or a separate adjudicator resolution. Canonical dataset-release and evaluation-input seals prevent reusing adjudications after content changes.
- Corpus intake, JSON fixtures, annotation sheets, retrieval indexes, dense embeddings, and report output have explicit size/count bounds. Duplicate JSON keys are rejected. POSIX path operations use directory-relative no-follow opens. Report paths reject symlinks and Windows reparse points; no-overwrite creation is exclusive, and explicit overwrite uses a temporary file and replace.
- The optional local-only `intfloat/multilingual-e5-small` adapter pins revision `614241f622f53c4eeff9890bdc4f31cfecc418b3`, applies `query:` / `passage:` prefixes, limits passage batching and corpus size, and compares dense cosine with raw BM25 + reciprocal-rank fusion on the same chunk set. It is not enabled during ordinary tests and does not download weights. The model card requires those prefixes and documents a 512-token input limit; these general model-card properties do not establish performance on Nexus data. See the [E5 model card](https://huggingface.co/intfloat/multilingual-e5-small) and its [pinned revision](https://huggingface.co/intfloat/multilingual-e5-small/tree/614241f622f53c4eeff9890bdc4f31cfecc418b3).

## Verification

Focused command:

```text
python3 -B -m unittest -q tests.test_rag_dense_retrieval tests.test_rag_benchmark_dataset tests.test_rag_evaluation tests.test_rag_prototype
Ran 61 tests — OK
```

Compilation and CLI checks:

```text
python3 -m py_compile experiments/rag_prototype/*.py scripts/rag_dataset_tool.py scripts/run_rag_eval.py tests/test_rag_*.py — PASS
python3 -m compileall -q experiments/rag_prototype scripts/rag_dataset_tool.py scripts/run_rag_eval.py tests — PASS
python3 scripts/rag_dataset_tool.py --help — PASS
```

The environment contains a partial RAG snapshot rather than the full repository, and does not have the project dependency set (including pytest, SQLAlchemy/Alembic, LangChain, torch, or Transformers). The full 468-test regression suite, PostgreSQL/Alembic checks, Windows execution, and live E5 retrieval are **NOT RUN** here. The owner's 468 passing tests are prior owner-reported baseline results, not results of this change.

## Synthetic result snapshot

The two result files are reproducible examples only; their queries, documents, and labels are synthetic. They make no claim about real-world Nexus accuracy.

| Fixture (k=3) | Strategy | P@3 | R@3 | MRR@3 | nDCG@3 | No-answer false-positive rate |
|---|---|---:|---:|---:|---:|---:|
| Dev, 5 answerable + 1 no-answer | Arabic-normalized BM25 | 0.200 | 0.600 | 0.600 | 0.600 | 0/1 |
| Dev | Raw BM25 | 0.133 | 0.400 | 0.400 | 0.400 | 0/1 |
| Holdout sample, 4 answerable + 1 no-answer | Arabic-normalized BM25 | 0.167 | 0.500 | 0.500 | 0.500 | 0/1 |
| Holdout sample | Raw BM25 | 0.167 | 0.500 | 0.500 | 0.500 | 0/1 |

In this deliberately tiny fixture, Arabic normalization fixes one Arabic spelling variant. Both lexical strategies miss the two cross-language examples in each split. The single no-answer query per split is insufficient to estimate abstention quality. These observations are useful for checking diagnostics and designing the real corpus, not for selecting a production retriever.

An opt-in dev timing snapshot is also saved at `benchmarks/results/rag_eval_synthetic_dev_v2_k3_latency_20261111.json`. It was measured with Python 3.12.14 on Linux x86_64 (9 logical CPUs reported), on this six-query synthetic fixture: normalized BM25 indexing 0.000104 s and mean query 0.0226 ms; raw BM25 indexing 0.000142 s and mean query 0.0329 ms. These sub-millisecond values are host- and fixture-specific, include no load, and must not be interpreted as production latency. Dense model loading, embedding/indexing, and dense query latency are **NOT RUN**.

## Independent review

The independent code reviewer initially rejected the handoff because adjudication summaries were not bound to exact dataset content and Windows path operations could race with hostile path replacement. Both review findings were addressed for the release-seal flow; the reviewer re-reviewed and approved that scope. The reviewer also confirmed bounded E5 batches, candidate corpus caps, evidence hashes in review sheets, and identity assignment checks. Reviewer IDs are not authenticated by a CSV; the review organizer must verify reviewer identity outside this tool.

## Security and operating limitations

- On POSIX, ingestion and output use directory-handle-relative no-follow operations where supported. On Windows, the standard-library fallback rejects observed symlinks, junctions, and other detectable reparse points and checks file identity, but cannot eliminate hostile concurrent path-component replacement. Run intake/output only in owner-controlled directories with ACLs that prevent other users or processes from replacing path components. This remains a platform limitation and is not described as race-proof.
- Source documents are treated as data, not instructions. Retrieval evaluation does not generate answers or execute document content. This slice does not implement end-to-end prompt-injection mitigation for a future answer-generation pipeline.
- Holdout fixtures stored in this repository are public synthetic samples, not protected evaluation data. Real holdout files and labels must live in restricted storage and remain unopened during development tuning.
- The release-seal checks bind workflow artifacts; they do not establish corpus licensing, reviewer qualifications, query quality, or absence of semantic/paraphrase leakage. Human curation remains required.

## Next steps

1. Prepare a source-attributed Arabic/English document corpus and frozen candidate-pool policy; separate dev and protected holdout before annotation.
2. Have two independent human reviewers judge query answerability plus document and chunk relevance; resolve disagreements with a third reviewer. Do not treat generated CSV rows as labels until this process is completed.
3. Validate the dev/holdout pair, freeze evaluation configuration, then run raw and Arabic-normalized BM25 on dev and inspect every failure.
4. Install a controlled optional embedding runtime and pinned model weights on the target host; run the E5 and hybrid comparison on the same frozen corpus, recording host, model revision, runtime, indexing time, query latency, and resource use.
5. Run the complete project suite and PostgreSQL/Alembic checks on Windows; review platform-specific path behavior on the actual owner-controlled ACL configuration.
6. Keep Phase 3 Quality Gate pending until its own acceptance evidence is complete. Keep Phase 4 RAG experimental until real labeled evaluation, grounding review, security review, and explicit product activation approval.
