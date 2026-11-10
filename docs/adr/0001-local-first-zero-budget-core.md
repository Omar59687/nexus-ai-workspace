# Local-first core with optional cloud providers

**Status:** Accepted

Core workflows must run locally with open-source or free components and no paid API keys; cloud providers are optional and may never be required. This protects privacy, keeps the learning project reproducible on the owner's hardware, and preserves the $0 software budget while leaving room for optional provider adapters later.

## Consequences

- Local model quality and latency limit the default experience.
- A provider abstraction is required before adding a second provider.
- No cloud fallback may happen silently.
- Core features must not depend on a hosted service, subscription, or paid credential.
