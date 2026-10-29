#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Interactive runner for the transcription + summarization pipeline.
# Prompts for all inputs, then calls run_pipeline.py.
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load shared helpers (speaker list, event list, config)
# shellcheck source=pipeline_helpers.sh
source "$SCRIPT_DIR/pipeline_helpers.sh"

# ── Pre-flight checks ─────────────────────────────────────────────────────────
if [[ -z "${OPENAI_API_KEY:-}" ]]; then
    echo "ERROR: OpenAI API key not found."
    echo "  Add your key to $CONFIG_FILE:  api_key=sk-..."
    echo "  Or set it in your shell:     export OPENAI_API_KEY='sk-...'"
    exit 1
fi

# ── Load config defaults ──────────────────────────────────────────────────────
read_config

echo ""
echo "================================================"
echo "  Transcription & Summarization Pipeline"
echo "================================================"
echo ""

# ── 1. Content type ─────────────────────────────────────────────────────────
echo "What type of content are you processing?"
echo ""

# Build menu dynamically from enabled types
TYPE_OPTIONS=()
TYPE_LABELS=()
[[ "$ENABLE_SERMONS"  == "true" ]] && TYPE_OPTIONS+=("sermon")  && TYPE_LABELS+=("Sermon")
[[ "$ENABLE_CLASSES"  == "true" ]] && TYPE_OPTIONS+=("class")   && TYPE_LABELS+=("Higher Ed class (adult Sunday School)")
[[ "$ENABLE_TALKS"    == "true" ]] && TYPE_OPTIONS+=("talk")    && TYPE_LABELS+=("Talk / Conference presentation")
[[ "$ENABLE_MEETINGS" == "true" ]] && TYPE_OPTIONS+=("meeting") && TYPE_LABELS+=("Meeting")

if [[ ${#TYPE_OPTIONS[@]} -eq 0 ]]; then
    echo "ERROR: No content types are enabled in config.txt."
    echo "  Set at least one of enable_sermons, enable_classes, enable_talks, enable_meetings to true."
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
        echo "Invalid choice. Exiting."
        exit 1
    fi
    echo "→ Type: $CONTENT_TYPE"
fi
echo ""

# ── 2. Input ─────────────────────────────────────────────────────────────────
echo "Input: enter a single file path (audio: mp3, m4a, wav; video: mp4, mov, m4v, mkv, webm; or txt)"
echo "       OR a directory path to batch-process all audio/transcripts inside."
echo "(Tip: drag a file or folder from Finder into this window)"
if [[ -n "$DEFAULT_INPUT" ]]; then
    echo "(Default: $DEFAULT_INPUT)"
fi
echo ""
read -rp "Input path [Enter for default]: " INPUT_RAW
INPUT="${INPUT_RAW/#\~/$HOME}"

# Use default if blank
if [[ -z "$INPUT" && -n "$DEFAULT_INPUT" ]]; then
    INPUT="$DEFAULT_INPUT"
fi

if [[ ! -e "$INPUT" ]]; then
    echo "ERROR: path not found: $INPUT"
    exit 1
fi

# ── 3. Output directory ──────────────────────────────────────────────────────
echo ""
echo "Where should the output documents be saved?"
echo ""

OUTPUT=""
if [[ -n "$DEFAULT_OUTPUT" ]]; then
    echo "  1) $DEFAULT_OUTPUT  (from config.txt)  ← default"
    echo "  2) Same folder as the input files"
    echo "  3) Enter a different path"
    echo ""
    read -rp "Choice [1-3, Enter for default]: " output_choice
    case "$output_choice" in
        ""|1) OUTPUT="$DEFAULT_OUTPUT" ;;
        2)    OUTPUT="" ;;
        3)    read -rp "Output path: " OUTPUT_RAW
              OUTPUT="${OUTPUT_RAW/#\~/$HOME}" ;;
        *)    OUTPUT="$DEFAULT_OUTPUT" ;;
    esac
else
    echo "  1) Same folder as the input files  ← default"
    echo "  2) Enter a different path"
    echo ""
    read -rp "Choice [1-2, Enter for default]: " output_choice
    case "$output_choice" in
        2)  read -rp "Output path: " OUTPUT_RAW
            OUTPUT="${OUTPUT_RAW/#\~/$HOME}" ;;
        *)  OUTPUT="" ;;
    esac
fi

if [[ -n "$OUTPUT" ]]; then
    PARENT="$(dirname "$OUTPUT")"
    if [[ ! -d "$PARENT" ]]; then
        echo "ERROR: parent directory does not exist: $PARENT"
        echo "  Please create it first or choose a different output path."
        exit 1
    fi
fi

# ── 4. Overwrite? ────────────────────────────────────────────────────────────
echo ""
read -rp "Overwrite existing output files? [y/N]: " overwrite_choice
OVERWRITE_FLAG=""
[[ "$overwrite_choice" =~ ^[Yy]$ ]] && OVERWRITE_FLAG="--overwrite"

# ── 5. Speaker (sermon + talk only) ──────────────────────────────────────────
SPEAKER=""
SCHEDULE=""
EVENT=""
TALK_TITLE=""
SCRIPTURE=""
AGENDA_RAW=""
AGENDA=""
STYLE_FLAG="--style normal"

if [[ "$CONTENT_TYPE" == "sermon" || "$CONTENT_TYPE" == "talk" ]]; then
    echo ""
    echo "How should the speaker be identified?"
    echo "  1) Select or enter speaker manually  ← default"
    echo "  2) Use preaching schedule  (auto-assign from filename dates)"
    echo ""
    read -rp "Choice [1-2, Enter for 1]: " speaker_mode

    if [[ "$speaker_mode" == "2" ]]; then
        if [[ -n "${DEFAULT_SCHEDULE:-}" ]]; then
            echo "  Default: $DEFAULT_SCHEDULE  (from config.txt)"
        elif [[ -d "$SCHEDULES_DIR" ]]; then
            echo "  (Schedules folder: $SCHEDULES_DIR)"
        fi
        echo ""
        read -rp "Schedule CSV path [Enter for default]: " SCHED_RAW
        SCHED_RAW="${SCHED_RAW/#\~/$HOME}"
        if [[ -z "$SCHED_RAW" && -n "${DEFAULT_SCHEDULE:-}" ]]; then
            SCHEDULE="$DEFAULT_SCHEDULE"
        else
            SCHEDULE="$SCHED_RAW"
        fi
        if [[ ! -f "$SCHEDULE" ]]; then
            echo "ERROR: schedule file not found: $SCHEDULE"
            exit 1
        fi
        echo "→ Schedule: $SCHEDULE"
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

# ── 5b. Higher Ed class ──────────────────────────────────────────────────────
# Class documents never name class members; the teacher is named only if given.
if [[ "$CONTENT_TYPE" == "class" ]]; then
    echo ""
    if [[ -n "$DEFAULT_HE_TEACHER" ]]; then
        read -rp "Teacher, with title [Enter for $DEFAULT_HE_TEACHER]: " SPEAKER
        SPEAKER="${SPEAKER:-$DEFAULT_HE_TEACHER}"
    else
        read -rp "Teacher, with title (e.g. Elder John Smith; blank if unsure): " SPEAKER
    fi
    read -rp "Class topic or series (optional): " TALK_TITLE
    read -rp "Passage studied (optional, e.g. Joshua 1): " SCRIPTURE
    EVENT="Higher Ed (Adult Sunday School)"
    echo "→ Event: $EVENT"
fi

# ── 6. Meeting-specific options ───────────────────────────────────────────────
if [[ "$CONTENT_TYPE" == "meeting" ]]; then
    echo ""
    # Show the input directory as a hint — agenda is usually in the same folder
    if [[ -f "$INPUT" ]]; then
        INPUT_DIR="$(dirname "$INPUT")"
    else
        INPUT_DIR="$INPUT"
    fi
    echo "Agenda file — .docx, .txt, or .pdf (optional — leave blank to skip):"
    echo "(Tip: agenda is usually in the same folder as the recording: $INPUT_DIR)"
    read -rp "Agenda path: " AGENDA_RAW
    AGENDA="${AGENDA_RAW/#\~/$HOME}"
    if [[ -n "$AGENDA" ]]; then
        if [[ ! -f "$AGENDA" ]]; then
            echo "ERROR: agenda file not found: $AGENDA"
            exit 1
        fi
    fi

    echo ""
    echo "Minutes verbosity:"
    echo "  1) Minimal  — bullet points, decisions and actions only"
    echo "  2) Normal   — standard minutes with brief summaries (default)"
    echo "  3) Verbose  — detailed, includes discussion flow and reasoning"
    echo ""
    read -rp "Enter choice [1-3, default 2]: " style_choice
    case "$style_choice" in
        1) STYLE_FLAG="--style minimal" ;;
        3) STYLE_FLAG="--style verbose" ;;
        *) STYLE_FLAG="--style normal" ;;
    esac
fi

# ── 7. Confirm and run ────────────────────────────────────────────────────────
echo ""
echo "------------------------------------------------"
echo "  Ready to run"
echo "  Type:    $CONTENT_TYPE"
echo "  Input:   $INPUT"
if [[ -n "$OUTPUT" ]]; then
    echo "  Output:  $OUTPUT"
else
    echo "  Output:  (same folder as input)"
fi
if [[ "$CONTENT_TYPE" == "class" ]]; then
    [[ -n "$SPEAKER"    ]] && echo "  Teacher: $SPEAKER"
    [[ -n "$TALK_TITLE" ]] && echo "  Topic:   $TALK_TITLE"
    [[ -n "$SCRIPTURE"  ]] && echo "  Passage: $SCRIPTURE"
else
    [[ -n "$SPEAKER"    ]] && echo "  Speaker: $SPEAKER"
    [[ -n "$TALK_TITLE" ]] && echo "  Title:   $TALK_TITLE"
fi
[[ -n "$SCHEDULE"   ]] && echo "  Schedule: $SCHEDULE"
[[ -n "$EVENT"      ]] && echo "  Event:   $EVENT"
[[ -n "$OVERWRITE_FLAG" ]] && echo "  Overwrite: yes"
[[ -n "$AGENDA"     ]] && echo "  Agenda:  $AGENDA"
if [[ "$CONTENT_TYPE" == "meeting" ]]; then
    echo "  Style:   $STYLE_FLAG"
fi
echo "------------------------------------------------"
echo ""
read -rp "Proceed? [Y/n]: " confirm
if [[ "$confirm" =~ ^[Nn]$ ]]; then
    echo "Cancelled."
    exit 0
fi

# ── Build and run the command ─────────────────────────────────────────────────
CMD=(python3 "$SCRIPT_DIR/run_pipeline.py" "$INPUT" --type "$CONTENT_TYPE" ${STYLE_FLAG})

[[ -n "$OUTPUT"         ]] && CMD+=(--output-dir "$OUTPUT")
[[ -n "$OVERWRITE_FLAG" ]] && CMD+=(--overwrite)
[[ -n "$SPEAKER"        ]] && CMD+=(--speaker "$SPEAKER")
[[ -n "$SCHEDULE"       ]] && CMD+=(--schedule "$SCHEDULE")
[[ -n "$EVENT"          ]] && CMD+=(--event "$EVENT")
[[ -n "$TALK_TITLE"     ]] && CMD+=(--title "$TALK_TITLE")
[[ -n "$SCRIPTURE"      ]] && CMD+=(--scripture "$SCRIPTURE")
[[ -n "$AGENDA"         ]] && CMD+=(--agenda "$AGENDA")

echo ""
echo "Running: ${CMD[*]}"
echo ""

"${CMD[@]}"
