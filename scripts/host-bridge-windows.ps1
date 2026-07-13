[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$dockerBin = 'C:\Program Files\Docker\Docker\resources\bin'
if (Test-Path -LiteralPath $dockerBin) { $env:PATH = "$dockerBin;$env:PATH" }
$BridgeRoot = Join-Path $ProjectRoot 'data\host-bridge'
$Requests = Join-Path $BridgeRoot 'requests'
$Responses = Join-Path $BridgeRoot 'responses'
$LogPath = Join-Path $BridgeRoot 'bridge.log'
$PidPath = Join-Path $BridgeRoot 'bridge.pid'
$ReadyPath = Join-Path $BridgeRoot 'ready.json'
New-Item -ItemType Directory -Force -Path $Requests,$Responses | Out-Null
Set-Content -LiteralPath $PidPath -Value $PID -Encoding ascii

function Write-AtomicJson([string]$Path, [object]$Value) {
    $temporary = "$Path.tmp"
    $json = $Value | ConvertTo-Json -Depth 8
    [IO.File]::WriteAllText($temporary, $json, [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Write-Ready {
    Write-AtomicJson $ReadyPath ([ordered]@{
        pid = $PID
        platform = 'windows'
        projectRoot = $ProjectRoot
        updatedAt = [DateTimeOffset]::Now.ToString('o')
    })
}

try {
    while ($true) {
        Write-Ready
        foreach ($requestPath in @(Get-ChildItem -LiteralPath $Requests -Filter '*.json' -File -ErrorAction SilentlyContinue | Sort-Object CreationTimeUtc)) {
            $started = [DateTimeOffset]::Now
            $request = $null
            $stdoutPath = Join-Path $BridgeRoot "$($requestPath.BaseName).stdout"
            $stderrPath = Join-Path $BridgeRoot "$($requestPath.BaseName).stderr"
            try {
                $request = Get-Content -LiteralPath $requestPath.FullName -Raw -Encoding utf8 | ConvertFrom-Json
                $timeoutSeconds = [Math]::Max(1, [Math]::Min(3600, [int]$request.timeoutSeconds))
                $workingDirectory = if ($request.cwd -and (Test-Path -LiteralPath $request.cwd -PathType Container)) {
                    [string]$request.cwd
                } else {
                    $ProjectRoot
                }
                $process = [Diagnostics.Process]::new()
                $process.StartInfo.FileName = 'powershell.exe'
                $process.StartInfo.Arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -OutputFormat Text -EncodedCommand ' + [string]$request.encodedCommand
                $process.StartInfo.WorkingDirectory = $workingDirectory
                $process.StartInfo.UseShellExecute = $false
                $process.StartInfo.CreateNoWindow = $true
                $process.StartInfo.RedirectStandardOutput = $true
                $process.StartInfo.RedirectStandardError = $true
                $process.StartInfo.StandardOutputEncoding = [Text.Encoding]::UTF8
                $process.StartInfo.StandardErrorEncoding = [Text.Encoding]::UTF8
                $null = $process.Start()
                $stdoutTask = $process.StandardOutput.ReadToEndAsync()
                $stderrTask = $process.StandardError.ReadToEndAsync()
                $finished = $process.WaitForExit($timeoutSeconds * 1000)
                if (-not $finished) {
                    try { $process.Kill() } catch {}
                    $exitCode = 124
                    $timedOut = $true
                } else {
                    $exitCode = $process.ExitCode
                    $timedOut = $false
                }
                $process.WaitForExit()
                $stdout = $stdoutTask.Result
                $stderr = $stderrTask.Result
                $process.Dispose()
            }
            catch {
                $exitCode = 1
                $timedOut = $false
                $stdout = ''
                $stderr = $_.Exception.Message
            }
            $finishedAt = [DateTimeOffset]::Now
            $responsePath = Join-Path $Responses "$($requestPath.BaseName).json"
            Write-AtomicJson $responsePath ([ordered]@{
                id = $requestPath.BaseName
                exitCode = $exitCode
                timedOut = $timedOut
                stdout = $stdout
                stderr = $stderr
                startedAt = $started.ToString('o')
                finishedAt = $finishedAt.ToString('o')
                durationMs = [Math]::Round(($finishedAt - $started).TotalMilliseconds)
            })
            Add-Content -LiteralPath $LogPath -Encoding utf8 -Value (
                "{0} id={1} exit={2} durationMs={3}" -f $finishedAt.ToString('o'),$requestPath.BaseName,$exitCode,[Math]::Round(($finishedAt - $started).TotalMilliseconds)
            )
            Remove-Item -LiteralPath $requestPath.FullName,$stdoutPath,$stderrPath -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Milliseconds 500
    }
}
finally {
    Remove-Item -LiteralPath $ReadyPath,$PidPath -Force -ErrorAction SilentlyContinue
}
