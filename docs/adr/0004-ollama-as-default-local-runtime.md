# Ollama as the default local model runtime

**Status:** Accepted

Ollama is the default local model runtime because it requires no paid API, runs on the owner's machine, and exposes completion and token metrics needed for evidence-based evaluation. The default model remains `llama3.2:latest` until a model decision is approved with evidence covering factual reliability, completion behavior, latency, memory, and hardware placement.

## Consequences

- Local hardware limits model size, latency, and concurrency.
- The documented factual failures of the default model remain visible limitations.
- Changing the default model requires a recorded decision; speed alone is insufficient.
- Provider-specific code should stay behind the model-adapter boundary.
