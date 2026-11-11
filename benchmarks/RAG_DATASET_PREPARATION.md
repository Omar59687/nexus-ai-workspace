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
