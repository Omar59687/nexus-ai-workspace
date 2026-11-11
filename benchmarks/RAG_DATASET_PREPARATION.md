# Nexus RAG benchmark dataset preparation (schema v2)

## What the tool does

The benchmark_dataset.py module and rag_dataset_tool.py script create bounded corpus manifests, export blank review sheets, record submitted decisions, summarize independent votes, accept only matching votes or a separate adjudicator decision, and convert accepted labels into an evaluation fixture. No real corpus or human labels are included in this change.

Datasets are split-specific: each JSON manifest names exactly one split (dev or holdout). The default retrieval CLI opens only the development fixture. A holdout run requires both an explicit --fixture path and --allow-holdout. The synthetic holdout JSON in this repository is public sample data and is **not protected**; put a real held-out dataset and its judgments in a permission-controlled location outside the repository, and do not use it to tune retrieval.

Before sealing a real dataset release, the owner may run `python scripts/rag_dataset_tool.py validate-pair dev.json holdout.json`. This explicit release-time check opens both splits to check cross-split IDs, source references, and exact normalized document/chunk content. Routine development evaluation opens only the selected single-split fixture. Near-duplicate paraphrases still require human review.

## Dataset and judgment rules

- Give every dataset a stable dataset_id and incrementing dataset_version.
- Record the source name/version, retrieval date, license, and a SHA-256 fingerprint.
- Preserve stable document IDs, content-derived version IDs, source references, language (ar/en), exact text hashes, chunk IDs, and source character offsets.
- Draft queries identify query language, expected evidence language, and split. The answerable field in a draft is provisional until reviewers decide it.
- Candidate review rows include query answerability, document relevance, and chunk relevance. Grades are 0 not relevant, 1 marginal, 2 relevant, and 3 highly relevant. For answerability rows, use 0 for no supporting answer in the corpus and 3 when supporting evidence exists. Add a rationale for every positive grade.
- Each reviewer works independently under a distinct reviewer ID. Two matching decisions are recorded as accepted_by_agreement; disagreements remain needs_adjudication until a separate adjudicator supplies a grade and rationale. Unresolved/pending items cannot enter evaluation.
- Review CSVs include the query and evidence text, document version/source references, and content/provenance SHA-256 values. Import checks those fields against the frozen manifest. Reviewer IDs are assigned by the organizer and checked for consistency, but the CSV format does not authenticate a person's identity.
- Adjudication envelopes are sealed to a canonical SHA-256 of the exact dataset release. Generated evaluation fixtures also carry a separate content seal, checked before evaluation, so changed questions, sources, documents, or chunks invalidate the review evidence.
- The evaluation builder requires accepted answerability and chunk judgments for each query/candidate chunk. Document-level judgments remain in the annotation record for document-level metrics and analyses.
- Each split must independently contain answerable Arabic→Arabic, English→English, Arabic→English, and English→Arabic queries. A production benchmark should also record the candidate-pool construction protocol and judge every chunk returned by all compared systems; the current tool exports exhaustive query×document and query×chunk review rows and refuses more than 100,000 rows by default.

## Windows workflow

Run ingestion and output only inside directories whose Windows ACLs restrict modification to the trusted project owner and the current process. The standard-library Windows fallback rejects observed symlinks, junctions, and other detectable reparse points, and checks file identity, but it cannot provide POSIX-style directory-handle-relative protection against a hostile process concurrently replacing path components. Do not point these commands at attacker-writable or shared intake/output trees. This is an explicit residual limitation, not a claim of race-proof Windows filesystem access.

1. Create a metadata CSV with exact columns relative_path,language,source_ref. relative_path is relative to the corpus root; source_ref identifies a source page or record and must not contain credentials.

2. Ingest one split and create an unjudged manifest (adjust the dates and attribution to the actual source):

    python scripts/rag_dataset_tool.py ingest --root data/benchmark/dev --metadata-csv data/benchmark/dev-metadata.csv --dataset-id nexus-bilingual-docs --dataset-version 1 --split dev --source-name "Owner-reviewed documents" --source-version 1 --license "record the applicable license" --retrieved-at 2026-11-11 --output data/benchmark/dev-draft.json

   The tool accepts UTF-8 .txt and .md files only. Defaults cap one file at 2 MB, total input at 50 MB, total characters at 40 million, files at 500, chunks at 100,000, and each chunk at 4,000 characters. It does not read .env or infer a document's language.

3. Add draft query rows to the manifest. Include enough questions to cover each of the four directions, and keep only one split in this file. Review the candidate pool before annotation; for a large corpus, define a frozen pooling protocol before exporting review rows.

4. Export a blank sheet for each reviewer:

    python scripts/rag_dataset_tool.py export-review data/benchmark/dev-draft.json --reviewer-id reviewer-a --output data/benchmark/review-a.csv
    python scripts/rag_dataset_tool.py export-review data/benchmark/dev-draft.json --reviewer-id reviewer-b --output data/benchmark/review-b.csv

5. Each reviewer independently completes relevance and rationale. Import one sheet, then import the other into that new snapshot. During import, provide the assigned reviewer ID; the tool rejects CSV rows whose reviewer ID was changed:

    python scripts/rag_dataset_tool.py import-review data/benchmark/dev-draft.json --csv data/benchmark/review-a.csv --reviewer-id reviewer-a --output data/benchmark/dev-review-a.json
    python scripts/rag_dataset_tool.py import-review data/benchmark/dev-review-a.json --csv data/benchmark/review-b.csv --reviewer-id reviewer-b --output data/benchmark/dev-reviews.json
    python scripts/rag_dataset_tool.py adjudicate data/benchmark/dev-reviews.json --output data/benchmark/dev-adjudications.json

6. Resolve conflicts in a separate CSV with columns question_id,target_kind,target_id,adjudicator_id,relevance,rationale, then run resolve. The adjudicator must have a distinct ID. Pending items remain excluded.

7. Build an evaluation fixture and run it only after validation:

    python scripts/rag_dataset_tool.py build-eval data/benchmark/dev-reviews.json --adjudications data/benchmark/dev-final-decisions.json --output data/benchmark/dev-eval.json
    python scripts/run_rag_eval.py --fixture data/benchmark/dev-eval.json --split dev -k 5

For protected evaluation, create the holdout with its own IDs and provenance, store it outside the repository with restricted access, and do not call the holdout command until model and retrieval configuration are frozen. Synthetic samples exist only to exercise code paths; they are not quality evidence.

## Frozen corpus and annotation protocol for a real benchmark

The current CSV exporter reviews every query against every document and chunk.
It is suitable only when that exhaustive review fits below the configured
100,000-row cap. It does **not** yet accept a candidate-pool manifest. Do not
silently reduce the pool, treat omitted items as nonrelevant, or claim corpus
wide Recall when only a pool was judged. If exhaustive review is too large,
stop before annotation and add/review a versioned pool-manifest feature first.

For a bounded real benchmark, freeze the corpus manifest and annotation policy
before collecting judgments. For every query, include every chunk returned at
the agreed depth by every strategy being compared, plus the query's independently
identified evidence chunks. Freeze model, retriever, preprocessing, top-k,
pooling depth, and software revisions. Preserve the pool build inputs, strategy
names and ranks in a restricted audit record; remove system identity and rank
from reviewer-facing sheets so reviewers judge evidence support rather than
system preference. The current CSV tooling does not implement this masking or
pool selection, so the current supported workflow remains exhaustive review.

Keep document-level relevance judgments as a distinct annotation layer. The
current evaluation runner scores chunk retrieval; it does not compute
document-level retrieval metrics. Do not report those annotations as measured
document retrieval quality.

For every answerable query, reviewers must confirm that the declared
`evidence_language` matches the language of all adjudicated relevant chunks.
The fixture builder now rejects a mismatch. Unanswerable questions have no
evidence language and no relevant chunks. Each split must independently include
AR→AR, EN→EN, AR→EN, and EN→AR.

## Optional local E5 evaluation on Windows

E5 remains opt-in; ordinary tests and BM25 evaluation do not load weights or
download a model. The adapter pins `intfloat/multilingual-e5-small` to revision
`614241f622f53c4eeff9890bdc4f31cfecc418b3`, loads from the local cache only,
and uses `query: ` / `passage: ` prefixes. Start with CPU so the comparison is
available without CUDA setup. Use a separate virtual environment if the base
project environment should remain unchanged.

In PowerShell from the repository root (Python 3.12):

```powershell
py -3.12 -m venv "$env:TEMP\NexusAI-rag-e5"
& "$env:TEMP\NexusAI-rag-e5\Scripts\Activate.ps1"
python -m pip install --upgrade pip
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
python -m pip install transformers==5.20.1
New-Item -ItemType Directory -Force local_data\rag-e5 | Out-Null
python -m pip freeze | Set-Content -Encoding ascii local_data\rag-e5\e5-environment.lock.txt
```

The PyTorch command follows the official Windows CPU installation selector;
check the selector if the installed Python/platform changes. Record the exact
resolved versions from the lock file with every result. Then fetch the exact
model revision once and verify offline loading:

```powershell
$env:HF_HOME = Join-Path $env:LOCALAPPDATA 'NexusAI\huggingface'
python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='intfloat/multilingual-e5-small', revision='614241f622f53c4eeff9890bdc4f31cfecc418b3')"
python -c "from transformers import AutoModel, AutoTokenizer; r='614241f622f53c4eeff9890bdc4f31cfecc418b3'; AutoTokenizer.from_pretrained('intfloat/multilingual-e5-small', revision=r, local_files_only=True, trust_remote_code=False); AutoModel.from_pretrained('intfloat/multilingual-e5-small', revision=r, local_files_only=True, trust_remote_code=False); print('PINNED E5 CACHE: PASS')"
```

Run the same development fixture and settings for every strategy:

```powershell
python scripts/run_rag_eval.py --split dev --fixture benchmarks/rag_eval_synthetic_dev_v2.json -k 5 --with-e5 --measure-latency --json-out local_data/rag-e5-dev.json
```

The checked-in fixture is synthetic; its scores are code-path diagnostics only.
For real documents, use a separate dev fixture created through the annotation
workflow above. Select any dense or hybrid abstention threshold using dev only,
record it, and freeze it with the other retrieval settings. The dense threshold
is cosine similarity (`--e5-minimum-score`); the hybrid threshold is fused RRF
score (`--hybrid-minimum-rrf-score`). They have different scales and must not be
compared numerically.

Only after the corpus, model revision, settings, threshold, and scoring rules
are frozen, run a protected holdout once with an explicit path and opt-in:

```powershell
python scripts/run_rag_eval.py --split holdout --fixture 'D:\Nexus-Private\holdout-eval.json' --allow-holdout -k 5 --with-e5 --measure-latency --json-out 'D:\Nexus-Private\holdout-result.json'
```

Protect both holdout inputs and reports with Windows ACLs. The CLI guard is a
workflow safeguard, not access control. If PyTorch, Transformers, or the pinned
cache is absent, E5 measurement is **NOT RUN**; do not substitute synthetic
fixture performance as real-corpus evidence.

Installation references: [official PyTorch local installation selector](https://pytorch.org/get-started/locally/), [Transformers installation and cache guidance](https://huggingface.co/docs/transformers/installation), and the [pinned multilingual-E5 model card](https://huggingface.co/intfloat/multilingual-e5-small/tree/614241f622f53c4eeff9890bdc4f31cfecc418b3).
