#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Double-click this file in Finder to update Sermon Transcriber.
# ---------------------------------------------------------------------------

cd "$(dirname "$0")"
./update.sh || echo "Update did not finish — see the message above."
echo ""
read -rp "Press Enter to close..." _
