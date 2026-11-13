# Phase 4 generated PDF-to-RAG diagnostic

This opt-in diagnostic connects the existing bounded PDF worker, page-aware
ingestion, pinned local E5 embeddings, in-memory index, retrieval service, and
structured Ollama answer service. It creates four small synthetic text-layer
PDFs (English and Arabic) in a temporary directory. It does not read owner
documents, access PostgreSQL, activate an endpoint, download model weights, or
measure production accuracy.

## Windows live run

From the Nexus AI repository PowerShell prompt, using the existing cached E5
environment and Hugging Face cache:

```powershell
.\scripts\run_pdf_rag_e2e.ps1 -RunLive
```

Defaults use `%LOCALAPPDATA%\NexusAI\rag-e5-venv\Scripts\python.exe`,
`%LOCALAPPDATA%\NexusAI\huggingface`, and write a JSON report to
`%LOCALAPPDATA%\NexusAI\reports\pdf-rag-e2e.json`. The wrapper forces offline
Hugging Face loading. It requires the configured local Ollama service to be
available. Override `-Python`, `-Cache`, or `-Report` only with existing local
paths. The script refuses to run live without `-RunLive`.

The report records generated document IDs, source-version IDs, extracted page
numbers, source hashes, retrieved source/chunk identities, exact synthetic
evidence text, model answer text, answer citations, safe error categories, and
whether expected source documents appeared in retrieval results. Each citation
is checked against the temporary extracted pages, source version, document
identity, chunk ID, and exact offsets before it is reported as valid.
Console JSON escapes non-ASCII characters for Windows code-page safety; the
optional report file is UTF-8 and retains readable Arabic.

## Reading the results

`execution_status` means the expected plumbing and provenance checks executed
and passed. The report always marks `semantic_accuracy` and
`abstention_quality` as `NOT_SCORED`; model output quality varies and these
synthetic cases are not human-reviewed labels. A case may fail if expected
source evidence is not retrieved, structured generation is rejected, or a
citation cannot be matched to extracted source text. A no-answer control filters
to a deliberately absent document ID, verifies empty retrieval, and confirms
that the answer service abstains without calling Ollama.

The corpus covers EN→EN, AR→AR, AR→EN, and EN→AR retrieval, a question that
requires evidence from two PDFs, and an empty-evidence control. Supported
numeric answer validation and fabricated citation rejection are covered by
deterministic fake-adapter tests; these tests do not load E5 or call Ollama.

## Answer coverage (separate from execution PASS)

The diagnostic now reports `fixture_answer_coverage`: number of answerable
synthetic cases, number answered with source-validated citations, unnecessary
abstentions, and a coverage fraction. Each case has `fixture_answerability`
and `answer_coverage_status`. An answerable case that safely abstains can
**still pass pipeline execution** while recording `UNNECESSARY_ABSTENTION`.
The deliberately empty no-answer case records `EXPECTED_ABSTENTION` and
is excluded from the answerable coverage denominator.

Coverage is **not** a score of factual correctness or semantic entailment.
Even a cited answer can be factually wrong; independent reviewed judgments
and adversarial tests are still required before calling output accurate. A
high-quality score must never be inferred from top-level `execution_status`.
Existing fail-closed citation and unsupported-number checks are unchanged.

## Synthetic numeric-fact verification

In addition to citation coverage, every answerable generated-PDF question has
an explicit numeric fact expectation. The diagnostic records
`fixture_numeric_facts_match` per case and
`fixture_answer_coverage.answered_with_expected_numeric_facts` plus
`all_expected_numeric_facts_present` in the summary. Revenue must represent
42 million dollars; the multi-document answer must additionally include 1,200
employees. Arabic and English numeric representations are checked by the
existing conservative number/unit parser. This prevents a response containing
only citations or generic prose from appearing factually successful.

These checks are **synthetic fixture assertions only**, not a substitute for
reviewed financial accuracy, table understanding, year attribution, source
relevance, or a protected holdout. Top-level technical `execution_status`
remains independent of numeric-fact matching, and the existing answer rejection
rules remain unchanged.

## Local test commands

```powershell
python -m unittest tests.retrieval.test_pdf_rag_e2e
python -m unittest tests.retrieval.test_answering tests.documents.test_ingestion
```

For tests that depend on OS-enforced PDF worker limits, run the repository's
platform-specific worker tests separately. The diagnostic requires pypdf and
the existing configured Windows worker controls. It does not add OCR; scanned
PDFs without a text layer remain unsupported.

The PDFs have a Unicode ToUnicode text layer but use a minimal synthetic font
map. When default extraction contains right-to-left characters, the worker
prefers pypdf layout extraction if it also contains right-to-left text. If the
chosen output differs, the worker records a page warning. This avoids treating
equal-length but differently ordered strings as equivalent. Worker IPC JSON is
ASCII-safe; the parent JSON decoder restores the original Unicode content.
