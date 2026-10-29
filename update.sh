#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Bring this copy up to date: newest release code, then the Python
# environment, the bundled ffmpeg and the settings folder.
#
# Safe to run any time — each step only does work when something changed.
#
# Code is only moved on copies made by install.sh (marked with the git
# setting sermon-transcriber.deploy=true). Those follow the newest v* release
# tag, or the default branch if no release has been tagged yet. Any edits
# made inside such a copy are discarded; settings live outside it.
# A development checkout just gets its environment synced.
#
# Usage:
#   ./update.sh                    # update code + environment
#   ./update.sh --no-fetch         # environment only, don't contact GitHub
#   ./update.sh --download-model   # also pre-download the Whisper model
#
# SERMON_TRANSCRIBER_REF=<tag or branch> pins a copy to that version.
# ---------------------------------------------------------------------------
set -euo pipefail

# uv release installed when none is found. Keep in sync with install.sh.
UV_VERSION="0.12.24"
WHISPER_MODEL="turbo"

find_uv() {
    local candidate
    for candidate in "$(command -v uv 2>/dev/null || true)" \
                     "${UV_INSTALL_DIR:-}/uv" \
                     "$HOME/.local/bin/uv"; do
        if [[ -n "$candidate" && -x "$candidate" ]]; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

newest_release_tag() {
    git -C "$CODE_DIR" tag -l 'v*' --sort=-v:refname | head -1
}

update_code() {
    local fetch="$1"
    if [[ "$(git -C "$CODE_DIR" config --get sermon-transcriber.deploy || true)" != "true" ]]; then
        echo "Development checkout — code left as is."
        return 1
    fi

    if [[ "$fetch" == true ]]; then
        if ! git -C "$CODE_DIR" fetch --quiet --tags --prune --prune-tags origin; then
            echo "WARNING: could not reach GitHub — keeping the current version."
            return 1
        fi
    fi

    local target="${SERMON_TRANSCRIBER_REF:-$(newest_release_tag)}"
    [[ -z "$target" ]] && target="origin/HEAD"
    local new cur
    if ! new="$(git -C "$CODE_DIR" rev-parse --verify --quiet "$target^{commit}")"; then
        echo "WARNING: version '$target' not found — keeping the current version."
        return 1
    fi
    cur="$(git -C "$CODE_DIR" rev-parse HEAD)"

    if [[ "$new" == "$cur" ]]; then
        echo "Code is up to date ($(git -C "$CODE_DIR" describe --tags --always))."
        return 1
    fi

    local old_desc
    old_desc="$(git -C "$CODE_DIR" describe --tags --always)"
    # (errexit is off inside an if-condition, so check failures explicitly)
    if ! git -C "$CODE_DIR" checkout --quiet --force --detach "$new"; then
        echo "WARNING: could not switch to $target — keeping the current version."
        return 1
    fi
    echo "Updated code: $old_desc → $(git -C "$CODE_DIR" describe --tags --always)"
    return 0
}

sync_environment() {
    local uv
    if ! uv="$(find_uv)"; then
        echo "uv not found — installing uv $UV_VERSION..."
        curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" | env UV_NO_MODIFY_PATH=1 sh
        uv="$(find_uv)" || { echo "ERROR: uv install failed." >&2; exit 1; }
    fi

    echo "Checking Python environment (a first install downloads Python and packages)..."
    # only-managed: use uv's own Python download, never whatever else is installed
    UV_PYTHON_PREFERENCE=only-managed \
        "$uv" sync --frozen --quiet --project "$CODE_DIR"

    # Whisper runs "ffmpeg" by name — point it at the binary bundled by
    # imageio-ffmpeg so no Homebrew install is needed.
    local py="$CODE_DIR/.venv/bin/python3" ffmpeg
    ffmpeg="$("$py" -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())')"
    ln -sf "$ffmpeg" "$CODE_DIR/.venv/bin/ffmpeg"

    "$py" "$CODE_DIR/app_home.py" >/dev/null

    # The newest yt-dlp for the YouTube launchers (see youtube_download.py), so
    # it's ready before it's needed. Not pinned: YouTube changes too often.
    UV_PYTHON_PREFERENCE=only-managed \
        "$uv" tool run --quiet --python 3.12 --from 'yt-dlp[default]@latest' --with deno \
        yt-dlp --version >/dev/null 2>&1 || echo "Note: couldn't fetch yt-dlp (only needed for YouTube)."
}

download_model() {
    echo "Downloading the Whisper '$WHISPER_MODEL' model if needed (about 1.5 GB, one time)..."
    "$CODE_DIR/.venv/bin/python3" -c \
        "import whisper; whisper.load_model('$WHISPER_MODEL', device='cpu')"
}

main() {
    CODE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    local fetch=true model=false arg
    for arg in "$@"; do
        case "$arg" in
            --no-fetch)       fetch=false ;;
            --download-model) model=true  ;;
            *) echo "Unknown option: $arg" >&2; exit 2 ;;
        esac
    done

    if update_code "$fetch"; then
        # Re-run the new version's own update steps
        local rerun=(--no-fetch)
        [[ "$model" == true ]] && rerun+=(--download-model)
        exec "$CODE_DIR/update.sh" "${rerun[@]}"
    fi

    sync_environment
    [[ "$model" == true ]] && download_model
    echo "Ready."
}

# Everything runs from main, which bash reads in full before starting, so a
# code update that replaces this file mid-run can't confuse it.
main "$@"
