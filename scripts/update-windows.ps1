[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot
$dockerBin = 'C:\Program Files\Docker\Docker\resources\bin'
if (Test-Path -LiteralPath $dockerBin) { $env:PATH = "$dockerBin;$env:PATH" }

$deadline = (Get-Date).AddMinutes(3)
while ($true) {
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'SilentlyContinue'
    docker version --format '{{.Server.Version}}' *> $null
    $dockerInfoExit = $LASTEXITCODE
    $ErrorActionPreference = $previousPreference
    if ($dockerInfoExit -eq 0) { break }
    if ((Get-Date) -gt $deadline) { throw 'Docker Desktop no ha arrancado en tres minutos.' }
    Start-Sleep -Seconds 3
}

$imageLine = [IO.File]::ReadAllLines((Join-Path $ProjectRoot '.env')) |
    Where-Object { $_.StartsWith('OPENCLAW_IMAGE=') } |
    Select-Object -First 1
$openclawImage = if ($imageLine) { $imageLine.Substring('OPENCLAW_IMAGE='.Length).Trim() } else { '' }
$oldImage = if ($openclawImage) {
    docker image inspect $openclawImage --format '{{.Id}}' 2>$null
} else { '' }

$isLocalImage = $openclawImage.EndsWith(':local')
if ($isLocalImage) {
    docker compose build --pull openclaw-gateway
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo comprobar la actualizacion local de OpenClaw.' }
} else {
    docker compose pull openclaw-gateway
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo comprobar la actualización de OpenClaw.' }
}

docker compose up -d --wait --remove-orphans openclaw-gateway
if ($LASTEXITCODE -ne 0) {
    if (-not $oldImage) { throw 'La actualización no arrancó y no existe una imagen anterior.' }
    Write-Warning 'La actualización falló. Recuperando la imagen anterior de OpenClaw.'
    $env:OPENCLAW_IMAGE = $oldImage.Trim()
    docker compose -f compose.yaml -f compose.rollback.yaml up -d --wait openclaw-gateway
    if ($LASTEXITCODE -ne 0) { throw 'También falló la recuperación automática.' }
}
