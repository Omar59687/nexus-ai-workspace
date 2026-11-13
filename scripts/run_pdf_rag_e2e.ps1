[CmdletBinding()]
param(
    [switch]$RunLive,
    [string]$Python = (Join-Path $env:LOCALAPPDATA 'NexusAI\rag-e5-venv\Scripts\python.exe'),
    [string]$Cache = (Join-Path $env:LOCALAPPDATA 'NexusAI\huggingface'),
    [string]$Report = (Join-Path $env:LOCALAPPDATA 'NexusAI\reports\pdf-rag-e2e.json')
)
$ErrorActionPreference = 'Stop'
if (-not $RunLive) { throw 'Pass -RunLive to explicitly allow cached E5 and local Ollama execution.' }
$repo = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Configured Nexus E5 Python interpreter is unavailable.' }
if (-not (Test-Path -LiteralPath $Cache -PathType Container)) { throw 'Configured local Hugging Face cache is unavailable.' }
$resolvedPython = (Resolve-Path -LiteralPath $Python).Path
$reportedPython = (& $resolvedPython -c 'import sys; print(sys.executable)').Trim()
if (-not $reportedPython -or [System.IO.Path]::GetFullPath($reportedPython) -ne [System.IO.Path]::GetFullPath($resolvedPython)) {
    throw 'The selected Python interpreter did not report the expected executable.'
}
$env:HF_HOME = $Cache
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$reportDirectory = Split-Path -Parent $Report
New-Item -ItemType Directory -Force -Path $reportDirectory | Out-Null
Push-Location $repo
try {
    & $resolvedPython .\scripts\run_pdf_rag_e2e.py --run-live --report $Report
    if ($LASTEXITCODE -ne 0) { throw "PDF-to-RAG diagnostic returned exit code $LASTEXITCODE. Inspect the JSON report outside the repository." }
    Write-Output "PDF-to-RAG diagnostic completed. Report: $Report"
} finally {
    Pop-Location
}
