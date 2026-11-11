# Offline RAG retrieval prototype

This standalone experiment uses Python's standard library and synthetic test fixtures.

| API | Behavior |
| --- | --- |
| `read_document(root, path, max_bytes=...)` | Accepts root-relative UTF-8 `.txt` and `.md` files, including uppercase suffixes. Rejects traversal, symlinks that resolve outside the root, nonregular files, and oversized or invalid UTF-8 input. PDF and DOCX are unsupported. |
| `chunk_document(document, max_chars=...)` | Returns contiguous source slices with zero-based character offsets `[start_char, end_char)` and one-based inclusive line spans. Prefers line boundaries and recognizes Markdown ATX heading paths outside fenced code blocks. |
| `BM25Index(chunks).search(query, top_k=...)` | Returns positive-scoring chunks. Optional exact filters accept `source`, `document_id`, `version_id`, and `heading_path`. Each hit carries the original chunk text and offsets for citation. |
| `exact_cosine(query, vectors, top_k=...)` | Ranks caller-supplied vectors by exhaustive cosine similarity. Vectors must have matching positive dimensions, finite coordinates, and a nonzero norm. |
| `reciprocal_rank_fusion(rankings, top_k=...)` | Sums reciprocal ranks over ordered ID lists with unique entries in each list. Pass chunk IDs to fuse lexical and vector rankings over the same chunks. |
| `retrieval_metrics(ranking, relevance, k=...)` | Calculates per-query Precision@k, Recall@k, reciprocal rank at k, and nDCG@k. Grades are non-negative integers and nDCG uses the gain `2**grade - 1`. Precision uses k as the denominator. |
| `mean_retrieval_metrics(queries, k=...)` | Macro-averages query metrics, yielding MRR@k. A no-answer fixture contributes zero for each metric. |
| `ensure_disjoint_documents(dev, holdout)` | Rejects shared document IDs across the two splits, including across versions. |

The resolved root-relative path identifies the document within its corpus, so in-root symlink aliases refer to the same document. File bytes determine the version for that document. The version, chunk size, and character offsets determine the chunk ID. Character offsets index Python strings and preserve the original line endings.

BM25 uses Unicode letters, numbers, and attached combining marks with case folding. Pass `normalize_arabic=True` to apply the same optional transformations to indexed text and queries. The switch folds آ, أ, and إ to ا and removes tatweel and the basic Arabic vocalization marks U+064B through U+0652. Equal scores are ordered by ascending ID in each ranking helper.

Use a root controlled by the caller. Intake validates the resolved path and file type and bounds the read even if the reported size changes. Filesystem mutations between path resolution and opening can still race these checks. Heading recognition covers ATX headings and fenced blocks. Retrieval is in memory, and cosine uses vectors supplied by the caller. Instruction-like text is handled as source text.

Run the synthetic fixtures from the repository root.

```sh
python -B -m unittest -v tests.test_rag_prototype
```

The fixture metrics are hand-checkable test expectations for synthetic data. Empty relevance labels produce zero metrics regardless of returned items; these helpers do not measure false-positive or abstention quality for unanswerable queries.
