#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Shared helper functions sourced by run_interactive.sh and run_pipeline.command
# Do not run this file directly.
# ---------------------------------------------------------------------------

HELPERS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Use the project's own Python environment (and its bundled ffmpeg) when it
# has been set up by install.sh / update.sh; otherwise fall back to whatever
# python3 is on the PATH.
if [[ -x "$HELPERS_DIR/.venv/bin/python3" ]]; then
    export PATH="$HELPERS_DIR/.venv/bin:$PATH"
fi

# Per-machine settings live outside the code folder so updates never touch
# them (see app_home.py). Missing files are created from templates/.
if ! APP_HOME="$(python3 "$HELPERS_DIR/app_home.py")"; then
    echo "ERROR: could not set up the settings folder (see message above)." >&2
    return 1
fi
CONFIG_FILE="$APP_HOME/config.txt"
PREACHERS_FILE="$APP_HOME/preachers.txt"
EVENTS_FILE="$APP_HOME/events.txt"
SCHEDULES_DIR="$APP_HOME/schedules"

# Once a speaker reaches this count their entry is capped at "N+"
# and never incremented again. Change this value if you want a
# different threshold.
PREACHER_CAP=5

# ---------------------------------------------------------------------------
# read_config
# Sets DEFAULT_INPUT and DEFAULT_OUTPUT from config.txt
# ---------------------------------------------------------------------------
read_config() {
    DEFAULT_INPUT=""
    DEFAULT_OUTPUT=""
    DEFAULT_SCHEDULE=""
    ENABLE_SERMONS=true
    ENABLE_TALKS=true
    ENABLE_MEETINGS=true
    if [[ ! -f "$CONFIG_FILE" ]]; then return; fi

    while IFS='=' read -r key value; do
        # Skip comments and blank lines
        [[ "$key" =~ ^[[:space:]]*# ]] && continue
        [[ -z "${key// /}" ]] && continue
        key="${key// /}"
        # Strip leading/trailing whitespace and surrounding quotes from value
        value="${value#"${value%%[![:space:]]*}"}"  # ltrim
        value="${value%"${value##*[![:space:]]}"}"  # rtrim
        value="${value#\"}" ; value="${value%\"}"   # strip double quotes
        value="${value#\'}" ; value="${value%\'}"   # strip single quotes
        case "$key" in
            api_key)
                # Only set from config if not already in environment,
                # and not the template's placeholder
                if [[ -n "$value" && "$value" != "sk-paste-your-key-here" &&
                      -z "${OPENAI_API_KEY:-}" ]]; then
                    export OPENAI_API_KEY="$value"
                fi
                ;;
            input_dir)       DEFAULT_INPUT="$value"    ;;
            output_dir)      DEFAULT_OUTPUT="$value"   ;;
            schedule_file)   DEFAULT_SCHEDULE="$value" ;;
            enable_sermons)  ENABLE_SERMONS="$value"   ;;
            enable_talks)    ENABLE_TALKS="$value"     ;;
            enable_meetings) ENABLE_MEETINGS="$value"  ;;
        esac
    done < "$CONFIG_FILE"
}


# ---------------------------------------------------------------------------
# update_preacher_count NAME
# Increments count for NAME in preachers.txt, or adds with count 1.
#
# Count states:
#   (missing/empty) — treat as 0; not yet in menu
#   1               — preached once; not yet in menu
#   2, 3, 4         — appears in selection menu
#   5+ (or N+)      — capped; always in menu; count never incremented again
#
# Count is incremented only once per pipeline run, not once per file,
# so batch-processing a directory doesn't over-inflate the count.
# ---------------------------------------------------------------------------
update_preacher_count() {
    local name="$1"
    [[ -z "$name" ]] && return

    local tmpfile
    tmpfile=$(mktemp)
    local found=false
    local cap_str="${PREACHER_CAP}+"

    if [[ -f "$PREACHERS_FILE" ]]; then
        while IFS= read -r line; do
            # Preserve comment and blank lines
            if [[ "$line" =~ ^# || -z "$line" ]]; then
                echo "$line" >> "$tmpfile"
                continue
            fi
            local pname count
            IFS='|' read -r pname count <<< "$line"
            if [[ "$pname" == "$name" ]]; then
                found=true
                if [[ "$count" == "$cap_str" ]]; then
                    # Already capped — do not increment
                    echo "$pname|$cap_str" >> "$tmpfile"
                elif [[ "$count" =~ ^[0-9]+$ ]]; then
                    local new_count=$(( count + 1 ))
                    if (( new_count >= PREACHER_CAP )); then
                        echo "$pname|$cap_str" >> "$tmpfile"
                    else
                        echo "$pname|$new_count" >> "$tmpfile"
                    fi
                else
                    # Missing or unrecognised count — start at 1
                    echo "$pname|1" >> "$tmpfile"
                fi
            else
                echo "$line" >> "$tmpfile"
            fi
        done < "$PREACHERS_FILE"
    fi

    if [[ "$found" == false ]]; then
        echo "$name|1" >> "$tmpfile"
    fi

    mv "$tmpfile" "$PREACHERS_FILE"
}


# ---------------------------------------------------------------------------
# select_speaker
# Sets SPEAKER variable. Shows two-column list of speakers with 2+ sermons.
# ---------------------------------------------------------------------------
select_speaker() {
    SPEAKER=""

    # Load speakers with count >= 2 (or capped at N+)
    local speakers=()
    local cap_str="${PREACHER_CAP}+"
    if [[ -f "$PREACHERS_FILE" ]]; then
        while IFS= read -r line; do
            [[ "$line" =~ ^# || -z "$line" ]] && continue
            local pname count
            IFS='|' read -r pname count <<< "$line"
            # Include if capped (5+) OR numeric count >= 2
            if [[ "$count" == "$cap_str" ]] ||
               { [[ "$count" =~ ^[0-9]+$ ]] && (( count >= 2 )); }; then
                speakers+=("$pname")
            fi
        done < "$PREACHERS_FILE"
    fi

    echo "Select speaker:"
    echo ""

    # Two-column display of speakers with 2+ count
    local n=${#speakers[@]}
    local col_width=36
    for (( i=0; i<n; i+=2 )); do
        local left="$((i+1))) ${speakers[$i]}"
        if (( i+1 < n )); then
            local right="$((i+2))) ${speakers[$((i+1))]}"
            printf "  %-${col_width}s %s\n" "$left" "$right"
        else
            printf "  %s\n" "$left"
        fi
    done

    local other_num=$(( n + 1 ))
    echo ""
    printf "  %s\n" "$other_num) Other (enter manually)"
    echo ""
    read -rp "Choice [1-$other_num]: " speaker_choice

    if [[ "$speaker_choice" =~ ^[0-9]+$ ]] &&
       (( speaker_choice >= 1 && speaker_choice <= n )); then
        SPEAKER="${speakers[$((speaker_choice - 1))]}"
    else
        echo ""
        read -rp "Speaker name (with title, e.g. 'Pastor Joel Wood'): " SPEAKER
    fi

    # Persist count
    [[ -n "$SPEAKER" ]] && update_preacher_count "$SPEAKER"
}


# ---------------------------------------------------------------------------
# select_event SECTION
# Sets EVENT variable. SECTION is "sermon" or "talk".
# ---------------------------------------------------------------------------
select_event() {
    local section="$1"
    EVENT=""

    # Parse events.txt for the given section
    local events=()
    local current_section=""

    if [[ -f "$EVENTS_FILE" ]]; then
        while IFS= read -r line; do
            [[ "$line" =~ ^# ]] && continue
            if [[ "$line" =~ ^\[(.+)\]$ ]]; then
                current_section="${BASH_REMATCH[1]}"
                continue
            fi
            [[ -z "$line" ]] && continue
            [[ "$current_section" == "$section" ]] && events+=("$line")
        done < "$EVENTS_FILE"
    fi

    if [[ "$section" == "sermon" ]]; then
        echo "Select the service or event:"
    else
        echo "Select the conference or event:"
    fi
    echo ""

    local n=${#events[@]}
    for (( i=0; i<n; i++ )); do
        echo "  $((i+1))) ${events[$i]}"
    done
    local new_num=$(( n + 1 ))
    echo "  $new_num) Enter a different name"
    echo ""
    read -rp "Choice [1-$new_num]: " event_choice

    if [[ "$event_choice" =~ ^[0-9]+$ ]] &&
       (( event_choice >= 1 && event_choice <= n )); then
        EVENT="${events[$((event_choice - 1))]}"
    else
        echo ""
        if [[ "$section" == "sermon" ]]; then
            read -rp "Event name: " EVENT
        else
            read -rp "Conference/event name: " EVENT
        fi
    fi
}
