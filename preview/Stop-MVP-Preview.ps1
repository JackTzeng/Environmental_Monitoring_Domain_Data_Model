$ErrorActionPreference = 'Stop'

$PreviewId = 'EM-MVP-Preview-EM008-20261002'
$Port = 8876
$DataDir = Join-Path $env:USERPROFILE "AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\Codex\$PreviewId"
$LaunchPath = Join-Path $DataDir 'preview-launch.json'
$Python = [System.IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $PSScriptRoot) '.venv\Scripts\python.exe'))
$RuntimePython = [System.IO.Path]::GetFullPath((Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'))
$Netstat = Join-Path $env:SystemRoot 'System32\netstat.exe'

if (-not (Test-Path -LiteralPath $LaunchPath -PathType Leaf)) {
    throw "沒有預覽啟動識別檔；未停止任何程序：$LaunchPath"
}
$launch = Get-Content -LiteralPath $LaunchPath -Raw | ConvertFrom-Json
if ($launch.preview_id -ne $PreviewId -or $launch.port -ne $Port -or
    $launch.local_address -ne '127.0.0.1' -or $launch.url -ne "http://127.0.0.1:$Port" -or
    -not [string]::Equals([System.IO.Path]::GetFullPath([string]$launch.data_dir),
        [System.IO.Path]::GetFullPath($DataDir), [StringComparison]::OrdinalIgnoreCase) -or
    -not [string]::Equals([System.IO.Path]::GetFullPath([string]$launch.launcher_executable), $Python,
        [StringComparison]::OrdinalIgnoreCase) -or
    -not [string]::Equals([System.IO.Path]::GetFullPath([string]$launch.executable), $RuntimePython,
        [StringComparison]::OrdinalIgnoreCase) -or
    [int]$launch.parent_pid -ne [int]$launch.launcher_pid) {
    throw '啟動識別資訊不符；未停止任何程序。'
}

$launcherPid = [int]$launch.launcher_pid
$servicePid = [int]$launch.pid
$launcherInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $launcherPid"
$processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $servicePid"
$listenerRows = @()
foreach ($line in @(& $Netstat -ano -p tcp 2>$null)) {
    if ($line -match '^\s*TCP\s+(\S+):(\d+)\s+\S+\s+LISTENING\s+(\d+)\s*$' -and
        [int]$matches[2] -eq $Port) {
        $listenerRows += [pscustomobject]@{ LocalAddress = $matches[1]; LocalPort = $Port;
                                            OwningProcess = [int]$matches[3] }
    }
}
function Has-AppCommand($Process) {
    return ($Process.CommandLine -match '(?:^|\s)-m\s+em_mvp\.app(?:\s|$)' -and
        $Process.CommandLine -match "(?:^|\s)--port\s+$Port(?:\s|$)")
}
if (-not $launcherInfo -or
    -not [string]::Equals([System.IO.Path]::GetFullPath([string]$launcherInfo.ExecutablePath), $Python,
        [StringComparison]::OrdinalIgnoreCase) -or -not (Has-AppCommand $launcherInfo) -or
    -not $processInfo -or
    -not [string]::Equals([System.IO.Path]::GetFullPath([string]$processInfo.ExecutablePath), $RuntimePython,
        [StringComparison]::OrdinalIgnoreCase) -or
    [int]$processInfo.ParentProcessId -ne $launcherPid -or -not (Has-AppCommand $processInfo) -or
    $listenerRows.Count -ne 1 -or $listenerRows[0].LocalAddress -ne '127.0.0.1' -or
    $listenerRows[0].OwningProcess -ne $servicePid) {
    throw '程序或 loopback listener 與預覽啟動記錄不一致；未停止任何程序。'
}

Stop-Process -Id $launcherPid -Force
$deadline = (Get-Date).AddSeconds(10)
do {
    Start-Sleep -Milliseconds 200
    $launcherInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $launcherPid"
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $servicePid"
} while ((Get-Date) -lt $deadline -and ($launcherInfo -or $processInfo))
if ($processInfo -and [int]$processInfo.ParentProcessId -eq $launcherPid -and
    [string]::Equals([System.IO.Path]::GetFullPath([string]$processInfo.ExecutablePath), $RuntimePython,
        [StringComparison]::OrdinalIgnoreCase) -and (Has-AppCommand $processInfo)) {
    Stop-Process -Id $servicePid -Force
}
$deadline = (Get-Date).AddSeconds(10)
do {
    Start-Sleep -Milliseconds 200
    $launcherInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $launcherPid"
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $servicePid"
    $remainingListeners = @(& $Netstat -ano -p tcp 2>$null | Where-Object {
        $_ -match "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+\d+\s*$"
    })
} while ((Get-Date) -lt $deadline -and ($launcherInfo -or $processInfo -or $remainingListeners.Count))
if ($launcherInfo -or $processInfo -or $remainingListeners.Count) {
    throw '預覽程序停止後仍有程序或 listener；保留啟動識別檔供檢查。'
}
Remove-Item -LiteralPath $LaunchPath -Force
"Stopped preview launcher PID $launcherPid and listener PID $servicePid on 127.0.0.1:$Port. Data remains at $DataDir."
