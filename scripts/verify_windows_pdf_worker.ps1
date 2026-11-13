$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path -LiteralPath (Join-Path $repoRoot "pyproject.toml"))) {
    throw "Could not locate the repository root from this script path."
}
if ($env:OS -ne "Windows_NT") {
    throw "This acceptance command must run on Windows to verify Job Object enforcement."
}

Push-Location $repoRoot
try {
    $existingPythonPath = $env:PYTHONPATH
    $env:PYTHONPATH = Join-Path $repoRoot "src"
    if ($existingPythonPath) {
        $env:PYTHONPATH += [System.IO.Path]::PathSeparator + $existingPythonPath
    }
    $pythonCommand = Get-Command python -CommandType Application -All -ErrorAction Stop |
        Select-Object -First 1
    if ($null -eq $pythonCommand -or [string]::IsNullOrWhiteSpace($pythonCommand.Source)) {
        throw "No Python application was found on PATH."
    }
    $pythonExecutable = [System.IO.Path]::GetFullPath($pythonCommand.Source)
    $pythonRuntime = & $pythonExecutable -c "import sys; print(sys.executable)"
    if ($LASTEXITCODE -ne 0) {
        throw "Python runtime discovery failed."
    }
    if ([System.IO.Path]::GetFullPath($pythonRuntime.Trim()) -ne [System.IO.Path]::GetFullPath($pythonExecutable)) {
        throw "The selected Python command does not resolve to the interpreter the worker will reuse."
    }
    $pythonVersion = & $pythonExecutable -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    if ($LASTEXITCODE -ne 0) {
        throw "Python is unavailable at the selected executable."
    }
    if ($pythonVersion.Trim() -ne "3.12") {
        throw "Python 3.12 is required; found $($pythonVersion.Trim())."
    }

    & $pythonExecutable -c "import pypdf"
    if ($LASTEXITCODE -ne 0) {
        throw "The repository's pypdf dependency is unavailable in this Python environment."
    }

    Write-Output "Python interpreter: $($pythonRuntime.Trim())"
    Write-Output "Running generated-fixture Windows PDF worker tests with that interpreter."
    & $pythonExecutable -m pytest -q tests/documents/test_pdf_worker.py tests/documents/test_pdf_worker_windows.py
    $testExitCode = $LASTEXITCODE
    if ($testExitCode -ne 0) {
        throw "Windows PDF worker tests failed with exit code $testExitCode."
    }
    Write-Output "PASS: generated-fixture Windows PDF worker tests. No owner documents were read."
}
finally {
    Pop-Location
}
