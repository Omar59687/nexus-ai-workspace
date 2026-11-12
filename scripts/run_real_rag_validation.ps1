[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $Fixture,
    [ValidateSet("dev", "holdout")]
    [string] $Split = "dev",
    [ValidateRange(1, 1000)]
    [int] $K = 5,
    [switch] $AllowHoldout,
    [switch] $WithE5,
    [switch] $MeasureLatency,
    [string] $JsonOut
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$fixturePath = (Resolve-Path $Fixture).Path

if ($Split -eq "holdout" -and -not $AllowHoldout) {
    throw "Holdout is protected. Freeze the strategy first, then pass -AllowHoldout explicitly."
}
if ($Split -eq "dev" -and $AllowHoldout) {
    throw "-AllowHoldout is only valid with -Split holdout."
}
if ($Split -eq "holdout") {
    $relativeFixture = [System.IO.Path]::GetRelativePath($repositoryRoot, $fixturePath)
    $separator = [System.IO.Path]::DirectorySeparatorChar
    $isInsideRepository = -not [System.IO.Path]::IsPathRooted($relativeFixture) -and
        $relativeFixture -ne ".." -and -not $relativeFixture.StartsWith(".." + $separator)
    if ($isInsideRepository) {
        throw "Keep protected holdout fixtures outside the repository working tree."
    }
}

$arguments = @(
    (Join-Path $repositoryRoot "scripts/run_rag_eval.py"),
    "--fixture", $fixturePath,
    "--split", $Split,
    "-k", $K
)
if ($AllowHoldout) { $arguments += "--allow-holdout" }
if ($WithE5) { $arguments += "--with-e5" }
if ($MeasureLatency) { $arguments += "--measure-latency" }
if ($JsonOut) { $arguments += @("--json-out", $JsonOut) }

Push-Location $repositoryRoot
try {
    & python @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "RAG validation failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
