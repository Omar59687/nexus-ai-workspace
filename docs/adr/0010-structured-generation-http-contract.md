# ADR-0010: Minimal registry-backed structured-generation HTTP contract

- **Status:** Proposed for owner review
- **Date:** 2026-11-11

## Context

CP5 exposes the CP4 registry and service through FastAPI. The repo had no public contract specifying schema selection, optional model selection, metric shape, or safe HTTP errors. The owner authorized a minimal reversible choice. Existing `/llm/generate` and task CRUD must remain compatible.

## Decision

Add `POST /structured/generate` with a strict JSON request containing a required nonblank `schema_name`, optional nonblank `prompt` (omission uses the registry default), and optional nonblank `model`. Reject unknown fields. Return `schema_name`, validated JSON `data`, and metrics with attempt snapshots plus aggregate values. Missing provider metrics remain JSON `null`; aggregate values are present only when all attempts reported that metric.

Map unknown schema to generic 404; malformed request and final semantic rejection to generic 422; timeout/unavailable to generic 503; malformed provider response or unverified completion to generic 502. Do not include prompts, generated output, raw validation input, or provider exception text in responses or logs. Keep CP4's existing bounded two-attempt semantic retry behavior. Leave TQ-11 (whether retry policy should change) open.

## Consequences

- The route is small and uses the existing registry, service, adapter, and configured `OllamaClient` values.
- The contract is represented in Pydantic models and OpenAPI.
- This ADR does not approve Phase 3 closure, a default-model change, frontend behavior, or production exposure beyond the current local service.
- Owner review is required before this ADR becomes accepted.
