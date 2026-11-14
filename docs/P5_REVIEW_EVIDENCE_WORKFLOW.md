# Phase 5 — Verified Evidence Preview and Original PDF Attachment

**Branch:** `feature/p5-review-evidence-workflow`. This is an isolated,
opt-in continuation of the tested authorization and durable financial-review
ledger. No production migration or public route installation is performed.

## Reviewer workflow

1. Server authenticates the request using the independently configured,
   read-only PostgreSQL session verifier.
2. `GET /financial-reviews/selections` requires `list` permission.
3. `GET /financial-reviews/selections/{id}/evidence` requires
   **independent** `view_evidence` permission. It only returns exact
   indexed chunk text (up to 8192 characters) and citation identity.
   The ledger revalidates the active document and original offsets.
4. Optionally configure `pdf_bytes_provider(document_id, version_id)`
   when constructing the HTTP router. With a trusted provider only,
   `GET /financial-reviews/selections/{id}/original-pdf` requires
   **independent** `view_pdf` permission and returns the original
   source PDF as a forced attachment. This endpoint does not accept a
   user-selected filesystem path, remote URL, or arbitrary blob key.
5. The viewer must visually inspect the original PDF to establish the
   value's accounting row, label, year, currency and units, and only
   then use the existing explicit approval endpoint with both required
   visual attestations. Text preview, byte hashing and successful
   download **never set approval flags automatically**.
6. `POST /financial-reviews/analyze` includes only explicitly approved
   entries, with version and numeric citation checks repeated.

## PDF attachment boundary

The provider must be trusted infrastructure returning bytes **only** for
documents already authorized to that reviewer, not a helper that accepts
unsanitized paths. The endpoint revalidates the indexed citation before
and after provider access. The attachment must be nonempty, under 40 MiB,
begin with a PDF header, match the expected content SHA-256 of the indexed
source, have at most 500 pages, and include the cited page. A strict
pypdf parse checks the file structure. Mismatch, stale index, missing page,
or parse failures return generic error responses, not bytes.

The response uses `Content-Disposition: attachment` and
`Cache-Control: private, no-store`; it is not embedded as trusted HTML
and is **not a PDF page renderer**. Clients can open the authorized
download separately in their operating system's PDF viewer. Large
report files exceeding this bound are explicitly not supported.

The original PDF is **not** yet stored by the financial ledger. Source
bytes must be obtained through an injected, restricted document storage
service. The service cannot be mounted securely until that provider's
ACL and storage lifetime behavior have been reviewed.

## Security and production gaps

A release still requires independent **document-level ACLs** enforced by
the trusted byte provider, a privileged operator-only session provisioner,
session refresh/revocation handling, production RLS/DB-role review,
deployment migration, CSRF and browser threat review, request throttling,
full document visual viewer/UI, accessibility testing and audit logs.
The new `view_evidence` and `view_pdf` grants also require an
**explicit** migration for any preexisting permission table. Do not
blindly apply DDL or widen grants for existing tenants.

The test suite covers source-version replacement, oversized chunks,
authorization failures, PDF digest mismatch, malformed PDFs, absent
cited pages and opt-in route behavior. Tests use fake ledger data or a
disposable localhost database, never production credentials or PDF files.


## Opt-in reviewer workbench

The HTTP router accepts \`enable_review_page=True\` to mount
\`GET /financial-reviews/reviewer\`. The page is **not mounted by default**.
The development workbench fetches a bounded pending queue, opens independently
authorized indexed evidence, and downloads the digest-verified original PDF
attachment. The reviewer must inspect the original document in a local PDF
viewer; this page is not itself a visual PDF renderer.

Approval requires manually entered company, year, metric, currency and unit
and two human-attested checkboxes. There is no default approval or automatic
financial-row inference. Rejection is confirmed before submission.

The workbench uses a temporary bearer token entered into a password field,
held only in current JavaScript memory and cleared from the input immediately.
It does not use \`localStorage\`, \`sessionStorage\`, cookies, third-party
JavaScript, or analytics. Untrusted evidence is presented only with
\`textContent\`, never interpolated into HTML. Each response includes a fresh
CSP nonce, a restrictive CSP, \`no-store\` and \`no-referrer\` headers.
It cannot obtain tokens itself; a secure, trusted token provisioning channel
is still required.

**Do not claim production browser security based on these tests.** The
workbench is intentionally operator-oriented. Proper deployment still needs
credential provisioning, document access enforcement, token rotation,
server-side rate limits, TLS, a real PDF viewer UX, mobile and accessible
visual testing, and independent browser security review.

## Second-account / Windows acceptance handoff

Engineering may proceed on GitHub without local input. Work that genuinely
requires the owner's Windows environment and original PDF collection:

1. Obtain a **test-only** disposable PostgreSQL database, compatible
   reviewed-financial schema and session permission schema, with no production
   records. Do not migrate hosted databases automatically.
2. Configure an authenticated, least-privilege document resolver capable of
   retrieving the exact original PDF bytes by immutable document and version
   IDs. Do not derive arbitrary file paths from URL or request data.
3. Explicitly mount the router in a **test-only** FastAPI app with a test
   workspace and trusted \`PostgresFinancialAccess\`. Supply the restricted
   ledger factory and PDF bytes provider, and set \`enable_review_page=True\`.
4. Manually provision a test session through a secure operator-only method.
   Supply \`list\`, \`view_evidence\`, \`view_pdf\`, \`approve\`, and \`reject\`
   grants only for the intended workspace; never commit or paste the token.
5. On Windows, test a real Arabic annual report in the browser: queue
   selection -> indexed text -> PDF download -> original-page inspection ->
   explicit approval -> source-backed multi-year analytics.
6. Independently verify unauthorized users cannot read another workspace,
   stale versions fail closed, expired/revoked sessions cannot act, and
   attempts to approve without both visual attestations fail.
7. Record screenshots, failures, and source IDs **without exposing sensitive
   PDF content or bearer tokens**. Do not merge or deploy without approval.

For quick module-level CI, no real PDF files, local Windows environment, or
human credentials are necessary; the isolated GitHub Actions workflow covers
fake and disposable-database tests.
