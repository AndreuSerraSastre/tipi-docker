[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot
$dockerBin = 'C:\Program Files\Docker\Docker\resources\bin'
if (Test-Path -LiteralPath $dockerBin) { $env:PATH = "$dockerBin;$env:PATH" }

& (Join-Path $PSScriptRoot 'start-host-bridge-windows.ps1')

$Marker = 'data\openclaw\workspace\.tipi-autonomy-v1'
$Agents = 'data\openclaw\workspace\AGENTS.md'
$Boot = 'data\openclaw\workspace\BOOT.md'
$Heartbeat = 'data\openclaw\workspace\HEARTBEAT.md'
$Lessons = 'data\openclaw\workspace\CARETAKER_LESSONS.md'
$FingerprintFiles = @(
    'config\tipi-autonomy-request.md',
    'workspace\AGENTS.md',
    'workspace\BOOT.md',
    'workspace\HEARTBEAT.md',
    'workspace\CARETAKER_LESSONS.md'
)
$AutonomyFingerprint = ($FingerprintFiles | ForEach-Object {
    (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash.ToLowerInvariant()
}) -join ':'
$AlreadyConfigured = (Test-Path -LiteralPath $Marker) -and `
    ((Get-Content -LiteralPath $Marker -Raw -Encoding ascii).Trim() -eq $AutonomyFingerprint) -and `
    (Test-Path -LiteralPath $Agents) -and `
    ((Get-Content -LiteralPath $Agents -Raw -Encoding utf8) -match 'TIPI_AUTONOMY_V1') -and `
    (Test-Path -LiteralPath $Boot) -and (Test-Path -LiteralPath $Heartbeat) -and `
    (Test-Path -LiteralPath $Lessons)
if ($AlreadyConfigured) { return }

docker compose --profile tools run --rm --no-deps openclaw-cli exec-policy preset yolo
if ($LASTEXITCODE -ne 0) { throw 'No se pudo activar la ejecución autónoma completa.' }
docker compose --profile tools run --rm --no-deps openclaw-cli hooks enable boot-md
if ($LASTEXITCODE -ne 0) { throw 'No se pudo activar la revisión de arranque de OpenClaw.' }

New-Item -ItemType Directory -Force -Path 'data\maintenance' | Out-Null
$Request = Get-Content -LiteralPath 'config\tipi-autonomy-request.md' -Raw -Encoding utf8
$thinkingLine = [IO.File]::ReadAllLines((Join-Path $ProjectRoot '.env')) |
    Where-Object { $_.StartsWith('TIPI_OPENCLAW_THINKING=') } |
    Select-Object -First 1
$thinking = if ($thinkingLine) { $thinkingLine.Substring('TIPI_OPENCLAW_THINKING='.Length).Trim() } else { 'low' }
Write-Host 'OpenClaw está creando y probando su modo cuidador...' -ForegroundColor Cyan
docker compose --profile tools run --rm --no-deps openclaw-cli agent `
    --session-key 'agent:main:tipi-autonomy-setup' `
    --thinking $thinking `
    --timeout 600 `
    --message $Request
if ($LASTEXITCODE -ne 0) { throw 'OpenClaw no pudo completar la configuración de autocuidado.' }

$Configured = (Test-Path -LiteralPath $Agents) -and `
    ((Get-Content -LiteralPath $Agents -Raw -Encoding utf8) -match 'TIPI_AUTONOMY_V1') -and `
    (Test-Path -LiteralPath $Boot) -and (Test-Path -LiteralPath $Heartbeat) -and `
    (Test-Path -LiteralPath $Lessons)
if (-not $Configured) { throw 'OpenClaw terminó, pero no dejó completas sus órdenes de autocuidado.' }

Set-Content -LiteralPath $Marker -Value $AutonomyFingerprint -Encoding ascii
Write-Host 'Modo cuidador autónomo preparado y verificado.' -ForegroundColor Green
