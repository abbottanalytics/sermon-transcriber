#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Double-click to check for new recordings right now, instead of waiting for
# the next scheduled check (Sundays 1 pm, 7 pm and 11 pm). The check runs in
# the background: you can close this window, and a notification says what
# was done.
# ---------------------------------------------------------------------------

cd "$(dirname "$0")"
if ./agent.sh run-now >/dev/null 2>&1; then
    echo "Checking for new recordings now."
    echo "A notification will say what was transcribed. Each recording takes"
    echo "up to an hour on this Mac. You can close this window."
else
    echo "The automatic processing isn't set up on this Mac (see README, \"Option 4\")."
fi
read -rp "Press Enter to close..." _
