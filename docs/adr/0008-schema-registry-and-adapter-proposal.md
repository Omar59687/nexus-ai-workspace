# Schema registry and model adapter for structured outputs

**Status:** Proposed

The schema registry, bounded-retry service, and provider-specific adapter are implemented in baseline history and CP4 was explicitly accepted by the owner. The HTTP integration is committed at the current verified baseline `1926993`. A separate uncommitted follow-up configures structured-call timeouts and adds an opt-in live smoke harness; it does not change the HTTP contract. ADR-0010 records the public contract; ADR-0011 records the proposed LangChain rationale. This architecture ADR remains proposed until the owner accepts the overall direction.

## Considered options

- A direct Pydantic-only path with no registry.
- A registry plus service plus adapter boundary.
- A LangChain-specific implementation without a provider boundary.

## Consequences

- Schema validity proves structure only, not factual correctness.
- The adapter must reject unverifiable completion and incomplete generations.
- The service must not return a rejected result as success or fabricate metrics.
- FastAPI integration is committed at baseline `1926993`; the separate timeout/smoke follow-up is under review and does not alter the HTTP contract.
