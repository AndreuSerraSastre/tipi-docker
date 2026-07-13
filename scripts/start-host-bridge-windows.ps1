[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BridgeRoot = Join-Path $ProjectRoot 'data\host-bridge'
$PidPath = Join-Path $BridgeRoot 'bridge.pid'
$ReadyPath = Join-Path $BridgeRoot 'ready.json'
New-Item -ItemType Directory -Force -Path $BridgeRoot | Out-Null

if ((Test-Path -LiteralPath $PidPath) -and (Test-Path -LiteralPath $ReadyPath)) {
    $savedPid = [int](Get-Content -LiteralPath $PidPath -Raw)
    $savedProcess = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
    $readyAge = (Get-Date) - (Get-Item -LiteralPath $ReadyPath).LastWriteTime
    if ($savedProcess -and $readyAge.TotalSeconds -lt 10) { return }
}

Remove-Item -LiteralPath $PidPath,$ReadyPath -Force -ErrorAction SilentlyContinue
$bridgeScript = Join-Path $PSScriptRoot 'host-bridge-windows.ps1'
$process = Start-Process -FilePath 'powershell.exe' -ArgumentList @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$bridgeScript`""
) -WindowStyle Hidden -PassThru

$deadline = (Get-Date).AddSeconds(15)
while ((Get-Date) -lt $deadline) {
    if ((Test-Path -LiteralPath $ReadyPath) -and (Test-Path -LiteralPath $PidPath)) {
        $readyPid = [int](Get-Content -LiteralPath $PidPath -Raw)
        if ($readyPid -eq $process.Id) { return }
    }
    if ($process.HasExited) { throw 'El puente completo de Windows termino durante el arranque.' }
    Start-Sleep -Milliseconds 250
}
throw 'El puente completo de Windows no quedo preparado a tiempo.'
