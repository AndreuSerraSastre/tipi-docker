[CmdletBinding()]
param(
    [string]$ImportSecretsFrom = ''
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$dockerBin = 'C:\Program Files\Docker\Docker\resources\bin'
if (Test-Path -LiteralPath $dockerBin) { $env:PATH = "$dockerBin;$env:PATH" }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker Desktop no está instalado.'
}
& (Join-Path $PSScriptRoot 'start-host-bridge-windows.ps1')

function Get-EnvValue([string]$Name) {
    if (-not (Test-Path -LiteralPath '.env')) { return '' }
    $line = [IO.File]::ReadAllLines((Join-Path $ProjectRoot '.env')) |
        Where-Object { $_.StartsWith("$Name=") } |
        Select-Object -First 1
    if (-not $line) { return '' }
    return $line.Substring($Name.Length + 1).Trim()
}

function Set-EnvValue([string]$Name, [string]$Value) {
    $path = Join-Path $ProjectRoot '.env'
    $lines = [Collections.Generic.List[string]]::new()
    if (Test-Path -LiteralPath $path) {
        $lines.AddRange([string[]][IO.File]::ReadAllLines($path))
    }
    $found = $false
    for ($index = 0; $index -lt $lines.Count; $index++) {
        if ($lines[$index].StartsWith("$Name=")) {
            $lines[$index] = "$Name=$Value"
            $found = $true
            break
        }
    }
    if (-not $found) { $lines.Add("$Name=$Value") }
    [IO.File]::WriteAllLines($path, $lines, [Text.UTF8Encoding]::new($false))
}

function Get-EnvValueFromFile([string]$Path, [string]$Name) {
    if (-not (Test-Path -LiteralPath $Path)) { return '' }
    $line = [IO.File]::ReadAllLines((Resolve-Path -LiteralPath $Path)) |
        Where-Object { $_.StartsWith("$Name=") } |
        Select-Object -First 1
    if (-not $line) { return '' }
    return $line.Substring($Name.Length + 1).Trim()
}

function Read-RealtimeKey {
    Write-Host ''
    Write-Host 'OpenAI Realtime necesita una API key además del acceso por código.'
    $secureKey = Read-Host 'OPENAI_REALTIME_API_KEY (no se mostrará)' -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
    try { $key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
    if (-not $key.StartsWith('sk-')) { throw 'La clave de OpenAI no parece válida.' }
    return $key
}

if (-not (Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
    $tokenBytes = [byte[]]::new(32)
    $tokenGenerator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $tokenGenerator.GetBytes($tokenBytes) }
    finally { $tokenGenerator.Dispose() }
    $gatewayToken = ([BitConverter]::ToString($tokenBytes) -replace '-', '').ToLowerInvariant()
    Set-EnvValue 'OPENCLAW_GATEWAY_TOKEN' $gatewayToken
}

New-Item -ItemType Directory -Force -Path 'data\openclaw','data\models','data\voice' | Out-Null
if (-not (Test-Path -LiteralPath 'data\openclaw\openclaw.json')) {
    Copy-Item -LiteralPath 'config\openclaw.json' -Destination 'data\openclaw\openclaw.json'
}

$savedRealtimeKey = Get-EnvValue 'OPENAI_REALTIME_API_KEY'
if (-not $savedRealtimeKey -and $ImportSecretsFrom) {
    $importedRealtimeKey = Get-EnvValueFromFile $ImportSecretsFrom 'OPENAI_REALTIME_API_KEY'
    if ($importedRealtimeKey.StartsWith('sk-')) {
        Set-EnvValue 'OPENAI_REALTIME_API_KEY' $importedRealtimeKey
        $savedRealtimeKey = $importedRealtimeKey
        $importedRealtimeKey = $null
        Write-Host 'API key de Realtime recuperada de la copia de seguridad.' -ForegroundColor Green
    }
}
if (-not $savedRealtimeKey) {
    $savedRealtimeKey = Read-RealtimeKey
    Set-EnvValue 'OPENAI_REALTIME_API_KEY' $savedRealtimeKey
}

$gatewayImage = Get-EnvValue 'OPENCLAW_IMAGE'
$previousPreference = $ErrorActionPreference
$ErrorActionPreference = 'SilentlyContinue'
docker image inspect $gatewayImage *> $null
$imageInspectExit = $LASTEXITCODE
$ErrorActionPreference = $previousPreference
if ($imageInspectExit -ne 0) {
    docker compose pull openclaw-gateway
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'La imagen publicada no esta disponible; construyendo OpenClaw localmente.' -ForegroundColor Yellow
        Set-EnvValue 'OPENCLAW_IMAGE' 'tipi-openclaw:local'
        docker compose build --pull openclaw-gateway
        if ($LASTEXITCODE -ne 0) { throw 'No se pudo descargar ni construir la imagen de OpenClaw.' }
    }
}

docker compose up -d --wait openclaw-gateway
if ($LASTEXITCODE -ne 0) { throw 'OpenClaw no pudo arrancar antes de la autorizacion.' }

$authRaw = docker compose --profile tools run --rm --no-deps openclaw-cli models auth list --json --provider openai | Out-String
$jsonStart = $authRaw.IndexOf('{')
$hasOAuth = $false
if ($jsonStart -ge 0) {
    try {
        $auth = $authRaw.Substring($jsonStart) | ConvertFrom-Json
        $hasOAuth = @($auth.profiles | Where-Object { $_.type -eq 'oauth' }).Count -gt 0
    }
    catch { $hasOAuth = $false }
}
if (-not $hasOAuth) {
    Write-Host ''
    Write-Host 'Paso 1 de 3: inicia sesión con el código que aparecerá a continuación.'
    docker compose --profile tools run --rm --no-deps openclaw-cli `
        models auth login --provider openai --device-code
    if ($LASTEXITCODE -ne 0) { throw 'No se completó el acceso por código.' }
}

if (-not $savedRealtimeKey) {
    $realtimeKey = Read-RealtimeKey
    Set-EnvValue 'OPENAI_REALTIME_API_KEY' $realtimeKey
    $realtimeKey = $null
}

Write-Host ''
Write-Host 'Paso 2 de 3: preparando el reconocimiento y el audio.'
& (Join-Path $PSScriptRoot 'download-model.ps1')
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) { py -3.12 -m venv .venv }
& '.venv\Scripts\python.exe' -m pip install --disable-pip-version-check -q -r 'voice\requirements.txt'
& '.venv\Scripts\python.exe' -m pip install --disable-pip-version-check -q --no-deps -e 'voice'

Write-Host ''
& '.venv\Scripts\python.exe' -m tipi_voice --list-devices
if (-not (Get-EnvValue 'TIPI_INPUT_DEVICE')) {
    Set-EnvValue 'TIPI_INPUT_DEVICE' (Read-Host 'Número o parte del nombre del micrófono')
}
if (-not (Get-EnvValue 'TIPI_OUTPUT_DEVICE')) {
    Set-EnvValue 'TIPI_OUTPUT_DEVICE' (Read-Host 'Número o parte del nombre de los altavoces/auriculares')
}

Write-Host ''
Write-Host 'Paso 3 de 3: arrancando y comprobando Tipi.'
docker compose up -d openclaw-gateway
docker compose --profile tools run --rm --no-deps openclaw-cli models set openai/gpt-5.6-sol
docker compose up -d --force-recreate --wait openclaw-gateway
if ($LASTEXITCODE -ne 0) { throw 'OpenClaw no superó la comprobación de salud.' }
& (Join-Path $PSScriptRoot 'bootstrap-openclaw-windows.ps1')
& (Join-Path $PSScriptRoot 'enable-autonomy-windows.ps1')

& '.venv\Scripts\python.exe' -m tipi_voice --check
if ($LASTEXITCODE -ne 0) {
    $devicesRaw = docker compose --profile tools run --rm --no-deps openclaw-cli devices list --json | Out-String
    $devicesStart = $devicesRaw.IndexOf('{')
    if ($devicesStart -ge 0) {
        $devices = $devicesRaw.Substring($devicesStart) | ConvertFrom-Json
        foreach ($pending in @($devices.pending | Where-Object { $_.displayName -eq 'Tipi Voice' })) {
            docker compose --profile tools run --rm --no-deps openclaw-cli devices approve $pending.requestId
        }
    }
    & '.venv\Scripts\python.exe' -m tipi_voice --check
    if ($LASTEXITCODE -ne 0) { throw 'La comprobación final de Tipi ha fallado.' }
}

Write-Host ''
Write-Host 'Tipi está preparado. Para hablar: .\scripts\start-windows.ps1'
