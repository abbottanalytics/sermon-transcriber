#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Install Sermon Transcriber on a Mac (Intel or Apple Silicon).
#
# Paste into Terminal:
#   curl -fsSL https://raw.githubusercontent.com/abbottanalytics/sermon-transcriber/main/install.sh | bash
#
# What it does:
#   1. Makes sure git (Apple's Command Line Tools) and uv are present
#   2. Downloads the code to ~/Applications/SermonTranscriber
#   3. Sets up its own Python, packages and ffmpeg (nothing system-wide)
#   4. Creates the settings folder ~/Library/Application Support/SermonTranscriber
#   5. Pre-downloads the Whisper speech model
#
# Running it again is safe — an existing install is just updated.
#
# Options (environment variables):
#   SERMON_TRANSCRIBER_REPO   git URL to install from
#   SERMON_TRANSCRIBER_DIR    install location (default ~/Applications/SermonTranscriber)
#   SERMON_TRANSCRIBER_REF    tag or branch to install (default: newest release)
#   SKIP_MODEL_DOWNLOAD=1     skip step 5 (the model downloads on first use instead)
# ---------------------------------------------------------------------------
set -euo pipefail

REPO_URL="${SERMON_TRANSCRIBER_REPO:-https://github.com/abbottanalytics/sermon-transcriber.git}"
INSTALL_DIR="${SERMON_TRANSCRIBER_DIR:-$HOME/Applications/SermonTranscriber}"

# uv release installed when none is found. Keep in sync with update.sh.
UV_VERSION="0.12.24"

fail() { echo ""; echo "ERROR: $*" >&2; exit 1; }

main() {
    echo ""
    echo "================================================"
    echo "  Sermon Transcriber — install"
    echo "================================================"
    echo ""

    [[ "$(uname -s)" == "Darwin" ]] || fail "This installer is for macOS only."

    # ── git ─────────────────────────────────────────────────────────────────
    # /usr/bin/git is only a stub until Apple's Command Line Tools are installed.
    if ! git --version >/dev/null 2>&1; then
        echo "git is needed and comes with Apple's Command Line Tools."
        echo "A window will open to install them (an admin password may be needed)."
        echo "When it finishes, run this installer again."
        xcode-select --install 2>/dev/null || true
        exit 1
    fi

    # ── uv (manages Python and packages) ────────────────────────────────────
    if ! command -v uv >/dev/null 2>&1 &&
       [[ ! -x "${UV_INSTALL_DIR:-/nonexistent}/uv" && ! -x "$HOME/.local/bin/uv" ]]; then
        echo "Installing uv $UV_VERSION..."
        curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" | env UV_NO_MODIFY_PATH=1 sh
    fi

    # ── code ────────────────────────────────────────────────────────────────
    if [[ -d "$INSTALL_DIR/.git" ]]; then
        echo "Existing install found at $INSTALL_DIR — updating it."
    elif [[ -e "$INSTALL_DIR" ]]; then
        fail "$INSTALL_DIR exists but isn't an install. Move it aside and try again."
    else
        echo "Downloading code to $INSTALL_DIR..."
        mkdir -p "$(dirname "$INSTALL_DIR")"
        git clone --quiet "$REPO_URL" "$INSTALL_DIR"
        # Lets update.sh move this copy to new releases
        git -C "$INSTALL_DIR" config sermon-transcriber.deploy true
    fi

    # update.sh picks the release, syncs the environment and settings folder
    local update_args=()
    [[ "${SKIP_MODEL_DOWNLOAD:-}" == "1" ]] || update_args+=(--download-model)
    "$INSTALL_DIR/update.sh" ${update_args[@]+"${update_args[@]}"}

    local settings="$HOME/Library/Application Support/SermonTranscriber"
    [[ -n "${SERMON_TRANSCRIBER_HOME:-}" ]] && settings="$SERMON_TRANSCRIBER_HOME"
    echo ""
    echo "================================================"
    echo "  Installed: $(git -C "$INSTALL_DIR" describe --tags --always)"
    echo "================================================"
    echo ""
    echo "Next: add the OpenAI API key and folders to the settings file:"
    echo ""
    echo "  open -e \"$settings/config.txt\""
    echo ""
    echo "Then double-click run_pipeline.command in:"
    echo "  $INSTALL_DIR"
    echo ""
}

main "$@"
