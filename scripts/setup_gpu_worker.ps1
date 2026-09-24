# One-time setup for the GPU worker on this desktop: a Python 3.12 virtualenv with PyTorch (CUDA 12.8,
# needed for RTX 50-series cards), diffusers for local artwork, and the Sarvam client. Then it downloads
# the artwork models (about 7 GB) into the Hugging Face cache so the first job doesn't wait for them.
#
#   powershell -ExecutionPolicy Bypass -File scripts\setup_gpu_worker.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $root "worker\.venv-gpu"
$python = Join-Path $venv "Scripts\python.exe"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw "Install uv first: https://docs.astral.sh/uv/" }
if (-not (Test-Path $python)) { uv venv $venv --python 3.12 }
uv pip install --python $python torch --index-url https://download.pytorch.org/whl/cu128
uv pip install --python $python -r (Join-Path $root "worker\requirements-gpu.txt")

& $python -c @"
import torch
from huggingface_hub import hf_hub_download, snapshot_download
print('CUDA:', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')
snapshot_download('stabilityai/stable-diffusion-xl-base-1.0',
                  allow_patterns=['model_index.json', '*/config.json', '*/*.fp16.safetensors', 'scheduler/*',
                                  'tokenizer*/*'])
snapshot_download('madebyollin/sdxl-vae-fp16-fix', allow_patterns=['config.json', 'diffusion_pytorch_model.safetensors'])
hf_hub_download('ByteDance/SDXL-Lightning', 'sdxl_lightning_8step_lora.safetensors')
print('Artwork models are ready.')
"@
