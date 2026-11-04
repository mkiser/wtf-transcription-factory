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
$VenvDir = Join-Path $CodeDir ".venv"
$VenvPy  = Join-Path $VenvDir "Scripts\python.exe"
$UvVersion = "0.13.4"
# 3.12 has wheels for every dependency on the most systems. 3.13 and 3.14 lock
# out older Macs, and onnxruntime has no wheel for 3.15.
$PythonVersion = "3.12"

function Say($m) { Write-Host "`n$m" -ForegroundColor Cyan }

function Stop-Install($m) {
  Write-Host "`nThe install didn't finish: $m" -ForegroundColor Yellow
  Write-Host "  Check your internet connection and close the app if it's open."
  Write-Host "  Then run the same install command again."
  Write-Host "  The installer needs to reach github.com and pypi.org."
  throw $m
}

# An environment on Python 3.10 to 3.14 with its main packages already works, so
# an update leaves it in place. Anything else, such as an interrupted install or
# a failed one on 3.15, gets rebuilt.
function Test-Env {
  $ErrorActionPreference = "Continue"
  if (-not (Test-Path $VenvPy)) { return $false }
  & $VenvPy -c "import sys, pip, av, faster_whisper, flask; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,14) else 1)" 2>$null | Out-Null
  return ($LASTEXITCODE -eq 0)
}

function Build-Env {
  Write-Host "  Downloading a private copy of Python ..."
  $ProgressPreference = "SilentlyContinue"
  $bin = Join-Path $CodeDir "bin"
  $zip = Join-Path $env:TEMP ("wtf_uv_" + [System.Guid]::NewGuid().ToString("N") + ".zip")
  try {
    # uv fetches the Python. Everything stays inside the app's folder, and the
    # user's PATH and any Python they already have are left alone.
    Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/astral-sh/uv/releases/download/$UvVersion/uv-x86_64-pc-windows-msvc.zip" -OutFile $zip
    Expand-Archive -Path $zip -DestinationPath $bin -Force
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $CodeDir "python"
    $env:UV_CACHE_DIR = Join-Path $CodeDir ".uv-cache"
    if (Test-Path $VenvDir) { Remove-Item $VenvDir -Recurse -Force }
    # --seed installs pip, which the app uses to refresh yt-dlp. The request names
    # x64 because ctranslate2 has no wheel for Windows on ARM, which emulates x64.
    & (Join-Path $bin "uv.exe") venv --quiet --seed --python "cpython-$PythonVersion-windows-x86_64-none" --managed-python $VenvDir
    if ($LASTEXITCODE -ne 0) { throw "uv exited with code $LASTEXITCODE." }
  } catch {
    Stop-Install "couldn't set up Python. $_"
  } finally {
    Remove-Item $zip -Force -ErrorAction SilentlyContinue
    Remove-Item Env:UV_PYTHON_INSTALL_DIR, Env:UV_CACHE_DIR -ErrorAction SilentlyContinue
  }
}

# Wheels only: most people have no compiler, so a source build can only fail.
function Install-Deps {
  & $VenvPy -m pip install --quiet --upgrade pip | Out-Host
  if ($LASTEXITCODE -ne 0) { return $false }
  & $VenvPy -m pip install --quiet "--only-binary=:all:" -r (Join-Path $CodeDir "app\requirements.txt") | Out-Host
  return ($LASTEXITCODE -eq 0)
}

Say "Installing $Name ..."

Say "Downloading the latest version ..."
$tmp = Join-Path $env:TEMP ("wtf_" + [System.Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
  $zip = Join-Path $tmp "src.zip"
  Invoke-WebRequest -UseBasicParsing -Uri "https://codeload.github.com/$Repo/zip/refs/heads/$Branch" -OutFile $zip
  Expand-Archive -Path $zip -DestinationPath $tmp -Force
  $src = Join-Path $tmp "wtf-transcription-factory-$Branch"
  if (-not (Test-Path $CodeDir)) { New-Item -ItemType Directory -Path $CodeDir | Out-Null }
  Get-ChildItem -Path $src -Force |
    Where-Object { $_.Name -notin @('.venv', 'transcripts') } |
    ForEach-Object { Copy-Item $_.FullName -Destination $CodeDir -Recurse -Force }
} catch {
  Stop-Install "couldn't download the app. $_"
} finally {
  Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

Say "Setting things up (first time takes a few minutes) ..."
if (-not (Test-Env)) { Build-Env }
Write-Host "  Installing the speech engine and audio tools. Keep this window open."
if (-not (Install-Deps)) {
  Write-Host "  That didn't work. Rebuilding the app's environment and trying once more."
  Build-Env
  if (-not (Install-Deps)) { Stop-Install "couldn't install the app's components." }
}

Say "Creating the app shortcut ..."
$appPy = Join-Path $CodeDir "app\app.py"
$ws = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath('Programs'),
                   [Environment]::GetFolderPath('Desktop'))) {
  try {
    $lnk = $ws.CreateShortcut((Join-Path $dir "$Name.lnk"))
    $lnk.TargetPath       = $VenvPy
    $lnk.Arguments        = "`"$appPy`""
    $lnk.WorkingDirectory = $CodeDir
    $lnk.Save()
  } catch {
    Write-Host "  Couldn't create a shortcut in '$dir'."
    Write-Host "  To run the app later: & `"$VenvPy`" `"$appPy`""
  }
}

Say "All set! Launching ..."
Start-Process $VenvPy -ArgumentList "`"$appPy`"" -WorkingDirectory $CodeDir
Write-Host "  Next time, open `"$Name`" from the Start Menu or Desktop."
Write-Host "  (A small window stays open while it runs; close it to stop.)"
