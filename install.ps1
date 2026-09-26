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

$pyCommand = $null
$pyArgs = @()
$candidates = @(@{ Name = 'python'; Args = @() }, @{ Name = 'py'; Args = @('-3') })
foreach ($candidate in $candidates) {
  $command = Get-Command $candidate.Name -ErrorAction SilentlyContinue
  if ($command) {
    $probeArgs = @($candidate.Args) + @('-c', "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)")
    try {
      & $command.Source @probeArgs 2>$null
      if ($LASTEXITCODE -eq 0) {
        $pyCommand = $command.Source
        $pyArgs = @($candidate.Args)
        break
      }
    } catch {
      continue
    }
  }
}
if (-not $pyCommand) {
  Say "First you need Python 3.10 or newer (it's free and takes ~2 minutes)."
  Start-Process "https://www.python.org/downloads/"
  Write-Host "  1. On the page that just opened, click the small link under the yellow"
  Write-Host "     button: 'Or get the standalone installer for Python 3.x.x'."
  Write-Host "  2. Open it. IMPORTANT: tick 'Add python.exe to PATH', then Install Now."
  Write-Host "  3. Close this PowerShell window, open a new one, and run the same"
  Write-Host "     install command again."
  Write-Host "  Step-by-step guide: https://github.com/$Repo#windows"
  return
}

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
$venvArgs = $pyArgs + @('-m', 'venv', (Join-Path $CodeDir ".venv"))
& $pyCommand @venvArgs
if ($LASTEXITCODE -ne 0) { throw "Virtual environment creation failed." }
$venvPy = Join-Path $CodeDir ".venv\Scripts\python.exe"
& $venvPy -m pip install --quiet --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed." }
& $venvPy -m pip install --quiet -r (Join-Path $CodeDir "app\requirements.txt")
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
