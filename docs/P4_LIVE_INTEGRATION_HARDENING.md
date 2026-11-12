# Phase 4 Live Integration Hardening

This isolated engineering slice adds regression coverage and opt-in integration
harnesses. It does **not** activate production RAG and does not change the
formal Phase 3 or Phase 4 gate status.

## Verification scope

- PostgreSQL adapter tests run only when `NEXUS_P4_TEST_DATABASE_URL` points to
  a newly created local database named `nexus_ai_p4_it_<suffix>`.
- The Windows acceptance runner uses a separate newly created local app test
  database named `nexus_ai_p4_app_<suffix>` through
  `NEXUS_P4_APP_TEST_DATABASE_URL`. Both databases must be loopback and have no
  user schemas or objects before the runner proceeds. The runner overrides the
  app's normal PostgreSQL environment in child processes; it never prints DSNs
  or their credential fields. Application imports may invoke the existing
  dotenv loader, but the runner supplies explicit PostgreSQL overrides before
  those imports and does not inspect or display `.env` contents.
- PostgreSQL tests create and drop a random isolated schema. The application
  migration suite uses only the dedicated `nexus_ai_p4_app_` database.
- Reports and captured command logs are stored under
  `%LOCALAPPDATA%\NexusAI\reports`, outside the checkout.
- Local E5/Ollama checks run only with `-RunLiveModels`; E5 uses cached local
  weights, and Ollama must already be installed and running. No download is
  attempted. Generated fixtures are diagnostic plumbing, not accuracy evidence.

## Windows command

Create two empty disposable databases on local PostgreSQL, then set their DSNs
in the current PowerShell process without echoing them. Use URL-encoded
credentials if needed. Do not reuse `nexus_ai` or an owner-managed database.

```powershell
$env:NEXUS_P4_TEST_DATABASE_URL = '<loopback PostgreSQL URL for nexus_ai_p4_it_<suffix>>'
$env:NEXUS_P4_APP_TEST_DATABASE_URL = '<loopback PostgreSQL URL for nexus_ai_p4_app_<suffix>>'
.\scripts\Invoke-P4WindowsAcceptance.ps1 -ExpectedCommit '<40-character branch commit SHA>'
```

Add `-RunLiveModels` only when the pinned E5 weights are already cached and the
local Ollama service is available. The report prints PASS, FAIL, SKIPPED, or
BLOCKED per check; any required failure or blocker exits nonzero. The exact
revision check runs before any database preflight or write.

## PDF boundary

On POSIX, the parser subprocess has resource bounds and process-group cleanup.
It retains the host's filesystem and network authority, so it is bounded local
PDF processing rather than a complete hostile-document sandbox. On Windows,
PDF processing remains disabled and fails closed until supported process/job
resource controls are verified on Windows. No claim is made that Job Objects
alone provide filesystem or network containment.

## Evidence status

The environment used to prepare this branch did not provide Windows execution,
a local PostgreSQL service/driver, cached E5, or Ollama. Therefore live Windows,
PostgreSQL, and local-model checks are not run here. Automated fake-adapter and
offline tests are reported separately from owner-side acceptance. Citation
revalidation is performed immediately before return; it is not transactionally
pinned against a concurrent replacement after that check. Formal quality gates
remain pending.
