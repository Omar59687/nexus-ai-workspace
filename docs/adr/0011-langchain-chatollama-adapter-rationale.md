# ADR-0011: Proposed use of LangChain ChatOllama behind the structured adapter

- **Status:** Proposed; owner decision required
- **Date:** 2026-11-11

## Context

The Phase 3 roadmap names Ollama, LangChain, structured outputs, and local benchmarks. CP4 already provides a `StructuredModelAdapter` boundary and a `LangChainChatOllamaAdapter`; CP5 now wires that adapter to `/structured/generate`. The design must remain local-first, report provider completion and available metrics, and avoid coupling the structured service to LangChain.

## Proposed decision

For the current Phase 3 local Ollama structured-generation use case, retain LangChain `ChatOllama` as the adapter implementation while keeping the service dependent only on the repository's adapter protocol. This reuses the existing structured-output and raw-metadata integration and keeps provider-specific behavior at the boundary. Do not introduce LangGraph, cloud providers, or additional LangChain layers in this phase.

Before accepting this proposal, review dependency/license compatibility, pinned-version behavior, timeout support, resource cost, error mapping, and rollback path. The adapter tests must continue to prove completion enforcement and provider error mapping. No benchmark or factual-quality claim follows from selecting an adapter library.

## Consequences and limits

- Replacement remains possible behind `StructuredModelAdapter` if compatibility or maintenance costs fail review.
- Current adapter timeout behavior and dependency version compatibility need a concrete compatibility check; the current implementation does not pass a timeout option through `ChatOllama`.
- This remains a proposal until owner approval; it does not resolve all LangChain-related technical questions or pass the Phase 3 quality gate.
