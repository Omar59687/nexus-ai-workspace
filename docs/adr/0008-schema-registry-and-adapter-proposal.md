# Schema registry and model adapter for structured outputs

**Status:** Proposed

The schema registry, bounded-retry service, and provider-specific adapter are implemented in baseline commit `e45a7aa` and CP4 was explicitly accepted by the owner. The HTTP integration is in the uncommitted CP5 working diff and is pending owner review. ADR-0010 records the proposed public contract; ADR-0011 records the proposed LangChain rationale. This architecture ADR remains proposed until the owner accepts the overall direction.

## Considered options

- A direct Pydantic-only path with no registry.
- A registry plus service plus adapter boundary.
- A LangChain-specific implementation without a provider boundary.

## Consequences

- Schema validity proves structure only, not factual correctness.
- The adapter must reject unverifiable completion and incomplete generations.
- The service must not return a rejected result as success or fabricate metrics.
- FastAPI integration exists in the CP5 working diff; it should not be treated as accepted until the owner reviews the patch.
