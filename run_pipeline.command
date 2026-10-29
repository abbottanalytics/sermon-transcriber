#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Double-click this file in Finder to run the pipeline.
# Terminal will open and walk you through the steps.
# ---------------------------------------------------------------------------

# Change to the folder where this script lives
cd "$(dirname "$0")"

# Load shared helpers (speaker list, event list, config)
# shellcheck source=pipeline_helpers.sh
source ./pipeline_helpers.sh || { read -rp "Press Enter to close..." _; exit 1; }

# Keep Terminal window open if something goes wrong
trap 'echo ""; echo "Something went wrong. See error above."; read -rp "Press Enter to close..." _' ERR

echo ""
echo "================================================"
echo "  Transcription & Summarization Pipeline"
echo "================================================"
echo ""

# ── Check: OPENAI_API_KEY ────────────────────────────────────────────────────
if [[ -z "${OPENAI_API_KEY:-}" ]]; then
    echo "ERROR: OpenAI API key not found."
    echo ""
    echo "To fix this, open your settings file:"
    echo ""
    echo "  $CONFIG_FILE"
    echo ""
    echo "and add your key on the api_key line:"
    echo ""
    echo "  api_key=sk-paste-your-key-here"
    echo ""
    echo "You can get a key at: https://platform.openai.com/api-keys"
    echo ""
    read -rp "Press Enter to close..." _
    exit 1
fi

# ── Check: Python ────────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "ERROR: Python 3 is not installed."
    echo "Download it from: https://www.python.org/downloads/"
    echo ""
    read -rp "Press Enter to close..." _
    exit 1
fi

# ── Load config defaults ──────────────────────────────────────────────────────
read_config

# ── helper: native macOS file/folder picker via AppleScript ──────────────────
pick_file() {
    osascript -e "POSIX path of (choose file with prompt \"$1\" of type {\"mp3\", \"m4a\", \"wav\", \"mp4\", \"mov\", \"m4v\", \"mkv\", \"webm\", \"txt\"})" 2>/dev/null || true
}

pick_file_from() {
    # $1 = prompt, $2 = default location
    osascript -e "POSIX path of (choose file with prompt \"$1\" default location POSIX file \"$2\" of type {\"mp3\", \"m4a\", \"wav\", \"mp4\", \"mov\", \"m4v\", \"mkv\", \"webm\", \"txt\"})" 2>/dev/null || true
}

pick_folder() {
    osascript -e "POSIX path of (choose folder with prompt \"$1\")" 2>/dev/null || true
}

pick_folder_from() {
    # $1 = prompt, $2 = default location
    osascript -e "POSIX path of (choose folder with prompt \"$1\" default location POSIX file \"$2\")" 2>/dev/null || true
}

pick_docx() {
    osascript -e "POSIX path of (choose file with prompt \"$1\" of type {\"docx\"})" 2>/dev/null || true
}

pick_csv() {
    # $1 = prompt, $2 = optional default folder
    local prompt="$1"
    local default_loc="${2:-}"
    if [[ -n "$default_loc" && -d "$default_loc" ]]; then
        osascript -e "POSIX path of (choose file with prompt \"$prompt\" default location POSIX file \"$default_loc\")" 2>/dev/null || true
    else
        osascript -e "POSIX path of (choose file with prompt \"$prompt\")" 2>/dev/null || true
    fi
}

# ── 1. Content type ──────────────────────────────────────────────────────────
echo "What type of content are you processing?"
echo ""

# Build menu dynamically from enabled types
TYPE_OPTIONS=()
TYPE_LABELS=()
[[ "$ENABLE_SERMONS"  == "true" ]] && TYPE_OPTIONS+=("sermon")  && TYPE_LABELS+=("Sermon")
[[ "$ENABLE_TALKS"    == "true" ]] && TYPE_OPTIONS+=("talk")    && TYPE_LABELS+=("Talk or conference presentation")
[[ "$ENABLE_MEETINGS" == "true" ]] && TYPE_OPTIONS+=("meeting") && TYPE_LABELS+=("Meeting")

if [[ ${#TYPE_OPTIONS[@]} -eq 0 ]]; then
    echo "ERROR: No content types are enabled in config.txt."
    echo "Set at least one of enable_sermons, enable_talks, enable_meetings to true."
    echo ""
    read -rp "Press Enter to close..." _
    exit 1
fi

if [[ ${#TYPE_OPTIONS[@]} -eq 1 ]]; then
    CONTENT_TYPE="${TYPE_OPTIONS[0]}"
    echo "→ Type: $CONTENT_TYPE (only enabled type)"
else
    for (( i=0; i<${#TYPE_OPTIONS[@]}; i++ )); do
        echo "  $((i+1))) ${TYPE_LABELS[$i]}"
    done
    echo ""
    read -rp "Enter choice [1-${#TYPE_OPTIONS[@]}]: " type_choice

    if [[ "$type_choice" =~ ^[0-9]+$ ]] &&
       (( type_choice >= 1 && type_choice <= ${#TYPE_OPTIONS[@]} )); then
        CONTENT_TYPE="${TYPE_OPTIONS[$((type_choice-1))]}"
    else
        echo "Invalid choice. Please re-run."
        read -rp "Press Enter to close..." _
        exit 1
    fi
    echo "→ Type: $CONTENT_TYPE"
fi

echo "→ Type: $CONTENT_TYPE"
echo ""

# ── 2. Input ──────────────────────────────────────────────────────────────────
echo "Select your input — a single audio file OR a folder of audio files."
echo ""
echo "  1) Choose a single file  (opens file picker)"
echo "  2) Choose a folder       (opens folder picker)"
echo ""
read -rp "Enter 1 or 2: " input_mode

INPUT=""
case "$input_mode" in
    1)
        echo "Opening file picker..."
        if [[ -n "$DEFAULT_INPUT" && -e "$DEFAULT_INPUT" ]]; then
            INPUT="$(pick_file_from "Select an audio file or transcript" "$DEFAULT_INPUT")"
        else
            INPUT="$(pick_file "Select an audio file or transcript")"
        fi
        INPUT="${INPUT%$'\n'}"
        ;;
    2)
        echo "Opening folder picker..."
        if [[ -n "$DEFAULT_INPUT" && -e "$DEFAULT_INPUT" ]]; then
            INPUT="$(pick_folder_from "Select the folder containing your audio files" "$DEFAULT_INPUT")"
        else
            INPUT="$(pick_folder "Select the folder containing your audio files")"
        fi
        INPUT="${INPUT%/}"
        INPUT="${INPUT%$'\n'}"
        ;;
    *)
        echo "Invalid choice. Please re-run and enter 1 or 2."
        read -rp "Press Enter to close..." _
        exit 1
        ;;
esac

if [[ -z "$INPUT" ]]; then
    echo "No selection made. Exiting."
    read -rp "Press Enter to close..." _
    exit 1
fi

if [[ ! -e "$INPUT" ]]; then
    echo "ERROR: Could not find: $INPUT"
    read -rp "Press Enter to close..." _
    exit 1
fi

echo "→ Input: $INPUT"

# ── 3. Output directory ───────────────────────────────────────────────────────
echo ""
echo "Where should the output documents be saved?"
echo ""
if [[ -n "$DEFAULT_OUTPUT" ]]; then
    echo "  1) $DEFAULT_OUTPUT  (from config.txt)  ← default"
    echo "  2) Same folder as the input files"
    echo "  3) Choose a different folder  (opens folder picker)"
    echo ""
    read -rp "Choice [1-3, Enter for default]: " output_mode
else
    echo "  1) Same folder as the input files  ← default"
    echo "  2) Choose a different folder  (opens folder picker)"
    echo ""
    read -rp "Choice [1-2, Enter for default]: " output_mode
fi

OUTPUT=""
if [[ -n "$DEFAULT_OUTPUT" ]]; then
    case "$output_mode" in
        ""|1)
            OUTPUT="$DEFAULT_OUTPUT"
            echo "→ Output: $OUTPUT"
            ;;
        2)
            OUTPUT=""
            echo "→ Output: same folder as input"
            ;;
        3)
            echo "Opening folder picker..."
            if [[ -e "$DEFAULT_OUTPUT" ]]; then
                OUTPUT="$(pick_folder_from "Select the output folder" "$DEFAULT_OUTPUT")"
            else
                OUTPUT="$(pick_folder "Select the output folder")"
            fi
            OUTPUT="${OUTPUT%/}" ; OUTPUT="${OUTPUT%$'\n'}"
            [[ -z "$OUTPUT" ]] && echo "No folder selected — using same folder as input." \
                               || echo "→ Output: $OUTPUT"
            ;;
        *) OUTPUT="$DEFAULT_OUTPUT" ; echo "→ Output: $OUTPUT" ;;
    esac
else
    case "$output_mode" in
        2)
            echo "Opening folder picker..."
            OUTPUT="$(pick_folder "Select the output folder")"
            OUTPUT="${OUTPUT%/}" ; OUTPUT="${OUTPUT%$'\n'}"
            [[ -z "$OUTPUT" ]] && echo "No folder selected — using same folder as input." \
                               || echo "→ Output: $OUTPUT"
            ;;
        *) OUTPUT="" ; echo "→ Output: same folder as input" ;;
    esac
fi

# ── 4. Overwrite ──────────────────────────────────────────────────────────────
echo ""
read -rp "Re-process files that already have outputs? [y/N]: " overwrite_choice
OVERWRITE_FLAG=""
[[ "$overwrite_choice" =~ ^[Yy]$ ]] && OVERWRITE_FLAG="--overwrite"

# ── 5. Speaker + event (sermon and talk only) ─────────────────────────────────
SPEAKER=""
SCHEDULE=""
EVENT=""
TALK_TITLE=""

if [[ "$CONTENT_TYPE" == "sermon" || "$CONTENT_TYPE" == "talk" ]]; then
    echo ""
    echo "How should the speaker be identified?"
    echo "  1) Select or enter speaker manually  ← default"
    echo "  2) Use preaching schedule  (auto-assign from filename dates)"
    echo ""
    read -rp "Choice [1-2, Enter for 1]: " speaker_mode

    if [[ "$speaker_mode" == "2" ]]; then
        if [[ -n "${DEFAULT_SCHEDULE:-}" && -f "$DEFAULT_SCHEDULE" ]]; then
            echo ""
            echo "  Default schedule: $DEFAULT_SCHEDULE"
            echo ""
            echo "  1) Use default schedule  ← default"
            echo "  2) Choose a different CSV file  (opens file picker)"
            echo ""
            read -rp "Choice [1-2, Enter for 1]: " sched_mode
            if [[ "$sched_mode" == "2" ]]; then
                echo "Opening file picker..."
                SCHEDULE="$(pick_csv "Select the preaching schedule CSV" "$(dirname "$DEFAULT_SCHEDULE")")"
                SCHEDULE="${SCHEDULE%$'\n'}"
            else
                SCHEDULE="$DEFAULT_SCHEDULE"
            fi
        else
            echo ""
            echo "Opening file picker (starting in schedules folder)..."
            if [[ -d "$SCHEDULES_DIR" ]]; then
                SCHEDULE="$(pick_csv "Select the preaching schedule CSV" "$SCHEDULES_DIR")"
            else
                SCHEDULE="$(pick_csv "Select the preaching schedule CSV")"
            fi
            SCHEDULE="${SCHEDULE%$'\n'}"
        fi
        if [[ -z "$SCHEDULE" || ! -f "$SCHEDULE" ]]; then
            echo "No schedule selected or file not found — falling back to manual speaker entry."
            select_speaker
            echo "→ Speaker: $SPEAKER"
        else
            echo "→ Schedule: $SCHEDULE"
        fi
    else
        select_speaker
        echo "→ Speaker: $SPEAKER"
    fi

    echo ""
    if [[ "$CONTENT_TYPE" == "talk" ]]; then
        read -rp "Talk title (leave blank if none): " TALK_TITLE
        echo ""
        select_event "talk"
    else
        select_event "sermon"
    fi
    echo "→ Event: $EVENT"
fi

# ── 6. Meeting-specific ───────────────────────────────────────────────────────
AGENDA=""
STYLE_FLAG="--style normal"

if [[ "$CONTENT_TYPE" == "meeting" ]]; then
    echo ""
    echo "Do you have an agenda document (.docx)?"
    read -rp "  Add agenda? [y/N]: " has_agenda
    if [[ "$has_agenda" =~ ^[Yy]$ ]]; then
        echo "Opening file picker (starting in input folder)..."
        # Derive the folder to start the picker in from the input path
        if [[ -f "$INPUT" ]]; then
            INPUT_DIR="$(dirname "$INPUT")"
        else
            INPUT_DIR="$INPUT"
        fi
        AGENDA="$(osascript -e "POSIX path of (choose file with prompt \"Select the agenda file (.docx, .txt, or .pdf)\" default location POSIX file \"${INPUT_DIR}\" of type {\"docx\", \"txt\", \"pdf\"})" 2>/dev/null || true)"
        AGENDA="${AGENDA%$'\n'}"
        if [[ -z "$AGENDA" || ! -f "$AGENDA" ]]; then
            echo "No agenda selected — continuing without one."
            AGENDA=""
        else
            echo "→ Agenda: $AGENDA"
        fi
    fi

    echo ""
    echo "How detailed should the minutes be?"
    echo "  1) Brief    — decisions and actions only"
    echo "  2) Standard — typical meeting minutes (default)"
    echo "  3) Detailed — full discussion and reasoning"
    echo ""
    read -rp "Enter 1, 2, or 3 (default 2): " style_choice
    case "$style_choice" in
        1) STYLE_FLAG="--style minimal" ;;
        3) STYLE_FLAG="--style verbose" ;;
        *) STYLE_FLAG="--style normal"  ;;
    esac
fi

# ── 7. Confirm ────────────────────────────────────────────────────────────────
echo ""
echo "------------------------------------------------"
echo "  Ready to run — here's what will happen:"
echo ""
echo "  Content type : $CONTENT_TYPE"
echo "  Input        : $INPUT"
if [[ -n "$OUTPUT" ]]; then
    echo "  Output folder: $OUTPUT"
else
    echo "  Output folder: same as input"
fi
[[ -n "$SPEAKER"        ]] && echo "  Speaker      : $SPEAKER"
[[ -n "$SCHEDULE"       ]] && echo "  Schedule     : $SCHEDULE"
[[ -n "$TALK_TITLE"     ]] && echo "  Title        : $TALK_TITLE"
[[ -n "$EVENT"          ]] && echo "  Event        : $EVENT"
[[ -n "$OVERWRITE_FLAG" ]] && echo "  Overwrite    : yes"
[[ -n "$AGENDA"         ]] && echo "  Agenda       : $AGENDA"
if [[ "$CONTENT_TYPE" == "meeting" ]]; then
    echo "  Minutes style: $STYLE_FLAG"
fi
echo "------------------------------------------------"
echo ""
read -rp "Press Enter to start, or type 'n' and Enter to cancel: " confirm
if [[ "$confirm" =~ ^[Nn]$ ]]; then
    echo "Cancelled."
    read -rp "Press Enter to close..." _
    exit 0
fi

# ── Run ───────────────────────────────────────────────────────────────────────
CMD=(python3 run_pipeline.py "$INPUT" --type "$CONTENT_TYPE" ${STYLE_FLAG})

[[ -n "$OUTPUT"         ]] && CMD+=(--output-dir "$OUTPUT")
[[ -n "$OVERWRITE_FLAG" ]] && CMD+=(--overwrite)
[[ -n "$SPEAKER"        ]] && CMD+=(--speaker "$SPEAKER")
[[ -n "$SCHEDULE"       ]] && CMD+=(--schedule "$SCHEDULE")
[[ -n "$EVENT"          ]] && CMD+=(--event "$EVENT")
[[ -n "$TALK_TITLE"     ]] && CMD+=(--title "$TALK_TITLE")
[[ -n "$AGENDA"         ]] && CMD+=(--agenda "$AGENDA")

echo ""
echo "Starting... (this may take a few minutes per file)"
echo ""

"${CMD[@]}"

echo ""
echo "================================================"
echo "  All done! Your documents have been saved."
echo "================================================"
echo ""
read -rp "Press Enter to close..." _
