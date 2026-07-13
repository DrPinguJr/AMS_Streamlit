[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$packageRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$repoRoot = (Resolve-Path (Join-Path $packageRoot "..\..")).Path
$supervisor = Join-Path $PSScriptRoot "ams_supervisor.py"

function Find-AmsPython {
    $candidates = @()
    if ($env:VIRTUAL_ENV) { $candidates += (Join-Path $env:VIRTUAL_ENV "Scripts\python.exe") }
    $candidates += (Join-Path $repoRoot ".venv\Scripts\python.exe")
    $candidates += (Join-Path $repoRoot "venv\Scripts\python.exe")
    if ($env:AMS_PYTHON) { $candidates += $env:AMS_PYTHON }
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

$python = Find-AmsPython
if (-not $python) {
    Write-Host "[ERROR] Python was not found, so recorded AMS processes could not be verified safely." -ForegroundColor Red
    exit 1
}

Set-Location -LiteralPath $repoRoot
& $python $supervisor --stop --python $python
exit $LASTEXITCODE
