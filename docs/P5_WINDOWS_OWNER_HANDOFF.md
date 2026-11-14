# Nexus AI Phase 5 — Windows owner acceptance handoff

**Repository:** https://github.com/Omar59687/nexus-ai-workspace

**Source branch:** \`feature/p5-review-evidence-workflow\`

**Scope:** validate the opt-in PDF evidence and financial review workbench
against the owner's real local annual-report files using a disposable,
loopback-only test environment. No production deployment, migration, PR,
or merge without explicit owner approval.

## What is already implemented

- Durable PostgreSQL reviewed-financial ledger with version-safe citations.
- Per-operation authentication, revocable opaque sessions, and workspace grants.
- Operator-only token issuance and revocation library (no public token API).
- Authenticated HTTP endpoints for pending review, indexed evidence,
  original-PDF download, explicit review decisions and financial analytics.
- Original PDF validator (hash match, 40 MiB maximum, 500-page maximum,
  cited page present) and pinned local PDF store using the Phase 4 hardened
  approved-root reader and document-level ACL.
- Optional reviewer workbench at \`/financial-reviews/reviewer\` (not enabled by
  default, does not store credentials in browser storage).
- Synthetic full-stack end-to-end tests in disposable PostgreSQL and real
  synthetic PDF bytes.

## Mandatory verification procedure

1. Fetch the latest branch and verify the SHA against GitHub before changing
   anything. Use a separate local worktree or clone so that unrelated work
   cannot be overwritten.
2. Inspect the latest CI results before starting local tests. Do not assume
   the branch is passing unless the *current* commit's job succeeded.
3. Provision a **disposable** localhost PostgreSQL database guarded by the
   Phase 4 test preflight. Never connect test setup to hosted or customer DBs.
4. Explicitly configure, in a local test-only host, the PostgreSQL collection
   index, review ledger, session access verifier, operator provisioner and
   the \`PinnedLocalPdfStore\`. The pin map must use trusted, immutable
   document/version/hash tuples; source paths must be explicitly selected
   relative to an approved root and protected from untrusted writes.
5. Create a short-lived **test** bearer token with the operator-only library
   and grant only the needed workspace/actions. Do not display the token in
   logs, chat, screenshots, or source control. Document ACL must also check
   each requested document.
6. Enable the optional review workbench **only** in the disposable test host.
   Inspect a real Arabic annual report: pending numeric citation, indexed
   source excerpt, verified original PDF download, corresponding visual
   page, explicit year/metric/currency/unit selection and approval.
7. Verify security negatives: no token, revoked token, permission revoked
   mid-request, unauthorized document, cross-workspace ID, modified source
   PDF digest, modified indexed source generation, rejected/double-decision,
   oversized PDF, and invalid review attestations.
8. Verify reviewed-data analytics (annual totals, deduplication, conflict
   rejection, provenance) on at least two approved report years. Do not
   assert the test account's manual selections prove automatic extraction.
9. Capture sanitized screenshots and result summaries. Redact all bearer
   tokens, absolute sensitive paths, raw PDF contents and real financial
   values when sharing broadly.
10. Report tests with exact command, environment boundaries, pass/fail/skip
    counts, errors, source identities and Git SHA. Distinguish software
    defects from unavailable real files or missing operator approvals.

## Stop and request owner approval before

- Running a schema migration on a non-disposable DB.
- Connecting production document stores, employee identities or token issuers.
- Creating public network exposure, deploying, opening a PR or merging.
- Changing the project's financial verification trust policy.
- Marking the product production-ready.

If the original PDF collection is not available, complete the synthetic
workloads and explicitly report the real-report visual acceptance as BLOCKED.
Do not invent source evidence or substitute a fabricated PDF for the real
report acceptance gate.

## Reviewer guardrails

Source text previews are **not** original PDF visual review; the UI never
automatically attests financial facts. The approved browser page is an
operator workbench, not a production authentication UX. Pinned original PDF
files are opened only after independent workspace and per-document checks.
