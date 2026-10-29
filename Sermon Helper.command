#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Double-click this file in Finder to fix or finish a sermon's documents —
# e.g. when the preacher wasn't in the preaching schedule. Plain Mac dialogs
# walk you through it; this Terminal window shows progress.
# ---------------------------------------------------------------------------

cd "$(dirname "$0")"
# Sets up the Python environment and settings folder
source ./pipeline_helpers.sh || { read -rp "Press Enter to close..." _; exit 1; }

if python3 sermon_helper.py; then
    echo ""
    echo "Sermon Helper is finished — you can close this window."
else
    echo ""
    echo "Sermon Helper stopped with an error (see above)."
    read -rp "Press Enter to close..." _
fi
