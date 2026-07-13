[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

New-Item -ItemType Directory -Force -Path 'data\maintenance' | Out-Null
Set-Content -LiteralPath 'data\maintenance\voice-desired-state' -Value 'running' -Encoding ascii
try {
    & (Join-Path $PSScriptRoot 'start-host-bridge-windows.ps1')
    & (Join-Path $PSScriptRoot 'update-windows.ps1')
    & (Join-Path $PSScriptRoot 'bootstrap-openclaw-windows.ps1')
    & (Join-Path $PSScriptRoot 'enable-autonomy-windows.ps1')
    if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
        throw 'Primero ejecuta .\scripts\setup-windows.ps1'
    }
    & '.venv\Scripts\python.exe' -m pip install --disable-pip-version-check -q -r 'voice\requirements.txt'
    if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias actualizadas de Tipi.' }
    $env:PYTHONPATH = Join-Path $ProjectRoot 'voice'
    & '.venv\Scripts\python.exe' -m tipi_voice
}
finally {
    Set-Content -LiteralPath 'data\maintenance\voice-desired-state' -Value 'stopped' -Encoding ascii
}
