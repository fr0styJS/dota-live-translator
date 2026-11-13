# One-shot setup for the Dota Live Translator.
#   powershell -ExecutionPolicy Bypass -File setup.ps1
#   powershell -ExecutionPolicy Bypass -File setup.ps1 -Autostart
#   powershell -ExecutionPolicy Bypass -File setup.ps1 -SkipModels -MockTest
param(
  [switch]$SkipModels,     # skip the ~2.5 GB model download / warmup
  [switch]$Autostart,      # logon shortcut + 60s watchdog task
  [switch]$MockTest,       # run the no-GPU smoke test at the end
  [switch]$Force           # recreate the venv even if it exists
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$root = $PSScriptRoot

Write-Host "== Dota Live Translator setup ==" -ForegroundColor Cyan
Write-Host "repo: $root"

# --- 1. prerequisites -------------------------------------------------------
$build = [int](Get-CimInstance Win32_OperatingSystem).BuildNumber
Write-Host "Windows build: $build"
if ($build -lt 20348) {
  Write-Warning "WASAPI process loopback needs Windows 10 build 20348+ (Windows 11). Capture will fail here."
}

$launcher = Get-Command py -ErrorAction SilentlyContinue
if ($launcher) {
  $py = "py"
  $pyArgs = @("-3.12")
  try { & py -3.12 -c "import sys;print(sys.version)" | Out-Null }
  catch { throw "py -3.12 not found. Install Python 3.12 (python.org) and tick 'py launcher'." }
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
  $py = "python"
  $pyArgs = @()
  $ver = & python -c "import sys;print('%d.%d' % sys.version_info[:2])"
  if ($ver -ne "3.12") { Write-Warning "Python $ver detected; 3.12 is what this was built and tested on." }
} else {
  throw "No Python found. Install 3.12 from python.org (tick 'Add python.exe to PATH' and 'py launcher')."
}
Write-Host "python: $py $($pyArgs -join ' ')"

# --- 2. venv + deps ---------------------------------------------------------
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
$venvPyw = Join-Path $root ".venv\Scripts\pythonw.exe"
$needVenv = $Force -or -not (Test-Path $venvPy)
if ($needVenv) {
  if (Test-Path (Join-Path $root ".venv")) { Remove-Item (Join-Path $root ".venv") -Recurse -Force }
  Write-Host "creating venv..." -ForegroundColor Cyan
  & $py @pyArgs -m venv .venv
}
if (-not (Test-Path $venvPyw)) { throw "venv looks broken: $venvPyw missing" }

Write-Host "installing requirements (torch cu121 is ~2.5 GB on first run)..." -ForegroundColor Cyan
& $venvPy -m pip install --upgrade pip --quiet
& $venvPy -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed (exit $LASTEXITCODE)" }

# --- 3. sanity: the packages we import late --------------------------------
& $venvPy -c "import yaml, numpy, psutil, websockets, sounddevice, soundcard, comtypes, silero_vad; print('imports OK')"
if ($LASTEXITCODE -ne 0) { throw "basic imports failed in the venv" }

Write-Host "checking CUDA torch (first run downloads the CUDA build)..." -ForegroundColor Cyan
& $venvPy -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'no GPU')"
$cudaOk = (& $venvPy -c "import torch;print(1 if torch.cuda.is_available() else 0)").Trim() -eq "1"
if (-not $cudaOk) {
  Write-Warning "No CUDA device visible to torch."
  Write-Warning "Live mode needs an NVIDIA GPU (~4 GB free VRAM). Set asr.device/mt.device to 'cpu' in config.yaml to try anyway (very slow)."
}

# --- 4. models --------------------------------------------------------------
if ($SkipModels) {
  Write-Host "models skipped (-SkipModels); first live run will download them." -ForegroundColor Yellow
} else {
  Write-Host "warming up models (downloads ~2.5 GB on first run)..." -ForegroundColor Cyan
  & $venvPy tools\warmup.py
  if ($LASTEXITCODE -ne 0) { Write-Warning "warmup exited $LASTEXITCODE - see output above" }
}

# --- 5. optional autostart --------------------------------------------------
if ($Autostart) {
  Write-Host "registering autostart..." -ForegroundColor Cyan
  & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "tools\install_autostart.ps1")
} else {
  Write-Host "autostart not installed (re-run with -Autostart to add the logon shortcut + watchdog)." -ForegroundColor Yellow
}

# --- 6. optional smoke test (no GPU, no Dota) ------------------------------
if ($MockTest) {
  Write-Host "mock smoke test..." -ForegroundColor Cyan
  & $venvPy tools\test_mock.py
}

Write-Host ""
Write-Host "done. next:" -ForegroundColor Green
Write-Host "  $venvPy backend\app.py          # live, waits for Dota 2"
Write-Host "  $venvPy backend\app.py --mock   # scripted demo, no models"
Write-Host "  http://127.0.0.1:5111           # second-monitor page"
Write-Host "  $venvPy ui-overlay\overlay.py   # in-game overlay"
