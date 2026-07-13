[CmdletBinding()]
param(
    [switch]$Follow
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LogDirectory = Join-Path $ProjectRoot 'data\logs'
$Latest = Get-ChildItem -LiteralPath $LogDirectory -Filter 'tipi-*.log' -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if (-not $Latest) {
    throw 'Todavía no hay logs. Arranca Tipi y mantén al menos una conversación.'
}

if ($Follow) {
    Write-Host "Mostrando en directo: $($Latest.FullName)" -ForegroundColor Cyan
    Get-Content -LiteralPath $Latest.FullName -Encoding utf8 -Tail 100 -Wait
} else {
    Start-Process -FilePath 'notepad.exe' -ArgumentList $Latest.FullName
}
