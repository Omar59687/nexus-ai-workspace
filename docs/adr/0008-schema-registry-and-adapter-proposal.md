# Schema registry and model adapter for structured outputs

**Status:** Proposed

The proposed structured-output architecture couples a schema registry, a service with bounded validation retries, and a provider-specific model adapter. Local untracked files explore this shape, but the design is not accepted: it requires independent review, dedicated tests, a public API contract, and a decision on whether LangChain is required.

## Considered options

- A direct Pydantic-only path with no registry.
- A registry plus service plus adapter boundary.
- A LangChain-specific implementation without a provider boundary.

## Consequences

- Schema validity proves structure only, not factual correctness.
- The adapter must reject unverifiable completion and incomplete generations.
- The service must not return a rejected result as success or fabricate metrics.
- FastAPI integration must wait for review and an approved contract.
