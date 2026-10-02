$ErrorActionPreference = 'Stop'
$pidFile = Join-Path $env:USERPROFILE 'Documents\Codex\Environmental_Monitoring_MVP-data\logs\server.pid'
if (-not (Test-Path -LiteralPath $pidFile)) { Write-Output '沒有此啟動程式的服務記錄。'; return }
$serverPid = [int](Get-Content -LiteralPath $pidFile)
$serverProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$serverPid"
$expectedExecutable = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if ($serverProcess -and $serverProcess.ExecutablePath -eq $expectedExecutable -and $serverProcess.CommandLine -match 'em_mvp\.app') {
    Stop-Process -Id $serverPid
    Write-Output 'EM MVP 已停止；資料與備份保留。'
} elseif ($serverProcess) { throw '程序資訊不符，沒有停止其他程式。' }
