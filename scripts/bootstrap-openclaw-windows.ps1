[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot
$dockerBin = 'C:\Program Files\Docker\Docker\resources\bin'
if (Test-Path -LiteralPath $dockerBin) { $env:PATH = "$dockerBin;$env:PATH" }
$Marker = 'data\openclaw\workspace\.tipi-bootstrap-v1'
$Workspace = 'data\openclaw\workspace'
$Attestation = 'data\openclaw\workspace-attestations\cddce8bd7eebfe25e3f3e5cf0f37a0822fa900fa1864cc27b3e2d6b7e3fb6b4b.attested'

if (Test-Path -LiteralPath $Marker) { return }

# Migración desde la antigua carpeta superpuesta: solo se retira la atestación
# de esta ruta concreta cuando el nuevo workspace está realmente vacío.
$WorkspaceEntries = @(Get-ChildItem -LiteralPath $Workspace -Force -ErrorAction SilentlyContinue)
if ((Test-Path -LiteralPath $Attestation) -and $WorkspaceEntries.Count -eq 0) {
    Remove-Item -LiteralPath $Attestation -Force
}

function Invoke-BootstrapTurn([string]$Message) {
    docker compose --profile tools run --rm --no-deps openclaw-cli agent `
        --session-key 'agent:main:tipi-onboarding' `
        --thinking medium `
        --timeout 300 `
        --message $Message
    if ($LASTEXITCODE -ne 0) { throw 'OpenClaw no pudo completar el diálogo inicial de Tipi.' }
}

Write-Host ''
Write-Host 'OpenClaw va a conocer a Tipi mediante su conversación inicial.' -ForegroundColor Cyan
Invoke-BootstrapTurn 'Hola. Acabas de iniciar por primera vez. Sigue tu ritual de BOOTSTRAP.md: preséntate y hazme las preguntas necesarias para descubrir quién eres, quién soy y para qué has sido creado. Todavía no escribas las respuestas por mí.'

Write-Host 'Respondiendo automáticamente con la información del proyecto Tipi...' -ForegroundColor Cyan
$Answers = Get-Content -LiteralPath 'config\tipi-bootstrap-answers.md' -Raw -Encoding utf8
Invoke-BootstrapTurn $Answers

$Identity = Join-Path $Workspace 'IDENTITY.md'
$User = Join-Path $Workspace 'USER.md'
$Memory = Join-Path $Workspace 'MEMORY.md'
$Bootstrap = Join-Path $Workspace 'BOOTSTRAP.md'
$Configured = (Test-Path $Identity) -and (Test-Path $User) -and (Test-Path $Memory) -and `
    ((Get-Content $Identity -Raw -Encoding utf8) -match 'Tipi') -and `
    ((Get-Content $User -Raw -Encoding utf8) -match 'Andreu') -and `
    -not (Test-Path $Bootstrap)

if (-not $Configured) {
    Invoke-BootstrapTurn 'Finaliza ahora el onboarding: escribe IDENTITY.md, USER.md, SOUL.md y una MEMORY.md pública con lo que ya te he explicado; crea la nota diaria de memoria y elimina BOOTSTRAP.md. Después confirma brevemente que has terminado.'
}

$Configured = (Test-Path $Identity) -and (Test-Path $User) -and (Test-Path $Memory) -and `
    ((Get-Content $Identity -Raw -Encoding utf8) -match 'Tipi') -and `
    ((Get-Content $User -Raw -Encoding utf8) -match 'Andreu') -and `
    -not (Test-Path $Bootstrap)
if (-not $Configured) { throw 'OpenClaw terminó el diálogo, pero no dejó completa la identidad y memoria de Tipi.' }

Set-Content -LiteralPath $Marker -Value 'tipi-bootstrap-v1' -Encoding ascii
Write-Host 'OpenClaw ya conoce su identidad, a Andreu y el propósito de Tipi.' -ForegroundColor Green
