#!/bin/bash
#
#  WTF Transcription Factory — installer
#
#  Run this in Terminal:
#    curl -fsSL https://raw.githubusercontent.com/mkiser/wtf-transcription-factory/main/install.sh | bash
#
#  You don't need to install anything first. It downloads the app and its own
#  private copy of Python, sets up its own environment, and (on macOS) puts a
#  double-click launcher on your Desktop.
#  Nothing is quarantined by Gatekeeper because it's all built on your machine.
#
set -eu

REPO="mkiser/wtf-transcription-factory"
BRANCH="main"
NAME="WTF Transcription Factory"
CODE_DIR="$HOME/.wtf-transcription-factory"
VENV_PY="${CODE_DIR}/.venv/bin/python"
UV_VERSION="0.13.4"
# 3.12 has wheels for every dependency on the most systems. 3.13 and 3.14 lock
# out older Macs, and onnxruntime has no wheel for 3.15.
PYTHON_VERSION="3.12"

bold() { printf "\n\033[1m%s\033[0m\n" "$1"; }
info() { printf "   %s\n" "$1"; }

give_up() {
  bold "The install didn't finish: $1"
  info "Check your internet connection and close the app if it's open."
  info "Then paste the same install command again."
  info "The installer needs to reach github.com, astral.sh, and pypi.org."
  exit 1
}

# An environment on Python 3.10 to 3.14 with its main packages already works, so
# an update leaves it in place. Anything else, such as an interrupted install or
# a failed one on 3.15, gets rebuilt.
env_works() {
  "$VENV_PY" -c 'import sys, pip, av, faster_whisper, flask; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,14) else 1)' >/dev/null 2>&1
}

build_env() {
  info "Downloading a private copy of Python…"
  # uv fetches the Python. Everything stays inside the app's folder, and the
  # user's shell setup and any Python they already have are left alone.
  export UV_UNMANAGED_INSTALL="${CODE_DIR}/bin"
  export UV_PYTHON_INSTALL_DIR="${CODE_DIR}/python"
  export UV_CACHE_DIR="${CODE_DIR}/.uv-cache"
  curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" -o "${TMP}/uv-install.sh" || give_up "couldn't download uv."
  sh "${TMP}/uv-install.sh" >/dev/null || give_up "couldn't install uv."
  rm -rf "${CODE_DIR}/.venv"
  # --seed installs pip, which the app uses to refresh yt-dlp.
  "${CODE_DIR}/bin/uv" venv --quiet --seed --python "${PYTHON_VERSION}" --managed-python "${CODE_DIR}/.venv" || give_up "couldn't set up Python."
}

# Wheels only: most people have no compiler, so a source build can only fail.
install_deps() {
  "$VENV_PY" -m pip install --quiet --upgrade pip &&
    "$VENV_PY" -m pip install --quiet --only-binary=:all: -r "${CODE_DIR}/app/requirements.txt"
}

bold "🎙️  Installing ${NAME}"

bold "Downloading the latest version…"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
curl -fsSL "https://codeload.github.com/${REPO}/tar.gz/refs/heads/${BRANCH}" -o "${TMP}/src.tgz" || give_up "couldn't download the app."
tar -xzf "${TMP}/src.tgz" -C "${TMP}"
SRC="${TMP}/wtf-transcription-factory-${BRANCH}"
mkdir -p "${CODE_DIR}"
( cd "${SRC}" && find . -maxdepth 1 -mindepth 1 ! -name '.venv' ! -name 'transcripts' \
    -exec cp -R {} "${CODE_DIR}/" \; )

bold "Setting things up (first time takes a few minutes)…"
env_works || build_env
info "Installing the speech engine and audio tools. Keep this window open."
if ! install_deps; then
  info "That didn't work. Rebuilding the app's environment and trying once more."
  build_env
  install_deps || give_up "couldn't install the app's components."
fi

LAUNCHER=""
if [ "$(uname)" = "Darwin" ]; then
  bold "Creating your double-click launcher…"
  DESKTOP_LAUNCHER="$HOME/Desktop/${NAME}.command"
  if cat > "${DESKTOP_LAUNCHER}" <<'CMD' && chmod +x "${DESKTOP_LAUNCHER}"; then
#!/bin/bash
cd "$HOME/.wtf-transcription-factory" || exit 1
echo "🎙️  WTF Transcription Factory"
echo
echo "Your browser will open in a moment."
echo "Keep this window open while you use it — close it (or press Control-C) to stop."
echo
exec ".venv/bin/python" app/app.py
CMD
    LAUNCHER="${DESKTOP_LAUNCHER}"
    rm -rf "$HOME/Applications/${NAME}.app"   # remove the old applet from earlier versions
  else
    info "Couldn't put a launcher on your Desktop, so use the command below instead."
  fi
fi

bold "✅ All set!"
if [ -n "${LAUNCHER}" ]; then
  info "A “${NAME}” launcher is on your Desktop — double-click it any time to run."
  info "Starting it now…"
  open "${LAUNCHER}" || true
else
  info "To run it again later:"
  info "  \"${VENV_PY}\" \"${CODE_DIR}/app/app.py\""
  info "Starting it now. If nothing opens, the log is at ${CODE_DIR}/app.log"
  ( "${VENV_PY}" "${CODE_DIR}/app/app.py" >"${CODE_DIR}/app.log" 2>&1 & )
fi
