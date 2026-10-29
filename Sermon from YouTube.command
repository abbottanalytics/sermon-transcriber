#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Double-click when a Sunday service wasn't recorded on this Mac: it takes the
# sermon from the church's YouTube livestream instead and saves it in the
# Sermons folder, named like any other recording. Plain Mac dialogs walk you
# through it; this Terminal window shows progress.
# ---------------------------------------------------------------------------

cd "$(dirname "$0")"
# Sets up the Python environment and settings folder
source ./pipeline_helpers.sh || { read -rp "Press Enter to close..." _; exit 1; }

if python3 youtube_sermon.py; then
    echo ""
    echo "Finished — you can close this window."
else
    echo ""
    echo "Stopped with an error (see above)."
    read -rp "Press Enter to close..." _
fi
