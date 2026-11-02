# Runs the AI worker natively on this desktop so it can use LM Studio on the GPU.
# It pulls "llm" (teasers) and "image" (artwork) jobs from the local API, or from the Lightsail server
# when the desktop .env has KC_GPU_API_URL and KC_GPU_API_TOKEN (printed by setup_local.py --server).
#
#   powershell -ExecutionPolicy Bypass -File scripts\run_gpu_worker.ps1             # now, in this window
#   powershell -ExecutionPolicy Bypass -File scripts\run_gpu_worker.ps1 -Install    # every evening instead
#   powershell -ExecutionPolicy Bypass -File scripts\run_gpu_worker.ps1 -Stop       # end tonight's run now
#   powershell -ExecutionPolicy Bypass -File scripts\run_gpu_worker.ps1 -Uninstall
#
# -Install adds a Windows task that leaves the GPU alone during the day: the worker runs only within
# KC_GPU_HOURS (default 19:00-06:00 on this PC's clock), from the opening time or from sign-in if that is later.
# The task loads the model, restarts the worker if it crashes, and at the closing time lets the current job
# finish and closes LM Studio (models, server and daemon). LM Studio needn't start at sign-in: the task starts it.
# Logs: data\logs\gpu-schedule.log and data\logs\gpu-worker-*.log.

param([switch]$Install, [switch]$Uninstall, [switch]$Stop, [switch]$Scheduled)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$taskName = "KathaChepta GPU worker"
$lms = Join-Path $env:USERPROFILE ".lmstudio\bin\lms.exe"

# The worker's Python processes (a virtualenv's python.exe starts a second, real one).
function Get-WorkerProcess {
    Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" | Where-Object { $_.CommandLine -match "-m kc_worker" }
}

# Nothing of LM Studio stays running during the day: the models leave the GPU, then the server and its daemon stop.
function Stop-LmStudio {
    & $lms unload --all | Out-Null
    & $lms server stop | Out-Null
    & $lms daemon down | Out-Null
    # The daemon won't stop while the LM Studio app is open, and lms commands open the app when nothing is running.
    Get-Process "LM Studio" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed the evening GPU worker task."
    return
}
if ($Stop) {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    # Ending the task doesn't always end its PowerShell at once: stop that first so it can't restart the worker.
    Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" |
        Where-Object { $_.CommandLine -match "run_gpu_worker\.ps1.*-Scheduled" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Get-WorkerProcess | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    if (Test-Path $lms) { Stop-LmStudio }
    Write-Host "GPU worker stopped and LM Studio closed. A job it was in the middle of goes back"
    Write-Host "in the queue when its lease runs out (up to 15 minutes). The task starts again at the next opening time."
    return
}

$envFile = Join-Path $root ".env"
if (-not (Test-Path $envFile)) { throw "Missing .env. Run: python scripts/setup_local.py" }
$settings = @{}
Get-Content $envFile | Where-Object { $_ -match '^\s*[A-Z_]+=' } | ForEach-Object {
    $key, $value = $_ -split '=', 2
    $settings[$key.Trim()] = $value.Trim()
}

$hours = if ($settings.KC_GPU_HOURS) { $settings.KC_GPU_HOURS } else { "19:00-06:00" }
if ($hours -notmatch '^(\d{1,2}:\d\d)-(\d{1,2}:\d\d)$') { throw "KC_GPU_HOURS must look like 19:00-06:00, not '$hours'" }
$opens, $closes = [TimeSpan]$Matches[1], [TimeSpan]$Matches[2]
if ($opens -eq $closes) { throw "KC_GPU_HOURS opens and closes at the same time: '$hours'" }

function Test-GpuHours([datetime]$at) {
    $time = $at.TimeOfDay
    if ($opens -lt $closes) { return $time -ge $opens -and $time -lt $closes }
    return $time -ge $opens -or $time -lt $closes  # overnight, e.g. 19:00-06:00
}

if ($Install) {
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Scheduled"
    $triggers = @(
        (New-ScheduledTaskTrigger -Daily -At ((Get-Date).Date + $opens)),
        (New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"))
    $length = $closes - $opens
    if ($length -lt [TimeSpan]::Zero) { $length = $length.Add([TimeSpan]::FromDays(1)) }
    # StartWhenAvailable: if the PC was off or asleep at the opening time, start when it's back.
    $options = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -MultipleInstances IgnoreNew -ExecutionTimeLimit $length.Add([TimeSpan]::FromHours(1))
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Settings $options -Force `
        -Description "KathaChepta AI jobs on the GPU during $hours only (scripts\run_gpu_worker.ps1)" | Out-Null
    Write-Host "GPU work is scheduled for $hours every day ($((Get-TimeZone).Id)), and after a sign-in within those hours."
    Write-Host "Next start: $((Get-ScheduledTaskInfo -TaskName $taskName).NextRunTime). To change the hours, set KC_GPU_HOURS in .env and run -Install again."
    if (Test-GpuHours (Get-Date)) {
        Start-ScheduledTask -TaskName $taskName
        Write-Host "It's within those hours now, so it has started. Log: data\logs\gpu-schedule.log"
    }
    return
}

$env:KC_API_URL = if ($settings.KC_GPU_API_URL) { $settings.KC_GPU_API_URL } else { "http://localhost:8080" }
$env:KC_WORKER_TOKEN = if ($settings.KC_GPU_API_TOKEN) { $settings.KC_GPU_API_TOKEN } else { $settings.KC_GPU_WORKER_TOKEN }
$env:KC_WORKER_CAPABILITIES = if ($settings.KC_GPU_CAPABILITIES) { $settings.KC_GPU_CAPABILITIES } else { "llm,image" }
$env:KC_LLM_BASE_URL = if ($settings.KC_LLM_BASE_URL) { $settings.KC_LLM_BASE_URL } else { "http://localhost:1234/v1" }
$env:KC_LLM_MODEL = $settings.KC_LLM_MODEL
$env:KC_ARTWORK_PROVIDER = $settings.KC_ARTWORK_PROVIDER
$env:SARVAM_API_KEY = $settings.SARVAM_API_KEY  # Telugu conversation starters (Sarvam translate)
$env:PYTHONIOENCODING = "utf-8"
$model = if ($settings.KC_LLM_MODEL) { $settings.KC_LLM_MODEL } else { "qwen/qwen3-8b" }

$workerDir = Join-Path $root "worker"
# The GPU virtualenv (scripts\setup_gpu_worker.ps1) has PyTorch for local artwork; plain Python still runs teasers.
$python = Join-Path $workerDir ".venv-gpu\Scripts\python.exe"
$noVenv = "GPU virtualenv not found: local artwork won't work. Run scripts\setup_gpu_worker.ps1."
if (-not (Test-Path $python)) { $python = "python" } else { $noVenv = $null }

if ($Scheduled) {
    if (-not (Test-GpuHours (Get-Date))) { return }  # a daytime sign-in: the evening trigger starts it later
    $logs = Join-Path $root "data\logs"
    New-Item -ItemType Directory -Force $logs | Out-Null
    Get-ChildItem $logs -Filter "gpu-worker-*.log" | Where-Object LastWriteTime -lt (Get-Date).AddDays(-14) | Remove-Item
    $schedule = Join-Path $logs "gpu-schedule.log"
    function Write-Log([string]$text) { Add-Content $schedule ("{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $text) }
    if (Get-WorkerProcess) { Write-Log "A GPU worker is already running; leaving it alone."; return }

    $closing = (Get-Date).Date + $closes
    if ($closing -le (Get-Date)) { $closing = $closing.AddDays(1) }
    $env:KC_WORKER_UNTIL = $closes.ToString("hh\:mm")  # the worker finishes its job and exits at the closing time
    $env:PYTHONUNBUFFERED = "1"
    try {
        if ($noVenv) { Write-Log $noVenv }
        # One request at a time gets the whole 8K context; LM Studio's defaults split it and teasers overflow.
        & $lms daemon up | Out-Null  # closed at the last closing time
        & $lms server start | Out-Null
        & $lms unload --all | Out-Null
        & $lms load $model --context-length 8192 --parallel 1 --gpu max -y | Out-Null
        Write-Log "Opened until $($closing.ToString('yyyy-MM-dd HH:mm')) for $env:KC_API_URL (lms load $model -> exit $LASTEXITCODE)"
        while ((Get-Date) -lt $closing) {
            $log = Join-Path $logs ("gpu-worker-{0:yyyyMMdd-HHmmss}.log" -f (Get-Date))
            $run = Start-Process $python -ArgumentList "-m", "kc_worker" -WorkingDirectory $workerDir `
                -NoNewWindow -Wait -PassThru -RedirectStandardError $log
            if ($run.ExitCode -eq 0) { break }  # it reached the closing time
            Write-Log "Worker exited with code $($run.ExitCode); see $log"
            if ($run.ExitCode -eq 2) { break }  # a setting is wrong: restarting won't help
            Start-Sleep -Seconds 60
        }
    } catch {
        Write-Log "Failed: $_"
    } finally {
        Stop-LmStudio
        Write-Log "Closed: LM Studio's models are unloaded, its server and daemon stopped, and the GPU is free."
    }
    return
}

if (Get-WorkerProcess) {
    Write-Warning "A GPU worker is already running (the evening task?). End it first: scripts\run_gpu_worker.ps1 -Stop"
    exit 1
}
if ($noVenv) { Write-Warning $noVenv }
Write-Host "GPU worker serving $($env:KC_API_URL)"
try {
    $models = (Invoke-RestMethod "$($env:KC_LLM_BASE_URL)/models" -TimeoutSec 5).data.id
    if ($models -notcontains $env:KC_LLM_MODEL) {
        Write-Warning "LM Studio doesn't list $($env:KC_LLM_MODEL). Available: $($models -join ', ')"
    }
} catch {
    Write-Warning "LM Studio isn't answering at $($env:KC_LLM_BASE_URL). Start its server (Developer tab, or: lms server start)."
}

Set-Location $workerDir
& $python -m kc_worker
