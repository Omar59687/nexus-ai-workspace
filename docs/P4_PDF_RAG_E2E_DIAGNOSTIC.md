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
map. The PDF worker uses pypdf's layout extraction only as a fallback when the
default extraction contains right-to-left characters but returns fewer
characters than layout mode. This narrow fallback preserves the normal
extraction path for other documents.
