# Nexus AI Workspace

A local-first AI workspace built with FastAPI, PostgreSQL, and Ollama.

## Local LLM benchmarks

Run the reproducible local benchmark for `llama3.2:latest` from PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python scripts\run_llm_benchmark.py
```

Reports are saved under the Git-ignored `local_data/llm_benchmarks/`
directory. See [docs/BENCHMARKS.md](docs/BENCHMARKS.md) for case definitions,
evaluation rules, measurement details, and test commands.
