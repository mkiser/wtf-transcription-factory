#!/bin/bash
#
#  WTF Transcription Factory — installer
#
#  Run this in Terminal:
#    curl -fsSL https://raw.githubusercontent.com/mkiser/wtf-transcription-factory/main/install.sh | bash
#
#  Requires only Python 3. It downloads the app, sets up its own private
#  environment, and (on macOS) puts a double-click launcher on your Desktop.
#  Nothing is quarantined by Gatekeeper because it's all built on your machine.
#
set -eu

REPO="mkiser/wtf-transcription-factory"
BRANCH="main"
NAME="WTF Transcription Factory"
CODE_DIR="$HOME/.wtf-transcription-factory"

bold() { printf "\n\033[1m%s\033[0m\n" "$1"; }
info() { printf "   %s\n" "$1"; }

bold "🎙️  Installing ${NAME}"

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

bold "Downloading the latest version…"
TMP="$(mktemp -d)"
curl -fsSL "https://codeload.github.com/${REPO}/tar.gz/refs/heads/${BRANCH}" -o "${TMP}/src.tgz"
tar -xzf "${TMP}/src.tgz" -C "${TMP}"
SRC="${TMP}/wtf-transcription-factory-${BRANCH}"
mkdir -p "${CODE_DIR}"
( cd "${SRC}" && find . -maxdepth 1 -mindepth 1 ! -name '.venv' ! -name 'transcripts' \
    -exec cp -R {} "${CODE_DIR}/" \; )
rm -rf "${TMP}"

bold "Setting things up (first time takes a few minutes)…"
[ -d "${CODE_DIR}/.venv" ] || python3 -m venv "${CODE_DIR}/.venv"
"${CODE_DIR}/.venv/bin/python" -m pip install --quiet --upgrade pip
"${CODE_DIR}/.venv/bin/python" -m pip install --quiet -r "${CODE_DIR}/app/requirements.txt"

LAUNCHER=""
if [ "$(uname)" = "Darwin" ]; then
  bold "Creating your double-click launcher…"
  rm -rf "$HOME/Applications/${NAME}.app"   # remove the old applet from earlier versions
  LAUNCHER="$HOME/Desktop/${NAME}.command"
  cat > "${LAUNCHER}" <<'CMD'
#!/bin/bash
cd "$HOME/.wtf-transcription-factory" || exit 1
echo "🎙️  WTF Transcription Factory"
echo
echo "Your browser will open in a moment."
echo "Keep this window open while you use it — close it (or press Control-C) to stop."
echo
exec ".venv/bin/python" app/app.py
CMD
  chmod +x "${LAUNCHER}"
fi

bold "✅ All set!"
if [ -n "${LAUNCHER}" ]; then
  info "A “${NAME}” launcher is on your Desktop — double-click it any time to run."
  info "Starting it now…"
  open "${LAUNCHER}" || true
else
  info "To run it again later:"
  info "  \"${CODE_DIR}/.venv/bin/python\" \"${CODE_DIR}/app/app.py\""
  ( "${CODE_DIR}/.venv/bin/python" "${CODE_DIR}/app/app.py" >/dev/null 2>&1 & )
fi
