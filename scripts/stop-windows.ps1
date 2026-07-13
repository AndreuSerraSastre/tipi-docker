[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot
New-Item -ItemType Directory -Force -Path 'data\maintenance' | Out-Null
Set-Content -LiteralPath 'data\maintenance\voice-desired-state' -Value 'stopped' -Encoding ascii

Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -match 'tipi_voice' -and $_.ExecutablePath -like "$ProjectRoot*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Write-Host 'Tipi Voice detenido; OpenClaw conserva su memoria y su modo cuidador.'
