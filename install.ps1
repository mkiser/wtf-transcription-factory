# WTF Transcription Factory — Windows installer
#
# Run this in PowerShell:
#   irm https://raw.githubusercontent.com/mkiser/wtf-transcription-factory/main/install.ps1 | iex
#
# It requires only Python 3. It downloads the app, sets up its own private
# environment, creates Start Menu / Desktop shortcuts, and launches it.
$ErrorActionPreference = "Stop"

$Repo    = "mkiser/wtf-transcription-factory"
$Branch  = "main"
$Name    = "WTF Transcription Factory"
$CodeDir = Join-Path $env:LOCALAPPDATA $Name

function Say($m) { Write-Host "`n$m" -ForegroundColor Cyan }

Say "Installing $Name ..."

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue }
if (-not $py) {
  Say "First you need Python (it's free and takes ~2 minutes)."
  Start-Process "https://www.python.org/downloads/"
  Write-Host "  1. Install Python from the page that just opened."
  Write-Host "     IMPORTANT: tick 'Add Python to PATH' during setup."
  Write-Host "  2. Then run the same install command again."
  return
}

Say "Downloading the latest version ..."
$tmp = Join-Path $env:TEMP ("wtf_" + [System.Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp | Out-Null
$zip = Join-Path $tmp "src.zip"
Invoke-WebRequest -Uri "https://codeload.github.com/$Repo/zip/refs/heads/$Branch" -OutFile $zip
Expand-Archive -Path $zip -DestinationPath $tmp -Force
$src = Join-Path $tmp "wtf-transcription-factory-$Branch"
if (-not (Test-Path $CodeDir)) { New-Item -ItemType Directory -Path $CodeDir | Out-Null }
Get-ChildItem -Path $src -Force |
  Where-Object { $_.Name -notin @('.venv', 'transcripts') } |
  ForEach-Object { Copy-Item $_.FullName -Destination $CodeDir -Recurse -Force }
Remove-Item $tmp -Recurse -Force

Say "Setting things up (first time takes a few minutes) ..."
& $py.Source -m venv (Join-Path $CodeDir ".venv")
$venvPy = Join-Path $CodeDir ".venv\Scripts\python.exe"
& $venvPy -m pip install --quiet --upgrade pip
& $venvPy -m pip install --quiet -r (Join-Path $CodeDir "app\requirements.txt")

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
