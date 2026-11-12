[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [switch]$AllowProvisional,
    [string]$Manifest = (Join-Path $env:LOCALAPPDATA 'NexusAI\real-rag-benchmark\dev\bilingual-owner-reviewed.json'),
    [string]$Reviewer = 'reviewer-a',
    [string]$Python = (Join-Path $env:LOCALAPPDATA 'NexusAI\rag-e5-venv\Scripts\python.exe'),
    [string]$Cache = (Join-Path $env:LOCALAPPDATA 'NexusAI\huggingface'),
    [string]$Output = (Join-Path $env:LOCALAPPDATA 'NexusAI\real-rag-benchmark\dev\provisional-windowed-e5-comparison.json')
)
$ErrorActionPreference = 'Stop'
if (-not $AllowProvisional) { throw 'Pass -AllowProvisional to run submitted owner-review labels.' }
$repo = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path -LiteralPath $Manifest -PathType Leaf)) { throw "Manifest not found: $Manifest" }
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw "E5 Python not found: $Python" }
if (-not (Test-Path -LiteralPath $Cache -PathType Container)) { throw "Hugging Face cache not found: $Cache" }
$env:HF_HOME = $Cache
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
Push-Location $repo
try {
    & $Python .\scripts\run_provisional_owner_review_diagnostic.py `
        --manifest $Manifest --allow-provisional --reviewer $Reviewer -k 3 `
        --with-e5 --with-windowed-e5 --window-chars 500 --window-overlap 100 `
        --dense-rrf-weight 0.75 --json-out $Output
    if ($LASTEXITCODE -ne 0) { throw "Provisional diagnostic failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}
