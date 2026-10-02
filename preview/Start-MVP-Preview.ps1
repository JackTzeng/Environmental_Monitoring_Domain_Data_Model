$ErrorActionPreference = 'Stop'

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$PreviewId = 'EM-MVP-Preview-EM008-20261002'
$Port = 8876
$Url = "http://127.0.0.1:$Port"
$DataDir = Join-Path $env:USERPROFILE "AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\Codex\$PreviewId"
$ManifestPath = Join-Path $DataDir 'preview-seed.json'
$LaunchPath = Join-Path $DataDir 'preview-launch.json'
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$RuntimePython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$Netstat = Join-Path $env:SystemRoot 'System32\netstat.exe'

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "找不到專案 Python：$Python"
}
if (-not (Test-Path -LiteralPath $Netstat -PathType Leaf)) {
    throw "找不到 Windows TCP listener 查詢工具：$Netstat"
}
if (-not (Test-Path -LiteralPath $RuntimePython -PathType Leaf)) {
    throw "找不到預覽服務的 Codex runtime Python：$RuntimePython"
}

function Same-Path([string]$Actual, [string]$Expected) {
    if (-not $Actual) { return $false }
    return [string]::Equals([System.IO.Path]::GetFullPath($Actual),
        [System.IO.Path]::GetFullPath($Expected), [StringComparison]::OrdinalIgnoreCase)
}

function Has-AppCommand($ProcessInfo) {
    return ($ProcessInfo.CommandLine -match '(?:^|\s)-m\s+em_mvp\.app(?:\s|$)' -and
        $ProcessInfo.CommandLine -match "(?:^|\s)--port\s+$Port(?:\s|$)")
}

function Find-PreviewChild([int]$LauncherPid) {
    $launcherInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $LauncherPid"
    if (-not $launcherInfo -or -not (Same-Path $launcherInfo.ExecutablePath $Python) -or
        -not (Has-AppCommand $launcherInfo)) { return $null }
    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $LauncherPid" |
        Where-Object { (Same-Path $_.ExecutablePath $RuntimePython) -and (Has-AppCommand $_) })
    if ($children.Count -ne 1) { return $null }
    return $children[0]
}

function Stop-StartedPreview([int]$LauncherPid) {
    $ownedChild = Find-PreviewChild $LauncherPid
    Stop-Process -Id $LauncherPid -Force -ErrorAction SilentlyContinue
    if ($ownedChild) {
        Start-Sleep -Milliseconds 300
        $childNow = Get-CimInstance Win32_Process -Filter "ProcessId = $($ownedChild.ProcessId)"
        if ($childNow -and [int]$childNow.ParentProcessId -eq $LauncherPid -and
            (Same-Path $childNow.ExecutablePath $RuntimePython) -and (Has-AppCommand $childNow)) {
            Stop-Process -Id ([int]$ownedChild.ProcessId) -Force -ErrorAction SilentlyContinue
        }
    }
}

function Find-PreviewListener([int]$ListenPort, [int]$ProcessId) {
    $matchesForPort = @()
    foreach ($line in @(& $Netstat -ano -p tcp 2>$null)) {
        if ($line -match '^\s*TCP\s+(\S+):(\d+)\s+\S+\s+LISTENING\s+(\d+)\s*$' -and
            [int]$matches[2] -eq $ListenPort) {
            $matchesForPort += [pscustomobject]@{ LocalAddress = $matches[1]; LocalPort = $ListenPort;
                                                  OwningProcess = [int]$matches[3] }
        }
    }
    if ($matchesForPort.Count -eq 1 -and $matchesForPort[0].LocalAddress -eq '127.0.0.1' -and
        $matchesForPort[0].OwningProcess -eq $ProcessId) { return $matchesForPort[0] }
    return $null
}

$listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
$portListeners = @(& $Netstat -ano -p tcp 2>$null | Where-Object {
    $_ -match "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+\d+\s*$"
})
if ($listeners.Count -gt 0 -or $portListeners.Count -gt 0) {
    throw "連接埠 $Port 已有 listener；為避免連到其他服務，沒有啟動預覽。"
}

if (-not (Test-Path -LiteralPath $DataDir -PathType Container)) {
    & $Python (Join-Path $PSScriptRoot 'seed_preview.py') --data-dir $DataDir
    if ($LASTEXITCODE -ne 0) { throw "合成預覽資料建立失敗，exit code $LASTEXITCODE。" }
}

if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf) -or
    -not (Test-Path -LiteralPath (Join-Path $DataDir 'em.sqlite3') -PathType Leaf)) {
    throw "預覽資料目錄缺少識別檔或 SQLite；為避免接管既有資料，停止：$DataDir"
}
$seed = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
$resolvedDataDir = (Resolve-Path -LiteralPath $DataDir).Path
$manifestDataDir = [System.IO.Path]::GetFullPath([string]$seed.data_dir)
if ($seed.preview_id -ne $PreviewId -or $seed.synthetic_only -ne $true -or
    -not [string]::Equals($resolvedDataDir, $manifestDataDir, [StringComparison]::OrdinalIgnoreCase)) {
    throw "預覽資料識別不符；沒有啟動服務：$DataDir"
}

$LogDir = Join-Path $DataDir 'logs'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$StdoutLog = Join-Path $LogDir 'preview.stdout.log'
$StderrLog = Join-Path $LogDir 'preview.stderr.log'
$stdoutBefore = if (Test-Path -LiteralPath $StdoutLog) { (Get-Item -LiteralPath $StdoutLog).Length } else { 0 }

$oldDataDir = $env:EM_MVP_DATA_DIR
$oldGoogleId = $env:EM_MVP_GOOGLE_CLIENT_ID
$oldGoogleSecret = $env:EM_MVP_GOOGLE_CLIENT_SECRET
$service = $null
try {
    $env:EM_MVP_DATA_DIR = $resolvedDataDir
    Remove-Item Env:EM_MVP_GOOGLE_CLIENT_ID -ErrorAction SilentlyContinue
    Remove-Item Env:EM_MVP_GOOGLE_CLIENT_SECRET -ErrorAction SilentlyContinue
    $service = Start-Process -FilePath $Python `
        -ArgumentList @('-m', 'em_mvp.app', '--port', [string]$Port) `
        -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $StdoutLog -RedirectStandardError $StderrLog
}
finally {
    if ($null -eq $oldDataDir) { Remove-Item Env:EM_MVP_DATA_DIR -ErrorAction SilentlyContinue }
    else { $env:EM_MVP_DATA_DIR = $oldDataDir }
    if ($null -eq $oldGoogleId) { Remove-Item Env:EM_MVP_GOOGLE_CLIENT_ID -ErrorAction SilentlyContinue }
    else { $env:EM_MVP_GOOGLE_CLIENT_ID = $oldGoogleId }
    if ($null -eq $oldGoogleSecret) { Remove-Item Env:EM_MVP_GOOGLE_CLIENT_SECRET -ErrorAction SilentlyContinue }
    else { $env:EM_MVP_GOOGLE_CLIENT_SECRET = $oldGoogleSecret }
}

$deadline = (Get-Date).AddSeconds(20)
$health = $null
$boundListener = $null
$listenerProcess = $null
$startupLine = $null
while ((Get-Date) -lt $deadline) {
    $service.Refresh()
    if ($service.HasExited) {
        $errorText = if (Test-Path -LiteralPath $StderrLog) { Get-Content -LiteralPath $StderrLog -Raw } else { '' }
        throw "預覽服務提早結束，exit code $($service.ExitCode)。$errorText"
    }
    try { $health = Invoke-RestMethod -Uri "$Url/health" -TimeoutSec 1 }
    catch { $health = $null }
    $listenerProcess = Find-PreviewChild $service.Id
    if ($listenerProcess) { $boundListener = Find-PreviewListener $Port ([int]$listenerProcess.ProcessId) }
    if (Test-Path -LiteralPath $StdoutLog) {
        $logText = Get-Content -LiteralPath $StdoutLog -Raw
        $newLogText = if ($stdoutBefore -lt $logText.Length) { $logText.Substring($stdoutBefore) } else { $logText }
        $startupLine = ($newLogText -split "`r?`n" | Where-Object { $_ -like "EM MVP: $Url | data: *" } | Select-Object -First 1)
    }
    if ($health -and $boundListener -and $startupLine -like "EM MVP: $Url | data: $resolvedDataDir") { break }
    Start-Sleep -Milliseconds 250
}

$listenerProcess = Find-PreviewChild $service.Id
$boundListener = if ($listenerProcess) { Find-PreviewListener $Port ([int]$listenerProcess.ProcessId) } else { $null }
$launcherInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $($service.Id)"
$processInfo = if ($listenerProcess) {
    Get-CimInstance Win32_Process -Filter "ProcessId = $($listenerProcess.ProcessId)"
} else { $null }
if (-not $health -or $health.app -ne 'em-mvp' -or $health.version -ne '0.6.0' -or
    $health.parser_version -ne $seed.parser_version) {
    Stop-StartedPreview $service.Id
    throw '健康檢查未回報預期的 app／parser 版本；已停止本次啟動的程序。'
}
if (-not $boundListener -or $boundListener.LocalAddress -ne '127.0.0.1' -or
    -not $launcherInfo -or -not (Same-Path $launcherInfo.ExecutablePath $Python) -or
    -not (Has-AppCommand $launcherInfo) -or
    -not $processInfo -or -not (Same-Path $processInfo.ExecutablePath $RuntimePython) -or
    [int]$processInfo.ParentProcessId -ne $service.Id -or -not (Has-AppCommand $processInfo) -or
    $startupLine -ne "EM MVP: $Url | data: $resolvedDataDir") {
    $portListenerEvidence = @(& $Netstat -ano -p tcp 2>$null | Where-Object {
        $_ -match ":$Port\s"
    })
    $listenRows = @(& $Netstat -ano -p tcp 2>$null | Where-Object {
        $_ -match "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+\d+\s*$"
    })
    $processSnapshot = @(Get-CimInstance Win32_Process)
    $processById = @{}
    foreach ($process in $processSnapshot) { $processById[[int]$process.ProcessId] = $process }
    $ownerChains = @()
    foreach ($line in $listenRows) {
        if ($line -match '^\s*TCP\s+(\S+):(\d+)\s+\S+\s+LISTENING\s+(\d+)\s*$') {
            $ownerPid = [int]$matches[3]
            $chain = @()
            for ($depth = 0; $depth -lt 8 -and $ownerPid -gt 0; $depth++) {
                $ownerProcess = $processById[$ownerPid]
                if (-not $ownerProcess) { break }
                $chain += [pscustomobject]@{ ProcessId = [int]$ownerProcess.ProcessId;
                    ParentProcessId = [int]$ownerProcess.ParentProcessId; Name = $ownerProcess.Name;
                    ExecutablePath = $ownerProcess.ExecutablePath; CommandLine = $ownerProcess.CommandLine }
                $ownerPid = [int]$ownerProcess.ParentProcessId
            }
            $ownerChains += ,@{ listener_row = $line; process_chain = $chain }
        }
    }
    $diagnostic = [ordered]@{
        service_pid = $service.Id
        expected_launcher_executable = $Python
        expected_listener_executable = $RuntimePython
        launcher_parent_pid = $service.Id
        actual_executable = if ($processInfo) { $processInfo.ExecutablePath } else { $null }
        command_line = if ($processInfo) { $processInfo.CommandLine } else { $null }
        listener = if ($boundListener) { @($boundListener | Select-Object LocalAddress,LocalPort,OwningProcess) } else { @() }
        netstat_port_rows = $portListenerEvidence
        listener_process_chains = $ownerChains
        service_process = if ($processInfo) { @($processInfo | Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine) } else { @() }
        startup_line = $startupLine
        expected_startup_line = "EM MVP: $Url | data: $resolvedDataDir"
    } | ConvertTo-Json -Compress -Depth 8
    Stop-StartedPreview $service.Id
    throw "本機 listener／程序／資料路徑證據不符；已停止本次啟動的程序。診斷：$diagnostic"
}

$launch = [ordered]@{
    preview_id = $PreviewId
    pid = [int]$processInfo.ProcessId
    launcher_pid = $service.Id
    parent_pid = [int]$processInfo.ParentProcessId
    launcher_executable = $launcherInfo.ExecutablePath
    executable = $processInfo.ExecutablePath
    port = $Port
    local_address = $boundListener.LocalAddress
    url = $Url
    data_dir = $resolvedDataDir
    app_version = $health.version
    parser_version = $health.parser_version
    started_at = (Get-Date).ToUniversalTime().ToString('o')
}
$launch | ConvertTo-Json | Set-Content -LiteralPath $LaunchPath -Encoding UTF8
Start-Process $Url
$launch | ConvertTo-Json
