$ErrorActionPreference = 'Stop'
$pythonExe = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw '尚未安裝執行環境，請依 README 建立 .venv 並安裝 requirements.txt。'
}
$address = 'http://127.0.0.1:8765'
$alreadyRunning = $false
try {
    $status = Invoke-RestMethod -Uri "$address/health" -TimeoutSec 2
    $alreadyRunning = $status.app -eq 'em-mvp'
} catch { }
if (-not $alreadyRunning) {
    $logDirectory = Join-Path $env:USERPROFILE 'Documents\Codex\Environmental_Monitoring_MVP-data\logs'
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    $serverProcess = Start-Process -FilePath $pythonExe -ArgumentList '-m','em_mvp.app' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDirectory 'server.log') -RedirectStandardError (Join-Path $logDirectory 'server-error.log')
    $ready = $false
    for ($attempt=0; $attempt -lt 20; $attempt++) {
        Start-Sleep -Milliseconds 300
        try {
            $status = Invoke-RestMethod -Uri "$address/health" -TimeoutSec 1
            if ($status.app -eq 'em-mvp') { $ready=$true; break }
        } catch { }
        if ($serverProcess.HasExited) { break }
    }
    if (-not $ready) { throw "啟動失敗，請查看 $logDirectory 中的記錄。" }
    $serverProcess.Id | Set-Content -LiteralPath (Join-Path $logDirectory 'server.pid')
}
Start-Process $address
