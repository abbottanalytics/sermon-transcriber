#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Double-click to download a YouTube video's audio or video: paste the link,
# pick audio or video. Files go in Downloads/YouTube (youtube_dir in
# config.txt). This Terminal window shows progress.
# ---------------------------------------------------------------------------

cd "$(dirname "$0")"
# Sets up the Python environment and settings folder
source ./pipeline_helpers.sh || { read -rp "Press Enter to close..." _; exit 1; }

if python3 youtube_download.py; then
    echo ""
    echo "Finished — you can close this window."
else
    echo ""
    echo "Stopped with an error (see above)."
    read -rp "Press Enter to close..." _
fi
