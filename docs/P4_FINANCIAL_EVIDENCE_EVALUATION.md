# Phase 4 Financial Evidence Retrieval Evaluation

This is a deterministic, model-independent harness for the durable collection
index and `CollectionLexicalRetriever`. It indexes only the checked-in synthetic
fixture into `InMemoryCollectionIndexRepository`, registers explicit
company/year metadata, runs the existing BM25 retrieval path, and validates
citations against active source versions and page offsets.

It does not connect to PostgreSQL, call an LLM, generate embeddings, use paid
services, or claim financial accuracy. The fictional company names and invented
amounts are test data only.

## Run

From the repository root:

```bash
PYTHONPATH=src python -m nexus_ai.benchmark.financial_evidence \
  > benchmarks/results/financial_evidence_synthetic_v1.json
```

The command uses the fixture at
`benchmarks/financial_evidence_synthetic_v1.json` by default. Pass `--fixture`
to evaluate another fixture that follows the same schema. The checked-in result
is reproduced by this command and contains the synthetic run’s aggregate
metrics, per-case labels, relevant citations, and currency-decoy citations.

Focused tests:

```bash
PYTHONPATH=src python -m pytest -q \
  tests/test_financial_evidence_evaluation.py \
  tests/retrieval/test_collection_lexical.py \
  tests/retrieval/test_collection_registration.py \
  tests/documents/test_collection_index.py
```

## Fixture design

The schema requires `synthetic: true`, a bounded list of text documents with
explicit page boundaries, company aliases, metadata company/year, independent
fixture identity company/year, and expected evidence records. The test-only
extractor maps form-feed-separated UTF-8 fixture text to numbered pages. Each
case declares a query language, explicit company/year filter, and source page
judgment containing a financial year, metric, amount and currency; missing-fact
cases instead declare an explicit absence phrase.

The included eight cases cover Arabic-to-Arabic, English-to-English,
Arabic-to-English, English-to-Arabic, a comparative table, two conflicting
synthetic values, an equal amount shown in different currencies, and an EPS
value explicitly not disclosed. These annotations are synthetic test
assertions. They are not independently reviewed real-PDF judgments.

## Metric interpretation

- **Recall@5 / Recall@10:** retrieved expected source-page passages divided by
  all fixture-judged expected passages. A passage is a unique `(path, page)`
  target, including explicitly labeled absence evidence.
- **Citation provenance integrity:** citations whose workspace, document ID,
  source version, source digest, path, chunk, page, exact text and offsets
  validate against the active collection index, divided by returned citations.
- **Company/year leakage:** returned citations whose registered metadata or
  independent fixture identity differs from the requested company/year.
- **Missing evidence:** whether an explicit source statement that a fact was
  not disclosed was retrieved. No answer generator exists in this run, so this
  is not an abstention or hallucination metric.
- **Failure causes:** extraction, chunking, retrieval, missing evidence,
  incorrect metadata, incorrect currency, and citation provenance. Extraction
  means indexed page text differs from fixture source; chunking means the
  source page has the expected fact but no single chunk preserves it; retrieval
  means an available expected passage is absent from top-k.

The fixture deliberately includes a conversion-note decoy that repeats a
revenue amount in the wrong currency. The harness reports those candidates as
`incorrect_currency`; they are a retrieval diagnostic to review, not evidence
that any actual company reported those values.

## Current synthetic report

The checked-in run produced Recall@5 **9/9**, Recall@10 **9/9**, citation
provenance **25/25**, company/year leakage **0/25**, and retrieved the explicit
missing-EPS evidence in **1/1** missing-fact cases. It also identified **3**
incorrect-currency candidates from the planted decoy. These values describe
only these eight synthetic queries and four synthetic documents. They do not
predict performance on 50–150 real PDFs or establish Phase 4 acceptance.

## Failure triage for real-corpus preparation

Before adapting this harness to independently reviewed PDFs, reviewers must
annotate document identity, report year, financial period, metric, amount,
currency, page and relevant source passage. Keep their labels and evidence
outside this synthetic fixture until approved for the evaluation split. A real
benchmark run must preserve its corpus digest, extraction/chunk settings,
collection revision and reviewer provenance. Do not interpret an empty result
as proof that the source lacks a fact.
