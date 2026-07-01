#!/bin/bash
#
#  WTF Transcription Factory — installer
#
#  Run this in Terminal:
#    curl -fsSL https://raw.githubusercontent.com/mkiser/wtf-transcription-factory/main/install.sh | bash
#
#  It requires only Python 3. It downloads the app, sets up its own private
#  environment, and (on macOS) creates a double-click app you can launch from
#  Launchpad with no security warnings — because an app built on your own
#  machine is never quarantined by Gatekeeper.
#
set -eu

REPO="mkiser/wtf-transcription-factory"
BRANCH="main"
NAME="WTF Transcription Factory"
CODE_DIR="$HOME/.wtf-transcription-factory"
APP="$HOME/Applications/${NAME}.app"

bold() { printf "\n\033[1m%s\033[0m\n" "$1"; }
info() { printf "   %s\n" "$1"; }

bold "🎙️  Installing ${NAME}"

# 1) Require Python 3 -------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
  bold "First you need Python (it's free and takes ~2 minutes)."
  if [ "$(uname)" = "Darwin" ]; then
    open "https://www.python.org/downloads/" >/dev/null 2>&1 || true
  fi
  info "1. Install Python from the page that just opened"
  info "   (or go to https://www.python.org/downloads/)."
  info "2. Then paste the same install command again."
  exit 1
fi

# 2) Download the latest code (no git required) -----------------------------
bold "Downloading the latest version…"
TMP="$(mktemp -d)"
curl -fsSL "https://codeload.github.com/${REPO}/tar.gz/refs/heads/${BRANCH}" -o "${TMP}/src.tgz"
tar -xzf "${TMP}/src.tgz" -C "${TMP}"
SRC="${TMP}/wtf-transcription-factory-${BRANCH}"
mkdir -p "${CODE_DIR}"
# Copy app code + docs, but never clobber an existing venv or your transcripts.
( cd "${SRC}" && find . -maxdepth 1 -mindepth 1 ! -name '.venv' ! -name 'transcripts' \
    -exec cp -R {} "${CODE_DIR}/" \; )
rm -rf "${TMP}"

# 3) Private Python environment + dependencies ------------------------------
bold "Setting things up (first time takes a few minutes)…"
[ -d "${CODE_DIR}/.venv" ] || python3 -m venv "${CODE_DIR}/.venv"
"${CODE_DIR}/.venv/bin/python" -m pip install --quiet --upgrade pip
"${CODE_DIR}/.venv/bin/python" -m pip install --quiet -r "${CODE_DIR}/app/requirements.txt"

# 4) macOS: build a double-click app (created locally = no Gatekeeper warning)
if [ "$(uname)" = "Darwin" ]; then
  bold "Creating the app…"
  rm -rf "${APP}"
  mkdir -p "${APP}/Contents/MacOS"
  cat > "${APP}/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>${NAME}</string>
  <key>CFBundleDisplayName</key><string>${NAME}</string>
  <key>CFBundleIdentifier</key><string>com.wtfjht.transcription-factory</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>launch</string>
</dict></plist>
PLIST
  cat > "${APP}/Contents/MacOS/launch" <<'LAUNCH'
#!/bin/bash
DIR="$HOME/.wtf-transcription-factory"
exec "$DIR/.venv/bin/python" "$DIR/app/app.py"
LAUNCH
  chmod +x "${APP}/Contents/MacOS/launch"
fi

# 5) Launch -----------------------------------------------------------------
bold "✅ All set!"
if [ "$(uname)" = "Darwin" ] && [ -d "${APP}" ]; then
  info "Opening it now. Next time, open \"${NAME}\" from Launchpad or Spotlight."
  open "${APP}" || true
else
  info "To run it again later:"
  info "  \"${CODE_DIR}/.venv/bin/python\" \"${CODE_DIR}/app/app.py\""
  ( "${CODE_DIR}/.venv/bin/python" "${CODE_DIR}/app/app.py" >/dev/null 2>&1 & )
fi
