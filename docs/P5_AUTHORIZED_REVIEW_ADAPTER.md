# Phase 5 — Authenticated review adapter (isolated candidate)

Branch: `feature/p5-authorized-review-adapter` (based on durable ledger head `728e02d`).

The model-independent `AuthorizedFinancialReviewAdapter` composes the
existing `PostgresFinancialReviewLedger`. Its constructor **requires** two
trusted, host-injected functions:

- `resolve_principal() -> ReviewPrincipal` obtains a real authenticated
  identity through the host's verified session/token middleware.
- `authorize(principal, workspace_id, action) -> bool` checks current
  workspace membership and action-specific grants. **Only literal
  `True`** permits the operation.

The adapter checks the policy on **every** submit, approve, reject,
status and analyze call. It never trusts the reviewer's name for
authentication: approval requires `ReviewDecision.reviewer_id` to
equal the trusted principal subject, while rejection uses the principal
subject itself. The underlying ledger rechecks source-version integrity,
financial evidence, transaction constraints and row-scoped workspace
isolation independently.

**Important limitation:** `ReviewPrincipal` is a data carrier, not a
credential, and can be constructed by any Python code. The host MUST
prevent untrusted code from directly constructing the service or supplying
a principal/policy resolver. Do not expose a public endpoint using caller
supplied `ReviewPrincipal`, bearer strings without signature verification,
a permissive default policy, or client-controlled workspace IDs. The adapter
is a *guarded library boundary*, not a complete authentication system.

No HTTP route, auth provider, schema migration, deployment, or real-document
review UI is added here. The existing durable table remains inert until an
operator intentionally installs it. No PR or merge is created.

## Acceptance

`tests/test_financial_review_adapter.py` covers successful operation
authorization, changing permissions, subject spoof rejection, non-principal
identity rejection, policy denial, and resolver failure. The Phase 5 CI
workflow additionally runs this test on the isolated branch alongside its
existing regression and guarded disposable-PostgreSQL suites.

**Next:** implement a real verified session resolver and tenant permission
source, then a bounded request adapter with principal resolved by server-side
middleware; independently review workspace and document access before any
public exposure.
