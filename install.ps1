# WTF Transcription Factory — Windows installer
#
# Run this in PowerShell:
#   irm https://raw.githubusercontent.com/mkiser/wtf-transcription-factory/main/install.ps1 | iex
#
# You don't need to install anything first. It downloads the app and its own
# private copy of Python, sets up its own environment, creates Start Menu /
# Desktop shortcuts, and launches it.
$ErrorActionPreference = "Stop"

$Repo    = "mkiser/wtf-transcription-factory"
$Branch  = "main"
$Name    = "WTF Transcription Factory"
$CodeDir = Join-Path $env:LOCALAPPDATA $Name
$UvVersion = "0.13.4"
# 3.12 has wheels for every dependency on the most systems. 3.13 and 3.14 lock
# out older Macs, and onnxruntime has no wheel for 3.15.
$PythonVersion = "3.12"

function Say($m) { Write-Host "`n$m" -ForegroundColor Cyan }

Say "Installing $Name ..."

Say "Downloading the latest version ..."
$tmp = Join-Path $env:TEMP ("wtf_" + [System.Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
  $zip = Join-Path $tmp "src.zip"
  Invoke-WebRequest -Uri "https://codeload.github.com/$Repo/zip/refs/heads/$Branch" -OutFile $zip
  Expand-Archive -Path $zip -DestinationPath $tmp -Force
  $src = Join-Path $tmp "wtf-transcription-factory-$Branch"
  if (-not (Test-Path $CodeDir)) { New-Item -ItemType Directory -Path $CodeDir | Out-Null }
  Get-ChildItem -Path $src -Force |
    Where-Object { $_.Name -notin @('.venv', 'transcripts') } |
    ForEach-Object { Copy-Item $_.FullName -Destination $CodeDir -Recurse -Force }
} finally {
  Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

Say "Setting things up (first time takes a few minutes) ..."
$venvDir = Join-Path $CodeDir ".venv"
$venvPy = Join-Path $venvDir "Scripts\python.exe"
# An environment on Python 3.10 to 3.14 already works, so an update leaves it in
# place. Anything else, such as a failed install on 3.15, gets rebuilt.
$venvOk = $false
if (Test-Path $venvPy) {
  try {
    & $venvPy -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,14) else 1)" 2>$null
    $venvOk = ($LASTEXITCODE -eq 0)
  } catch {
    $venvOk = $false
  }
}
if (-not $venvOk) {
  # uv fetches the private Python. Everything stays inside the app's folder, and
  # the user's PATH and any Python they already have are left alone.
  $env:UV_UNMANAGED_INSTALL = Join-Path $CodeDir "bin"
  $env:UV_PYTHON_INSTALL_DIR = Join-Path $CodeDir "python"
  $env:UV_CACHE_DIR = Join-Path $CodeDir ".uv-cache"
  $uvInstaller = Join-Path $env:TEMP ("wtf_uv_" + [System.Guid]::NewGuid().ToString("N") + ".ps1")
  try {
    Invoke-WebRequest -Uri "https://astral.sh/uv/$UvVersion/install.ps1" -OutFile $uvInstaller
    & (Get-Process -Id $PID).Path -NoProfile -ExecutionPolicy Bypass -File $uvInstaller | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "uv install failed." }
  } finally {
    Remove-Item $uvInstaller -Force -ErrorAction SilentlyContinue
  }
  if (Test-Path $venvDir) { Remove-Item $venvDir -Recurse -Force }
  # --seed installs pip, which the app uses to refresh yt-dlp. The request names
  # x64 because ctranslate2 has no wheel for Windows on ARM, which emulates x64.
  & (Join-Path $CodeDir "bin\uv.exe") venv --quiet --seed --python "cpython-$PythonVersion-windows-x86_64-none" --managed-python $venvDir
  if ($LASTEXITCODE -ne 0) { throw "Virtual environment creation failed." }
}
& $venvPy -m pip install --quiet --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed." }
& $venvPy -m pip install --quiet --prefer-binary -r (Join-Path $CodeDir "app\requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "pip install failed." }

Say "Creating the app shortcut ..."
$appPy = Join-Path $CodeDir "app\app.py"
$ws = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath('Programs'),
                   [Environment]::GetFolderPath('Desktop'))) {
  $lnk = $ws.CreateShortcut((Join-Path $dir "$Name.lnk"))
  $lnk.TargetPath       = $venvPy
  $lnk.Arguments        = "`"$appPy`""
  $lnk.WorkingDirectory = $CodeDir
  $lnk.Save()
}

Say "All set! Launching ..."
Start-Process $venvPy -ArgumentList "`"$appPy`"" -WorkingDirectory $CodeDir
Write-Host "  Next time, open `"$Name`" from the Start Menu or Desktop."
Write-Host "  (A small window stays open while it runs; close it to stop.)"
