[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string] $ExpectedCommit,

    [string] $ExpectedBranch = 'feature/p4-live-integration-hardening',

    [switch] $RunLiveModels
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = (Get-Command python -ErrorAction Stop).Source
$arguments = @(
    (Join-Path $PSScriptRoot 'run_p4_windows_acceptance.py'),
    '--expected-commit', $ExpectedCommit,
    '--expected-branch', $ExpectedBranch
)
if ($RunLiveModels) {
    $arguments += '--run-live-models'
}

# Database checks require two new, empty, loopback databases. The Python runner
# validates both names and catalogs before running migrations or database tests.
# Credentials arrive only through process environment and are never echoed.
& $python @arguments
exit $LASTEXITCODE
