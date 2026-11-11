# RAG Research and Experiment Notes — 2026-11-11

**Status: exploratory only.** Phase 3 remains blocked and Phase 4 production work is not authorized. Any code accompanying these notes is an isolated, stdlib-only retrieval prototype under `experiments/`; it is not wired into the application, database, API, or Ollama runtime. No project-specific quality result or 90% target is claimed here.

## What exists and what remains a decision

The remote baseline has no document ingestion, chunking, embedding, or retrieval implementation. Its Ollama client is generation-oriented. The Phase 4 draft is a proposal, not an approved production architecture. In particular, vector persistence, document retention/deletion, supported parsers, embedding model, data scope, and numerical acceptance thresholds remain open. The prototype therefore uses temporary caller-supplied text and vectors only; it does not download models, read project documents, or persist data.

## Recommended experiment sequence

1. Establish a transparent BM25 lexical baseline on the frozen project-specific evaluation set.
2. Test conservative Arabic normalization as a separately switchable ablation, applied symmetrically to queries and indexed text. Keep original source text untouched for evidence and citations.
3. Compare one multilingual dense model. `intfloat/multilingual-e5-small` is a plausible first candidate for resource-constrained testing. Its official model card describes 94-language support, MIT licensing, 384-dimensional embeddings and a 512-token limit; it requires `query:` and `passage:` prefixes for asymmetric retrieval. Pin the model revision before any measurement and test memory/runtime on the owner’s machine. [Official model card](https://huggingface.co/intfloat/multilingual-e5-small)
4. Consider reciprocal-rank fusion only after lexical and dense parents have independent measured runs. RRF combines ranks and avoids directly adding incomparable raw BM25 and cosine scores. [Original RRF paper](https://dl.acm.org/doi/10.1145/1571941.1572114)
5. Add a reranker only if it improves held-out relevance enough to justify its added latency, memory, and operational complexity. A larger option such as BGE-M3 supports multiple retrieval representations but should be considered only after resource measurement. [BGE-M3 paper](https://arxiv.org/abs/2402.03216)

MIRACL provides Arabic and English relevance judgments for monolingual retrieval over Wikipedia; it can serve as an external sanity check, but it is not a substitute for the project’s own annual reports and business documents. [MIRACL paper](https://aclanthology.org/2023.tacl-1.63/)

## Evaluation design required before tuning

- Build a versioned, owner-approved corpus and query set from permitted project documents; preserve document-level split separation so chunks from one source cannot leak across train/dev/holdout.
- Include Arabic→Arabic, English→English, Arabic→English, and English→Arabic queries; mixed-language, OCR-noisy, numeric/entity lookup, duplicate evidence, and genuinely unanswerable cases.
- Freeze labels and source spans before tuning. Keep a separate holdout that is opened only for final comparison.
- Report Recall@5/10, Precision@k, MRR@10, and nDCG@10 per language/direction. Report paired per-query uncertainty intervals, retrieval p50/p95 latency, peak memory, and index/storage footprint.
- Record corpus/query hashes, document split, tokenizer/model revision, normalization, chunking, top-k, runtime/library versions, hardware, and exact command.
- Define acceptance thresholds with the owner before optimization. Do not use one demo, public benchmark scores, or retrieval metrics as proof of answer factuality.

## Prototype boundary

The provisional prototype is meant to test deterministic and security-sensitive mechanics: bounded local text intake beneath an explicit root, provenance-aware chunks and stable identifiers, lexical ranking, exact cosine for supplied vectors, rank fusion, and hand-checkable metrics. It does not support PDF/DOCX, OCR, model inference, durable persistence, answer generation, authentication, or production use. Hostile instructions inside a retrieved source remain inert text evidence; model/tool prompt-injection behavior belongs to a later answer-generation design.
