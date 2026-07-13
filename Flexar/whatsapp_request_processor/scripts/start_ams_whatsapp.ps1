[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "AMS WhatsApp Operations System"

# Resolve every path from this script, never from the user's current directory.
$packageRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$repoRoot = (Resolve-Path (Join-Path $packageRoot "..\..")).Path
$supervisor = Join-Path $PSScriptRoot "ams_supervisor.py"

function Find-AmsPython {
    $candidates = [System.Collections.Generic.List[string]]::new()
    if ($env:VIRTUAL_ENV) { $candidates.Add((Join-Path $env:VIRTUAL_ENV "Scripts\python.exe")) }
    $candidates.Add((Join-Path $repoRoot ".venv\Scripts\python.exe"))
    $candidates.Add((Join-Path $repoRoot "venv\Scripts\python.exe"))
    if ($env:AMS_PYTHON) { $candidates.Add($env:AMS_PYTHON) }

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    $systemPython = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $systemPython) { $systemPython = Get-Command python -ErrorAction SilentlyContinue }
    if ($systemPython) { return $systemPython.Source }
    return $null
}

if (-not (Test-Path -LiteralPath $supervisor -PathType Leaf)) {
    Write-Host "[ERROR] The AMS startup supervisor was not found." -ForegroundColor Red
    Write-Host "Please contact the system administrator."
    exit 1
}

$python = Find-AmsPython
if (-not $python) {
    Write-Host "[ERROR] Python was not found." -ForegroundColor Red
    Write-Host "Please contact the system administrator for the one-time Python setup."
    exit 1
}

Write-Host "[SYSTEM] Python: $python" -ForegroundColor Cyan
Set-Location -LiteralPath $repoRoot
& $python $supervisor --python $python
exit $LASTEXITCODE
