# Local E5 + Ollama Integration Harness

This is an opt-in diagnostic for the candidate retrieval and grounded-answer
services. It builds a small generated bilingual corpus in a temporary
directory, embeds it with the pinned multilingual E5 model from the local cache,
retrieves evidence, and passes bounded citations to the existing structured
Ollama adapter. It does not access user documents or download model weights.

## Run

From the repository root in PowerShell:

```powershell
$env:PYTHONPATH = "src"
python scripts/run_local_rag_integration.py --run-live
```

The command uses the application's existing Ollama model and endpoint
configuration without printing endpoint values or credentials. Add a custom
question against the synthetic documents with:

```powershell
python scripts/run_local_rag_integration.py --run-live --question "What was the generated 2024 revenue?"
```

Without `--run-live`, the script exits with `BLOCKED` before importing or
initializing model runtimes. Missing cached E5 weights, unavailable Ollama,
dependency errors, or generation failures produce a generic blocked result;
the exception details are not printed.

## Coverage and interpretation

The generated suite exercises AR→AR, EN→EN, AR→EN, and EN→AR questions; two
conflicting source records; a prompt-injection fixture; citation provenance;
and a filtered empty-evidence abstention control. The four language directions
filter to a selected fixture source so the diagnostic can inspect each path.
This is not a fair corpus-wide retrieval comparison and does not validate
semantic answer accuracy. The empty-evidence case is a control; it does not
prove that the retriever detects arbitrary unanswerable questions. Review the
JSON output manually. Do not convert the output into production accuracy or
Phase 3 / Phase 4 acceptance evidence.

The ordinary fake-based suite never starts E5 or Ollama. Run it with:

```powershell
$env:PYTHONPATH = "src"
python -m pytest -q tests/retrieval/test_local_integration_harness.py tests/retrieval/test_answering.py tests/retrieval/test_service.py
```
