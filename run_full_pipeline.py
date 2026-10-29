#!/usr/bin/env python3

# -------------------------------------------------
# PURPOSE:
# End-to-end pipeline:
# audio → (optional Whisper) → transcript → outputs
#
# This is the MAIN entrypoint.
#
# DESIGN:
# - Whisper step optional
# - Agenda optional
# - Delegates processing to meeting_summary
#
# processing flow:
# run_full_pipeline.py → orchestration
# meeting_summary.py → intelligence
# core.py → utilities
#
# NOTE: this assumes whisper names outputs with .txt in current path
#     txt_path = input_path.with_suffix(".txt")
# may want to allow for this
#     txt_path = input_path.parent / (input_path.stem + ".txt")
#
# USAGE:
#    full pipeline: python3 run_full_pipeline.py meeting.mp3 --agenda agenda.docx
#    skip whisper: python3 run_full_pipeline.py meeting.txt --agenda agenda.docx
#    with style: python3 run_full_pipeline.py meeting.mp3 --agenda agenda.docx --style verbose
#    
# -------------------------------------------------

import argparse
import subprocess
from pathlib import Path
from openai import OpenAI
import os, sys

from meeting_summary import (
    process_meeting,
    normalize_agenda,
    read_agenda,
)

print("PYTHON:", sys.executable)


def run_whisper(audio_path):
    subprocess.run([
        sys.executable, "-m", "whisper",
        str(audio_path),
        "--model", "turbo",
        "--fp16", "False",
        "--output_format", "all"
    ], check=True)


def main():
    ap = argparse.ArgumentParser()

    ap.add_argument("input", help="Audio or video file OR transcript (.txt)")
    ap.add_argument("--agenda", help="Path to agenda .docx")
    ap.add_argument("--style", default="normal", choices=["minimal", "normal", "verbose"])
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--skip-transcription", action="store_true")

    args = ap.parse_args()

    input_path = Path(args.input)

    # ------------------------
    # STEP 1: TRANSCRIPTION
    # ------------------------
    # Whisper reads the audio track of a video file directly, so video is accepted too.
    if input_path.suffix.lower() in [".mp3", ".m4a", ".wav", ".mp4", ".mov", ".m4v", ".mkv", ".webm"] and not args.skip_transcription:
        print("Running Whisper...")
        run_whisper(input_path)
        txt_path = input_path.with_suffix(".txt")
    else:
        txt_path = input_path

    if not txt_path.exists():
        raise ValueError(f"Transcript not found: {txt_path}")

#    client = OpenAI()
#    client = OpenAI(
#        api_key=os.getenv("OPENAI_API_KEY"),
#        # force correct project context
#        default_headers={
#            "OpenAI-Project": "proj_q7GPB1fPSEMtqkhqd6kZKSFs"
#        }
#    )
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # ------------------------
    # STEP 2: LOAD + NORMALIZE AGENDA
    # ------------------------
    agenda_structured = None

    if args.agenda:
        agenda_path = Path(args.agenda)

        if not agenda_path.exists():
            raise ValueError(f"Agenda file not found: {agenda_path}")

        print("Loading agenda...")
        raw_agenda = read_agenda(agenda_path)

        print("Normalizing agenda...")
        agenda_structured = normalize_agenda(client, raw_agenda)

    # ------------------------
    # STEP 3: PROCESS
    # ------------------------
    print("Processing meeting...")

    process_meeting(
        client,
        txt_path,
        args.overwrite,
        style=args.style,
        agenda_md=agenda_structured
    )

    print("\nDONE.")


if __name__ == "__main__":
    main()
