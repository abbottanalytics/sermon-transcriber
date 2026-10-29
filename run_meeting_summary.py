#!/usr/bin/env python3

# -------------------------------------------------
# PURPOSE:
# CLI runner for meeting transcript processing.
#
# Handles:
# - file vs directory input
# - optional agenda ingestion (.docx)
# - minutes style selection
#
# NOTE:
# All heavy logic lives in meeting_summary.py
# This file is intentionally thin (orchestration only)
# the agenda if specified is applied to ALL files in the run
#
# USAGE: 
# BASIC: python3 run_meeting_summary.py meeting.txt
# With Agenda: python3 run_meeting_summary.py meeting.txt --agenda agenda.docx
# With Style control: python3 run_meeting_summary.py meeting.txt --agenda agenda.docx --style verbose
# Batch Directory: python3 run_meeting_summary.py ./transcripts --agenda agenda.docx
# -------------------------------------------------

import argparse
from pathlib import Path
from openai import OpenAI
import os

from meeting_summary import (
    process_meeting,
    read_agenda,
    normalize_agenda
)


def main():
    ap = argparse.ArgumentParser()

    ap.add_argument("paths", nargs="+", help="Transcript file(s) or directories")
    ap.add_argument("--overwrite", action="store_true", help="Overwrite existing outputs")

    # NEW
    ap.add_argument("--agenda", help="Path to agenda .docx file")
    ap.add_argument("--style", default="normal", choices=["minimal", "normal", "verbose"],
                    help="Minutes verbosity")

    args = ap.parse_args()

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # -------------------------
    # LOAD + NORMALIZE AGENDA
    # -------------------------
    agenda_structured = None

    if args.agenda:
        agenda_path = Path(args.agenda)

        if not agenda_path.exists():
            raise ValueError(f"Agenda file not found: {agenda_path}")

        print("Loading agenda...")
        raw_agenda = read_agenda(agenda_path)

        print("Normalizing agenda...")
        agenda_structured = normalize_agenda(client, raw_agenda)

    # -------------------------
    # PROCESS FILES
    # -------------------------
    for p in args.paths:
        path = Path(p)

        if path.is_file():
            process_meeting(
                client,
                path,
                args.overwrite,
                style=args.style,
                agenda_md=agenda_structured
            )

        else:
            for txt in path.rglob("*.txt"):
                process_meeting(
                    client,
                    txt,
                    args.overwrite,
                    style=args.style,
                    agenda_md=agenda_structured
                )


if __name__ == "__main__":
    main()

