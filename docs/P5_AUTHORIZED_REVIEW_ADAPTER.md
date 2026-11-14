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


## Opt-in HTTP adapter

`create_financial_review_router` in
`src/nexus_ai/financial_review_http.py` creates FastAPI endpoints for
submission, approval, rejection, status and bounded reviewed analytics.
It is **not imported or mounted in `nexus_ai.main`**. The trusted
application host must explicitly mount it, supplying all four arguments:

- A server-configured `workspace_id` (not supplied by query/body/path).
- A `ledger_factory` returning a ledger for exactly that workspace.
- `authenticate_request(request)` which validates a real session/token and
  returns a `ReviewPrincipal` created by trusted server code.
- `authorize(principal, workspace_id, action)` which obtains up-to-date
  grants from a trusted permission store, and returns literal `True` only
  for authorized operations.

Routes use `/financial-reviews/selections`,
`/financial-reviews/selections/{item_id}/approve`,
`/financial-reviews/selections/{item_id}/reject`,
`/financial-reviews/status`, and `/financial-reviews/analyze`.
The approve body cannot contain an identity field: the reviewer's identity
is taken from the verified server-side principal. Strict schemas reject
unknown fields and type coercion. The ledger continues to verify active
document version, exact numeric evidence, and explicit human decisions.

HTTP 401 means authentication failed, 403 means authorization failed, 422
means invalid input/source evidence, and 503 means ledger wiring failure.
These responses intentionally avoid leaking document data, paths and tokens.
Response status and analytics data are returned only after authorization.

This is **still not** a deployed, publicly authenticated API. It does not
implement a credential verifier, session issuance, CSRF protection, secure
cookies, per-document authorization, visual inspection UI or migration
rollout. A host must configure and independently security-test these.
Do not mount these routes with a hard-coded/mock principal or allow-all
policy in a real application.

`tests/test_financial_review_http.py` uses a fake ledger to exercise
request validation, auth rejection, action-specific denial, tenant mismatch,
reviewer spoofing, and permitted lifecycle calls, without any database or
network access to an actual service.
