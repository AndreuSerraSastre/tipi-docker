[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ModelName = 'vosk-model-small-es-0.42'
$ModelDir = Join-Path $ProjectRoot "data\models\$ModelName"
if (Test-Path -LiteralPath $ModelDir) {
    return
}

$Url = "https://alphacephei.com/vosk/models/$ModelName.zip"
$ExpectedSha256 = '09b239888f633ef2f0b4e09736e3d9936acfd810bc65d53fad45261762c6511f'
$Archive = Join-Path ([IO.Path]::GetTempPath()) "$ModelName.zip"

Write-Host 'Descargando el modelo local de activación (39 MB)...'
Invoke-WebRequest -Uri $Url -OutFile $Archive
$Actual = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($Actual -ne $ExpectedSha256) {
    Remove-Item -LiteralPath $Archive -Force
    throw "El modelo descargado no supera la verificación SHA-256: $Actual"
}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ModelDir) | Out-Null
Expand-Archive -LiteralPath $Archive -DestinationPath (Split-Path -Parent $ModelDir) -Force
Remove-Item -LiteralPath $Archive -Force

