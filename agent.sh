#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Set up the background agent that processes new recordings automatically.
#
#   ./agent.sh install          Start the agent (now, at run_times, at login)
#   ./agent.sh uninstall        Stop and remove it
#   ./agent.sh status           Is it running, and what did it last do
#   ./agent.sh run-now          Run a check right now
#   ./agent.sh power-schedule   Wake / power on the Mac before the first run (admin)
#
# Before installing, set watch_dir (and api_key) in config.txt in the
# settings folder. The agent runs auto_run.sh → auto_transcribe.py, at the
# run_times in config.txt (default Sundays 1 pm, 7 pm and 11 pm; see
# agent_schedule.py). After changing run_times, run ./agent.sh install again.
#
# The agent only runs while someone is logged in to this Mac; turn on
# automatic login if it must survive a restart unattended (see README).
# ---------------------------------------------------------------------------
set -euo pipefail

LABEL="${SERMON_TRANSCRIBER_AGENT_LABEL:-local.sermon-transcriber}"
# Passed through to the agent when set — for testing with a scratch settings folder
PASS_THROUGH_VARS=(SERMON_TRANSCRIBER_HOME SERMON_TRANSCRIBER_NO_NOTIFY XDG_CACHE_HOME)

CODE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$CODE_DIR/.venv/bin/python3"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

fail() { echo "ERROR: $*" >&2; exit 1; }

settings_home() { "$PY" "$CODE_DIR/app_home.py"; }

config_value() {
    "$PY" -c "import sys; sys.path.insert(0, sys.argv[1]); from app_home import read_config; print(read_config().get(sys.argv[2], ''))" \
        "$CODE_DIR" "$1"
}

build_launcher() {
    local launcher="$1"
    [[ -x "$launcher" ]] && return 0
    command -v clang >/dev/null 2>&1 ||
        fail "clang not found — install Apple's Command Line Tools (xcode-select --install)."
    mkdir -p "$(dirname "$launcher")"
    clang -O2 -o "$launcher" "$CODE_DIR/agent_launcher.c"
    codesign --force --sign - --identifier "$LABEL.agent" "$launcher" 2>/dev/null || true
    echo "Built $launcher"
}

write_plist() {
    local launcher="$1" home="$2"
    local env_args=() var
    for var in "${PASS_THROUGH_VARS[@]}"; do
        [[ -n "${!var:-}" ]] && env_args+=("$var=${!var}")
    done
    mkdir -p "$(dirname "$PLIST")" "$home/logs"
    local intervals
    intervals="$(cd "$CODE_DIR" && "$PY" agent_schedule.py launchd)" || exit 1
    "$PY" - "$PLIST" "$LABEL" "$launcher" "$CODE_DIR/auto_run.sh" "$home/logs/agent.log" \
        "$intervals" ${env_args[@]+"${env_args[@]}"} <<'EOF'
import json, plistlib, sys
plist_path, label, launcher, script, log, intervals, *env = sys.argv[1:]
job = {
    "Label": label,
    "ProgramArguments": [launcher, script],
    "RunAtLoad": True,                 # at login / restart: catch up after a shutdown
    # The run times; one missed while the Mac slept runs as soon as it wakes
    "StartCalendarInterval": json.loads(intervals),
    # auto_run.sh leaves a timed caffeinate running to keep the Mac awake until
    # the next run today; without this launchd would stop it when the job ends
    "AbandonProcessGroup": True,
    "StandardOutPath": log,
    "StandardErrorPath": log,
}
if env:
    job["EnvironmentVariables"] = dict(item.split("=", 1) for item in env)
with open(plist_path, "wb") as f:
    plistlib.dump(job, f)
EOF
}

cmd_install() {
    [[ -x "$PY" ]] || fail "Python environment missing — run ./update.sh first."
    local home watch launcher
    home="$(settings_home)"
    watch="$(config_value watch_dir)"
    [[ -n "$watch" ]] || fail "Set watch_dir in $home/config.txt first (the folder recordings land in)."
    [[ -n "$(config_value api_key)" || -n "${OPENAI_API_KEY:-}" ]] ||
        echo "WARNING: no api_key in config.txt yet — sermons will wait until one is added."

    launcher="$home/bin/SermonTranscriberAgent"
    build_launcher "$launcher"
    write_plist "$launcher" "$home"

    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    launchctl bootstrap "$DOMAIN" "$PLIST"
    echo "Agent installed: $LABEL"
    echo "  Runs now, at login, and at: $(cd "$CODE_DIR" && "$PY" agent_schedule.py show)"

    # The first run starts immediately — give it a moment, then check access
    sleep 8
    if "$PY" -c "import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get('state',{}).get('access_denied') else 1)" \
        "$home/processed.json" 2>/dev/null; then
        echo ""
        echo "macOS is blocking the agent from reading $watch."
        echo "Give it Full Disk Access, once:"
        echo "  1. System Settings → Privacy & Security → Full Disk Access opens now"
        echo "  2. Click +, and choose the SermonTranscriberAgent file Finder is showing"
        echo "     (or press Cmd-Shift-G and paste: $launcher)"
        echo "  3. Then run:  ./agent.sh run-now"
        open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles" || true
        open -R "$launcher" || true
    else
        echo "Access check passed. Watching: $watch"
    fi
}

cmd_uninstall() {
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "Agent removed. (Settings, outputs and processed.json are kept.)"
}

cmd_status() {
    if ! launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
        echo "Agent is not installed."
        return 0
    fi
    # top-level fields only (one tab of indent)
    launchctl print "$DOMAIN/$LABEL" | grep -E $'^\t(state|runs|last exit code) =' | sed $'s/^\t/  /'
    echo "  runs at: $(cd "$CODE_DIR" && "$PY" agent_schedule.py show), and at login"
    local home
    home="$(settings_home)"
    echo "Recent activity ($home/logs/auto.log):"
    tail -n 8 "$home/logs/auto.log" 2>/dev/null | sed 's/^/  /' || echo "  (none yet)"
}

cmd_run_now() {
    launchctl kickstart "$DOMAIN/$LABEL" || fail "Agent is not installed — run ./agent.sh install"
    echo "Started a check. Follow it with:  tail -f \"$(settings_home)/logs/agent.log\""
}

cmd_power_schedule() {
    local wake day time
    wake="$(cd "$CODE_DIR" && "$PY" agent_schedule.py wake-time)" || exit 1
    read -r day time <<< "$wake"
    echo "Current power schedule:"
    pmset -g sched | sed 's/^/  /'
    echo ""
    echo "This sets the Mac to wake (or power on, if it was shut down) at $time every"
    echo "week (pmset day '$day'), just before the first run. Each run then keeps it"
    echo "awake until the next run that day. It REPLACES any repeating schedule shown"
    echo "above. Needs an admin password."
    read -rp "Continue? [y/N] " answer
    [[ "$answer" == [yY]* ]] || { echo "No change."; return 0; }
    sudo pmset repeat wakeorpoweron "$day" "$time"
    pmset -g sched | sed 's/^/  /'
}

case "${1:-}" in
    install)        cmd_install ;;
    uninstall)      cmd_uninstall ;;
    status)         cmd_status ;;
    run-now)        cmd_run_now ;;
    power-schedule) cmd_power_schedule ;;
    *) sed -n '3,9p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
