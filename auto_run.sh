#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# What the launchd agent runs (at run_times and at login — see agent.sh).
#
#   1. Once a day, update an installed copy to the newest release (update.sh)
#   2. Run the automatic job, keeping the Mac awake while it works
#   3. If another run is due later today, keep the Mac awake until then
#
# Output goes to logs/agent.log in the settings folder.
# ---------------------------------------------------------------------------
set -uo pipefail

main() {
    local code_dir py home stamp
    code_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    py="$code_dir/.venv/bin/python3"
    if [[ ! -x "$py" ]]; then
        echo "$(date '+%F %T') ERROR: $py missing — run update.sh"
        return 1
    fi
    export PATH="$code_dir/.venv/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    home="$("$py" "$code_dir/app_home.py")" || return 1

    # Keep agent.log from growing without limit (one previous copy kept)
    local agent_log="$home/logs/agent.log"
    if [[ -f "$agent_log" ]] && (( $(stat -f %z "$agent_log") > 5000000 )); then
        mv -f "$agent_log" "$agent_log.1"
    fi

    # Daily update, installed copies only (a development checkout is left alone)
    stamp="$home/last_update"
    if [[ "$(git -C "$code_dir" config --get sermon-transcriber.deploy 2>/dev/null)" == "true" &&
          "$(cat "$stamp" 2>/dev/null)" != "$(date +%F)" ]]; then
        echo "$(date '+%F %T') Daily update check"
        if "$code_dir/update.sh"; then
            date +%F > "$stamp"
        fi
    fi

    echo "$(date '+%F %T') Checking for new recordings"
    # caffeinate -i: no idle sleep while Whisper runs (a long sermon on an Intel Mac can take an hour)
    /usr/bin/caffeinate -i "$py" "$code_dir/auto_transcribe.py"
    local status=$?

    # Sunday 1 pm → keep awake until just after 7 pm, and so on. A timed
    # caffeinate only stops idle sleep: choosing Sleep or shutting down still works.
    local seconds pidfile="$home/stay_awake.pid"
    seconds="$(cd "$code_dir" && "$py" agent_schedule.py stay-awake-seconds 2>/dev/null || echo 0)"
    # Replace the previous run's timer (only if that process is still a caffeinate)
    if [[ -f "$pidfile" && "$(ps -p "$(cat "$pidfile")" -o comm= 2>/dev/null)" == *caffeinate ]]; then
        kill "$(cat "$pidfile")" 2>/dev/null
    fi
    rm -f "$pidfile"
    if (( seconds > 0 )); then
        /usr/bin/caffeinate -i -t "$seconds" >/dev/null 2>&1 &
        echo $! > "$pidfile"
        echo "$(date '+%F %T') Keeping the Mac awake for the next run ($((seconds / 60)) min)"
    fi
    return $status
}

# main is read in full before it runs, so a same-run update can't confuse it
main "$@"
