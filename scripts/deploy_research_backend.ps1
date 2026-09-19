# Deploy Adaptive through a version-checked, single-instance transaction.
[CmdletBinding()]
param(
    [switch]$PrepareOnly,
    [switch]$VerifyOnly,
    [switch]$RecoverUnresponsive,
    [switch]$AllowTradingWindowOverride,
    [string]$PreparedManifest = ''
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$workspaceRoot = Split-Path -Parent $projectRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$taskName = 'QuantAI_AdaptiveBackend'
$runtimeConfigPath = Join-Path $workspaceRoot 'config\runtime.env'
function Get-RuntimeValue([string]$Key, [string]$Fallback) {
    if (-not (Test-Path -LiteralPath $runtimeConfigPath -PathType Leaf)) { return $Fallback }
    foreach ($line in Get-Content -LiteralPath $runtimeConfigPath) {
        $text = $line.Trim()
        if (-not $text -or $text.StartsWith('#') -or $text.IndexOf('=') -lt 1) { continue }
        $index = $text.IndexOf('=')
        if ($text.Substring(0, $index).Trim() -eq $Key) {
            return $text.Substring($index + 1).Trim().Trim('"').Trim("'")
        }
    }
    return $Fallback
}
$port = [int](Get-RuntimeValue 'ADAPTIVE_API_PORT' '8888')
$runtimeRoot = Join-Path $projectRoot 'runtime'
$releaseRoot = Join-Path $runtimeRoot 'releases'
$activeManifest = Join-Path $runtimeRoot 'active-manifest.json'
$maintenancePath = Join-Path $runtimeRoot 'maintenance.json'
$lockPath = Join-Path $runtimeRoot 'deployment.lock'
$reportRoot = Join-Path $projectRoot 'test-reports\luna-deployment-consistency-20260906'
$reportPath = Join-Path $reportRoot 'deployment-latest.json'
$report = [ordered]@{
    started_at = (Get-Date).ToString('o')
    status = 'incomplete'
    mode = if ($PrepareOnly) { 'prepare' } elseif ($VerifyOnly) { 'verify' } else { 'deploy' }
    expected_release_id = $null
    expected_artifact_hash = $null
    actual_release_id = $null
    actual_artifact_hash = $null
    old_pid = $null
    new_pid = $null
    old_process_started_at = $null
    watchdog_pids = @()
    watchdog_started_pid = $null
    watchdog_stopped = $false
    new_process_started_at = $null
    contract_adopted = $false
    maintenance_entered = $false
    port_released = $false
    runtime_verified = $false
    scanner_behavior_verified = $false
    rollback_attempted = $false
    rollback_verified = $false
    rollback_unavailable = $false
    ai_production_run_verified = $false
    frontend_status = 'not_installed'
    frontend_vsix = $null
    frontend_version = $null
    task_name = $taskName
    task_status = 'unknown'
    task_status_check_attempts = 0
    error = $null
}
$reportEvidencePath = Join-Path $reportRoot ("deployment-" + ([datetime]$report.started_at).ToString('yyyyMMdd-HHmmss') + "-" + $report.mode + ".json")
$lockStream = $null
$previousManifest = $null

function Write-AtomicJson([string]$Path, [object]$Value) {
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $temporary = "$Path.$PID.tmp"
    [IO.File]::WriteAllText($temporary, ($Value | ConvertTo-Json -Depth 12), [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Save-Report {
    $report.finished_at = (Get-Date).ToString('o')
    Write-AtomicJson $reportPath $report
    Write-AtomicJson $reportEvidencePath $report
}

function Get-Listener {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
}

function Get-ProcessRecord([int]$ProcessId) {
    Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
}

function Assert-ExpectedApi([object]$ProcessRecord) {
    if (-not $ProcessRecord -or $ProcessRecord.Name -notmatch '^python(w)?\.exe$') {
        throw "port $port is not owned by the expected Adaptive run_api.py process."
    }
    if ($ProcessRecord.CommandLine -match 'scripts[\\/]run_api\.py') { return }

    # Processes launched by Task Scheduler run in a protected session, so a
    # non-elevated deploy cannot read their command line. Recovery is still safe
    # when the listener belongs to the verified PowerShell -> svchost watchdog
    # chain used by the managed backend task.
    $verifiedWatchdogs = @(Get-VerifiedWatchdogAncestors ([int]$ProcessRecord.ProcessId))
    if ($RecoverUnresponsive -and $verifiedWatchdogs.Count -gt 0) { return }

    throw "port $port is not owned by the expected Adaptive run_api.py process."
}

function Get-VerifiedWatchdogAncestors([int]$ProcessId) {
    $ancestors = @()
    $child = Get-ProcessRecord $ProcessId
    while ($child -and [int]$child.ParentProcessId -gt 0) {
        $parent = Get-ProcessRecord ([int]$child.ParentProcessId)
        if (-not $parent) { break }
        $isPowerShell = $parent.Name -match '^(powershell|pwsh)(\.exe)?$'
        if ($isPowerShell) {
            $commandLine = [string]$parent.CommandLine
            $grandParent = Get-ProcessRecord ([int]$parent.ParentProcessId)
            $isKnownLauncher = $commandLine -like '*start_adaptive_learning_backend.ps1*'
            $isServiceLaunched = (-not $commandLine) -and $grandParent -and
                $grandParent.Name -ieq 'svchost.exe'
            if ($isKnownLauncher -or $isServiceLaunched) {
                $ancestors += $parent
            }
        }
        $child = $parent
    }
    return $ancestors
}

function Stop-VerifiedApi {
    $listener = Get-Listener
    if (-not $listener) {
        $report.port_released = $true
        return
    }
    $report.old_pid = [int]$listener.OwningProcess
    $process = Get-ProcessRecord $report.old_pid
    Assert-ExpectedApi $process
    $report.old_process_started_at = $process.CreationDate
    $watchdogAncestors = @(Get-VerifiedWatchdogAncestors $report.old_pid)
    & "$env:SystemRoot\System32\taskkill.exe" /PID $report.old_pid /T /F | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "failed to stop verified Adaptive PID $($report.old_pid)" }
    foreach ($watchdog in $watchdogAncestors) {
        if (Get-ProcessRecord ([int]$watchdog.ProcessId)) {
            & "$env:SystemRoot\System32\taskkill.exe" /PID ([int]$watchdog.ProcessId) /T /F | Out-Null
            if ($LASTEXITCODE -notin @(0, 128)) {
                throw "failed to stop verified Adaptive watchdog PID $($watchdog.ProcessId)"
            }
            $report.watchdog_pids += [int]$watchdog.ProcessId
        }
    }
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        if (-not (Get-Listener)) {
            $report.port_released = $true
            return
        }
        Start-Sleep -Milliseconds 250
    }
    throw "port $port remained occupied after stopping PID $($report.old_pid)"
}

function Get-ManagedWatchdogs {
    $launcherName = 'start_adaptive_learning_backend.ps1'
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.ProcessId -ne $PID -and
            $_.CommandLine -and
            $_.CommandLine -like "*$launcherName*" -and
            $_.CommandLine -like "*$workspaceRoot*"
        }
}

function Stop-ManagedWatchdogs {
    $watchdogs = @(Get-ManagedWatchdogs)
    $report.watchdog_pids = @($watchdogs | ForEach-Object { [int]$_.ProcessId })
    foreach ($watchdog in $watchdogs) {
        & "$env:SystemRoot\System32\taskkill.exe" /PID ([int]$watchdog.ProcessId) /T /F | Out-Null
        if ($LASTEXITCODE -notin @(0, 128)) {
            throw "failed to stop Adaptive watchdog PID $($watchdog.ProcessId)"
        }
    }
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        if (-not @(Get-ManagedWatchdogs).Count) {
            $report.watchdog_stopped = $true
            return
        }
        Start-Sleep -Milliseconds 250
    }
    throw 'an old Adaptive watchdog remained after the stop transaction'
}

function Assert-OffHours {
    if ($AllowTradingWindowOverride) { return }
    $chinaNow = [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId((Get-Date), 'China Standard Time')
    if ($chinaNow.DayOfWeek -notin @('Saturday', 'Sunday') -and
        $chinaNow.TimeOfDay -ge [TimeSpan]::FromHours(8.5) -and
        $chinaNow.TimeOfDay -lt [TimeSpan]::FromHours(15.5)) {
        throw 'deployment is blocked during the weekday trading window'
    }
}

function Assert-TaskAction([switch]$AllowMissing) {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if (-not $task) {
        $report.task_status = 'missing_or_not_visible'
        if ($AllowMissing) { return }
        throw "managed task $taskName is missing or not visible to this PowerShell session"
    }
    $expectedLauncher = Join-Path $workspaceRoot 'scripts\start_adaptive_learning_backend.ps1'
    if (-not ($task.Actions | Where-Object { $_.Arguments -like "*$expectedLauncher*" })) {
        throw 'unexpected scheduled-task action; refusing to control the service'
    }
    $report.task_status = 'verified'
}

function Get-TaskStatusWithRetry {
    if (-not (Get-Listener)) {
        # A failed or already stopped backend cannot answer its internal task
        # endpoint.  The deployment transaction will still stop verified
        # process trees before replacing the release; do not block recovery on
        # an endpoint that has no listener.
        $report.task_status = 'backend_unavailable_safe_to_continue'
        return [pscustomobject]@{ running_tasks = @() }
    }
    $lastError = $null
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        $report.task_status_check_attempts = $attempt
        try {
            return Invoke-RestMethod "http://127.0.0.1:$port/api/v1/tasks/status" -TimeoutSec 5
        } catch {
            $lastError = $_.Exception.Message
            if ($attempt -lt 3) { Start-Sleep -Milliseconds 500 }
        }
    }
    if ($RecoverUnresponsive) {
        $report.task_status = 'unresponsive_task_state_unknown_recovery_authorized'
        return [pscustomobject]@{ running_tasks = @() }
    }
    throw "task status endpoint unavailable after $($report.task_status_check_attempts) attempts: $lastError"
}

function New-Manifest {
    $releaseId = "release-$(Get-Date -Format 'yyyyMMdd-HHmmss')-$([guid]::NewGuid().ToString('N').Substring(0,8))"
    $releaseContainer = Join-Path $releaseRoot $releaseId
    $sourceRoot = Join-Path $releaseContainer 'adaptive-investment-intelligence'
    $sharedRoot = Join-Path $releaseContainer 'shared'
    $manifestPath = Join-Path $releaseContainer 'manifest.json'
    New-Item -ItemType Directory -Force -Path $sourceRoot,$sharedRoot | Out-Null

    $runtimeDirectories = @('src', 'config', 'scripts', 'knowledge', 'plugins', 'providers')
    foreach ($relativeDirectory in $runtimeDirectories) {
        $copySource = Join-Path $projectRoot $relativeDirectory
        $copyDestination = Join-Path $sourceRoot $relativeDirectory
        $projectCopyArgs = @(
            $copySource, $copyDestination, '/E', '/COPY:DAT', '/DCOPY:DAT', '/R:1', '/W:1',
            '/XD', '__pycache__', '.mypy_cache', '.pytest_cache', '.ruff_cache',
            '/XF', '*.db', '*.db-*', '*.sqlite', '*.sqlite-*', '*.sqlite3', '*.wal', '*.shm', '*.pyc', 'tmp*'
        )
        & robocopy.exe @projectCopyArgs | Out-Null
        if ($LASTEXITCODE -gt 7) {
            throw "immutable source copy failed for $relativeDirectory with robocopy exit code $LASTEXITCODE"
        }
    }
    foreach ($rootFile in @('pyproject.toml', 'poetry.lock')) {
        Copy-Item -LiteralPath (Join-Path $projectRoot $rootFile) -Destination (Join-Path $sourceRoot $rootFile) -Force
    }

    $sharedCopyArgs = @(
        (Join-Path $workspaceRoot 'shared'), $sharedRoot, '/E', '/COPY:DAT', '/DCOPY:DAT',
        '/R:1', '/W:1', '/XD', '__pycache__', '/XF', '*.pyc'
    )
    & robocopy.exe @sharedCopyArgs | Out-Null
    if ($LASTEXITCODE -gt 7) { throw "shared runtime copy failed with robocopy exit code $LASTEXITCODE" }

    Push-Location $projectRoot
    try {
        & $pythonPath scripts/create_runtime_manifest.py --root $sourceRoot --output $manifestPath --release-id $releaseId | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'runtime manifest creation failed' }
        & $pythonPath scripts/create_runtime_manifest.py --root $sourceRoot --output $manifestPath --verify | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'runtime manifest verification failed' }
        & $pythonPath scripts/build_release_frontend.py --manifest $manifestPath | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'unified frontend build failed' }
    } finally {
        Pop-Location
    }
    return $manifestPath
}

function Start-ManagedApi {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($task) {
        Start-ScheduledTask -TaskName $taskName
    } else {
        $launcher = Join-Path $workspaceRoot 'scripts\start_adaptive_learning_backend.ps1'
        if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
            throw "managed task is missing and launcher was not found: $launcher"
        }
        $watchdog = Start-Process -FilePath 'powershell.exe' `
            -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $launcher) `
            -WindowStyle Hidden -PassThru
        $report.watchdog_started_pid = [int]$watchdog.Id
    }
    $healthy = $false
    for ($attempt = 0; $attempt -lt 45; $attempt++) {
        Start-Sleep -Seconds 1
        try {
            $health = Invoke-RestMethod "http://127.0.0.1:$port/api/v1/system/health" -TimeoutSec 2
            if ($health.status -eq 'ok') { $healthy = $true; break }
        } catch { }
    }
    if (-not $healthy) { throw 'new Adaptive process did not pass health check' }
    $listener = Get-Listener
    if (-not $listener) { throw 'health returned but port listener was not found' }
    $report.new_pid = [int]$listener.OwningProcess
    $process = Get-ProcessRecord $report.new_pid
    Assert-ExpectedApi $process
    $report.new_process_started_at = $process.CreationDate
    if ([datetime]$process.CreationDate -lt [datetime]$report.started_at) {
        throw 'listener PID was not created during this deployment transaction'
    }
}

try {
    New-Item -ItemType Directory -Force -Path $runtimeRoot,$releaseRoot,$reportRoot | Out-Null
    try {
        $lockStream = [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    } catch {
        throw 'another Adaptive deployment transaction is already running'
    }

    Assert-OffHours
    Assert-TaskAction -AllowMissing
    $manifestPath = if ($PreparedManifest) { (Resolve-Path -LiteralPath $PreparedManifest).Path } else { New-Manifest }
    $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
    & $pythonPath (Join-Path $projectRoot 'scripts/create_runtime_manifest.py') --root $manifest.source_root --output $manifestPath --verify | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'prepared backend validation failed' }
    $bundle = Get-Content -Raw -LiteralPath (Join-Path (Split-Path -Parent $manifestPath) 'bundle.json') | ConvertFrom-Json
    if ($bundle.release_id -ne $manifest.release_id -or $bundle.backend_artifact_hash -ne $manifest.artifact_hash) {
        throw 'frontend bundle is not bound to this backend release'
    }
    if ((Get-FileHash -LiteralPath $bundle.frontend_vsix -Algorithm SHA256).Hash -ne $bundle.frontend_sha256) {
        throw 'frontend VSIX hash mismatch'
    }
    $launcherPath = Join-Path $workspaceRoot 'scripts/start_adaptive_learning_backend.ps1'
    if ((Get-FileHash -LiteralPath $launcherPath -Algorithm SHA256).Hash -ne $bundle.launcher_sha256) {
        throw 'watchdog changed since bundle preparation'
    }
    $report.frontend_vsix = $bundle.frontend_vsix
    $report.frontend_version = $bundle.product_version
    $report.expected_release_id = $manifest.release_id
    $report.expected_artifact_hash = $manifest.artifact_hash
    if ($PrepareOnly) {
        $report.status = 'prepared'
        Save-Report
        exit 0
    }

    if ($VerifyOnly) {
        if (-not (Test-Path -LiteralPath $activeManifest)) { throw 'active runtime manifest is missing' }
        $runtime = Invoke-RestMethod "http://127.0.0.1:$port/api/v1/system/runtime" -TimeoutSec 15
        $report.actual_release_id = $runtime.release_id
        $report.actual_artifact_hash = $runtime.artifact_hash
        $report.runtime_verified = [bool]($runtime.deployment_ready -and -not $runtime.disk_drift)
        if (-not $report.runtime_verified) { throw 'running process failed runtime identity verification' }
        $report.status = 'verified'
        Save-Report
        exit 0
    }

    $taskStatus = Get-TaskStatusWithRetry
    if (@($taskStatus.running_tasks).Count -gt 0) { throw 'a task is running; retry after it finishes' }
    if (Test-Path -LiteralPath $activeManifest) {
        $previousManifest = Get-Content -Raw -LiteralPath $activeManifest
    }
    Write-AtomicJson $maintenancePath ([ordered]@{
        status = 'deploying'
        started_at = $report.started_at
        expected_release_id = $manifest.release_id
        owner_pid = $PID
    })
    $report.maintenance_entered = $true
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $taskName
    }
    Stop-ManagedWatchdogs
    Stop-VerifiedApi

    Push-Location $projectRoot
    try {
        & $pythonPath scripts/adopt_runtime_contract.py --confirm
        if ($LASTEXITCODE -ne 0) { throw 'runtime contract adoption failed' }
        $report.contract_adopted = $true
    } finally {
        Pop-Location
    }
    Copy-Item -LiteralPath $manifestPath -Destination "$activeManifest.tmp" -Force
    Move-Item -LiteralPath "$activeManifest.tmp" -Destination $activeManifest -Force
    Start-ManagedApi

    $runtime = Invoke-RestMethod "http://127.0.0.1:$port/api/v1/system/runtime" -TimeoutSec 15
    $report.actual_release_id = $runtime.release_id
    $report.actual_artifact_hash = $runtime.artifact_hash
    if ($runtime.release_id -ne $manifest.release_id -or
        $runtime.artifact_hash -ne $manifest.artifact_hash -or
        -not $runtime.deployment_ready -or $runtime.disk_drift) {
        throw 'running process identity does not match the prepared runtime manifest'
    }
    $report.runtime_verified = $true

    $scanner = Invoke-RestMethod "http://127.0.0.1:$port/api/v1/scanner/latest?top_n=5" -TimeoutSec 30
    $scannerItems = @($scanner.candidates) + @($scanner.blocked_candidates)
    if (@($scannerItems | Where-Object { $_.PSObject.Properties.Name -contains 'score_display' }).Count -eq 0) {
        throw 'scanner response does not expose score_display'
    }
    $report.scanner_behavior_verified = $true

    & code.cmd --install-extension $bundle.frontend_vsix --force
    if ($LASTEXITCODE -ne 0) { throw 'frontend extension installation failed' }
    $installedRoot = Join-Path $env:USERPROFILE ".vscode/extensions/quantai.quantai-research-terminal-$($bundle.product_version)"
    $installedStamp = Get-Content -Raw -LiteralPath (Join-Path $installedRoot 'release-info.json') | ConvertFrom-Json
    if ($installedStamp.release_id -ne $bundle.release_id -or
        $installedStamp.backend_artifact_hash -ne $manifest.artifact_hash) {
        throw 'installed frontend belongs to a different backend release'
    }
    foreach ($entry in $bundle.frontend_files.PSObject.Properties) {
        if ((Get-FileHash -LiteralPath (Join-Path $installedRoot $entry.Name) -Algorithm SHA256).Hash -ne $entry.Value) {
            throw "installed frontend file mismatch: $($entry.Name)"
        }
    }
    $report.frontend_status = 'installed_reload_pending'
    Remove-Item -LiteralPath $maintenancePath -Force -ErrorAction SilentlyContinue
    $report.status = 'routes_verified_frontend_reload_and_ai_run_pending'
} catch {
    $report.error = $_.Exception.Message
    if ($report.maintenance_entered) {
        $report.rollback_attempted = $true
        if ($previousManifest) {
            try {
                [IO.File]::WriteAllText("$activeManifest.rollback.tmp", $previousManifest, [Text.UTF8Encoding]::new($false))
                Move-Item -LiteralPath "$activeManifest.rollback.tmp" -Destination $activeManifest -Force
                Stop-ManagedWatchdogs
                Stop-VerifiedApi
                Start-ManagedApi
                $rollbackRuntime = Invoke-RestMethod "http://127.0.0.1:$port/api/v1/system/runtime" -TimeoutSec 15
                $report.rollback_verified = [bool]($rollbackRuntime.deployment_ready -and -not $rollbackRuntime.disk_drift)
                if ($report.rollback_verified) {
                    Remove-Item -LiteralPath $maintenancePath -Force -ErrorAction SilentlyContinue
                }
            } catch {
                $report.rollback_unavailable = $true
                $report.rollback_error = $_.Exception.Message
            }
        } else {
            $report.rollback_unavailable = $true
        }
    }
} finally {
    if ($lockStream) { $lockStream.Dispose() }
    Save-Report
}
if ($report.error) { Write-Error $report.error; exit 1 }
