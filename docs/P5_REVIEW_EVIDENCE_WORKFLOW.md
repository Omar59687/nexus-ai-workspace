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
