# Runs the AI worker natively on this desktop so it can use LM Studio on the GPU.
# It pulls "llm" (teasers) and "image" (artwork) jobs from the local API, exactly as a
# GPU machine will pull from the Lightsail server in production.
#
#   powershell -ExecutionPolicy Bypass -File scripts\run_gpu_worker.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root ".env"
if (-not (Test-Path $envFile)) { throw "Missing .env. Run: python scripts/setup_local.py" }
$settings = @{}
Get-Content $envFile | Where-Object { $_ -match '^\s*[A-Z_]+=' } | ForEach-Object {
    $key, $value = $_ -split '=', 2
    $settings[$key.Trim()] = $value.Trim()
}

$env:KC_API_URL = if ($settings.KC_GPU_API_URL) { $settings.KC_GPU_API_URL } else { "http://localhost:8080" }
$env:KC_WORKER_TOKEN = $settings.KC_GPU_WORKER_TOKEN
$env:KC_WORKER_CAPABILITIES = if ($settings.KC_GPU_CAPABILITIES) { $settings.KC_GPU_CAPABILITIES } else { "llm,image" }
$env:KC_LLM_BASE_URL = if ($settings.KC_LLM_BASE_URL) { $settings.KC_LLM_BASE_URL } else { "http://localhost:1234/v1" }
$env:KC_LLM_MODEL = $settings.KC_LLM_MODEL
$env:KC_ARTWORK_PROVIDER = $settings.KC_ARTWORK_PROVIDER
$env:PYTHONIOENCODING = "utf-8"

try {
    $models = (Invoke-RestMethod "$($env:KC_LLM_BASE_URL)/models" -TimeoutSec 5).data.id
    if ($models -notcontains $env:KC_LLM_MODEL) {
        Write-Warning "LM Studio doesn't list $($env:KC_LLM_MODEL). Available: $($models -join ', ')"
    }
} catch {
    Write-Warning "LM Studio isn't answering at $($env:KC_LLM_BASE_URL). Start its server (Developer tab, or: lms server start)."
}

Set-Location (Join-Path $root "worker")
# The GPU virtualenv (scripts\setup_gpu_worker.ps1) has PyTorch for local artwork; plain Python still runs teasers.
$python = Join-Path $root "worker\.venv-gpu\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Warning "GPU virtualenv not found: local artwork won't work. Run scripts\setup_gpu_worker.ps1."
    $python = "python"
}
& $python -m kc_worker
