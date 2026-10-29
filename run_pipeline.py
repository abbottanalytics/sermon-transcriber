#!/usr/bin/env python3
"""
Transcription + Processing Pipeline
====================================
Converts audio (mp3/m4a/wav), video (mp4/mov/m4v/mkv/webm) or existing transcripts (.txt) into
structured documents using Whisper (transcription) and GPT-4 (processing).

Supported content types:
  sermon  — cleaned transcript, outline, summary, scripture inference
  meeting — cleaned transcript, minutes, summary, action items, motions
  talk    — cleaned transcript, outline, summary (no scripture)
  class   — Higher Ed (adult Sunday School): cleaned transcript, class summary,
            lesson outline, discussion guide, podcast description
            (--speaker is the teacher; labeled Higher Ed unless --event says otherwise)

USAGE
-----
Single file:
  python3 run_pipeline.py sermon.mp3 --type sermon
  python3 run_pipeline.py meeting.txt --type meeting --agenda agenda.docx --style verbose
  python3 run_pipeline.py talk.mp3 --type talk
  python3 run_pipeline.py talk.mp4 --type talk      # video works too: Whisper reads its audio track

Batch directory (processes all .txt files inside):
  python3 run_pipeline.py ./sermons/ --type sermon
  python3 run_pipeline.py ./sermons/ ./more_sermons/ --type sermon

Options:
  --type        Required. One of: sermon, meeting, talk, class
  --agenda      Path to agenda .docx (meeting only)
  --style       Minutes verbosity: minimal, normal, verbose (meeting only, default: normal)
  --overwrite   Re-process files even if outputs already exist
  --skip-whisper  Skip Whisper; treat audio file as already transcribed

REQUIREMENTS
------------
  OPENAI_API_KEY must be set in your environment:
    export OPENAI_API_KEY='sk-...'

  Python packages: pyproject.toml (installed by install.sh / update.sh via uv)
  Whisper and ffmpeg are included; no separate install needed
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from openai import OpenAI

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav"}
# Whisper decodes the audio track of a video itself (via ffmpeg), so no separate extraction step.
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}
MEDIA_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS


DEFAULT_WHISPER_MODEL = "turbo"


def run_whisper(audio_path: Path, output_dir: Path, model: str = DEFAULT_WHISPER_MODEL):
    print(f"  Transcribing with Whisper ({model}): {audio_path.name}")
    output_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable, "-m", "whisper",
            str(audio_path),
            "--model", model,
            "--fp16", "False",
            "--output_format", "all",
            "--output_dir", str(output_dir),
        ],
        check=True,
    )


def resolve_transcript(input_path: Path, skip_whisper: bool, output_dir: Path,
                       whisper_model: str = DEFAULT_WHISPER_MODEL) -> Path:
    if input_path.name.startswith("._"):
        raise ValueError(f"Skipping macOS metadata file: {input_path.name}")
    if input_path.suffix.lower() in MEDIA_EXTENSIONS and not skip_whisper:
        run_whisper(input_path, output_dir, whisper_model)
        txt_path = output_dir / (input_path.stem + ".txt")
    elif input_path.suffix == ".txt":
        txt_path = input_path
    else:
        # Earlier Whisper output: in the output folder, or beside the recording
        candidates = [output_dir / (input_path.stem + ".txt"), input_path.with_suffix(".txt")]
        txt_path = next((c for c in candidates if c.exists()), candidates[0])

    if not txt_path.exists():
        raise FileNotFoundError(f"Transcript not found: {txt_path}")

    return txt_path


def collect_inputs(paths: list[str], content_type: str) -> list[Path]:
    """Expand paths: files are used directly; directories are searched for audio, video and .txt files."""
    results = []
    for p in paths:
        path = Path(p).expanduser().resolve()
        if path.is_file():
            results.append(path)
        elif path.is_dir():
            found = []
            for f in sorted(path.rglob("*")):
                if not f.is_file():
                    continue
                if f.name.startswith("._"):  # macOS resource-fork companion files
                    continue
                name = f.name.lower()
                if f.suffix.lower() in AUDIO_EXTENSIONS:
                    found.append(f)
                elif f.suffix.lower() in VIDEO_EXTENSIONS:
                    # A video and an audio file with the same name are the same recording
                    # (and would write the same output names): use the audio.
                    if not any((f.parent / (f.stem + ext)).exists() for ext in AUDIO_EXTENSIONS):
                        found.append(f)
                elif name.endswith(".txt"):
                    # Skip our own generated outputs
                    if any(name.endswith(s) for s in [".scripture.txt", ".motions_and_actions.txt"]):
                        continue
                    # Skip if an audio/video file with the same stem exists (handled via that file)
                    has_audio = any(
                        (f.parent / (f.stem + ext)).exists()
                        for ext in MEDIA_EXTENSIONS
                    )
                    if not has_audio:
                        found.append(f)
            results.extend(found)
        else:
            print(f"WARNING: path not found, skipping: {path}", file=sys.stderr)
    return results


def process_file(client, input_path: Path, content_type: str, overwrite: bool,
                 skip_whisper: bool, style: str, agenda_md: str | None,
                 output_dir: Path | None, speaker: str | None,
                 event: str | None, title: str | None,
                 schedule: dict | None = None,
                 whisper_model: str = DEFAULT_WHISPER_MODEL,
                 scripture: str | None = None):
    # Determine where outputs will land so we can check before running Whisper
    stem = input_path.stem

    # Auto-fill speaker from schedule if not provided on the command line
    if not speaker and schedule:
        from schedule_lookup import get_speaker_for_stem
        looked_up = get_speaker_for_stem(stem, schedule)
        if looked_up:
            speaker = looked_up
            print(f"  Schedule: speaker = {speaker}")
        else:
            print(f"  Schedule: no entry found for {stem} — speaker unknown")
    effective_out_dir = output_dir if output_dir else input_path.parent
    sentinel = effective_out_dir / (stem + ".cleaned.docx")

    if not overwrite and sentinel.exists():
        print(f"\nSKIP (already processed): {input_path.name}")
        return

    # Resolve output directory — Whisper files go here too
    effective_out_dir = output_dir if output_dir else input_path.parent
    effective_out_dir.mkdir(parents=True, exist_ok=True)

    if input_path.suffix.lower() in MEDIA_EXTENSIONS:
        txt_path = resolve_transcript(input_path, skip_whisper, effective_out_dir, whisper_model)
    else:
        txt_path = input_path

    print(f"\nPROCESSING [{content_type}]: {txt_path.name}")

    out_base = effective_out_dir / txt_path.stem

    if content_type == "sermon":
        from sermon_summary import process_sermon
        process_sermon(client, txt_path, overwrite, out_base=out_base,
                       speaker=speaker, event=event, title=title, scripture=scripture)

    elif content_type == "talk":
        from talk_summary import process_talk
        process_talk(client, txt_path, overwrite, out_base=out_base,
                     speaker=speaker, event=event, title=title)

    elif content_type == "class":
        from class_summary import process_class
        process_class(client, txt_path, overwrite, out_base=out_base,
                      teacher=speaker, event=event, title=title, scripture=scripture)

    elif content_type == "meeting":
        from meeting_summary import process_meeting
        process_meeting(client, txt_path, overwrite, style=style, agenda_md=agenda_md,
                        out_base=out_base)


def main():
    ap = argparse.ArgumentParser(
        description="Transcribe and process audio/transcripts into structured documents.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("paths", nargs="+", help="Audio file(s), transcript file(s), or directories")
    ap.add_argument("--type", required=True, choices=["sermon", "meeting", "talk", "class"],
                    help="Content type — controls what outputs are generated")
    ap.add_argument("--agenda", help="Agenda .docx file (meeting only)")
    ap.add_argument("--style", default="normal", choices=["minimal", "normal", "verbose"],
                    help="Minutes verbosity (meeting only)")
    ap.add_argument("--output-dir", help="Directory for output files (default: same folder as input)")
    ap.add_argument("--speaker", help="Speaker name with title (e.g. 'Pastor Joel Wood')")
    ap.add_argument("--schedule", help="Path to preaching schedule CSV for automatic speaker lookup")
    ap.add_argument("--event", help="Service or event name (e.g. 'Morning Worship')")
    ap.add_argument("--title", help="Talk or sermon title, or a class's topic")
    ap.add_argument("--scripture", help="Scripture passage (sermon or class), e.g. 'Joshua 1'")
    ap.add_argument("--overwrite", action="store_true", help="Overwrite existing output files")
    ap.add_argument("--skip-whisper", action="store_true",
                    help="Skip Whisper even for audio files (assumes .txt already exists)")
    args = ap.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY is not set.", file=sys.stderr)
        print("  export OPENAI_API_KEY='sk-...'", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # Load agenda once if provided (meeting only)
    agenda_md = None
    if args.agenda:
        if args.type != "meeting":
            print("WARNING: --agenda is only used for meeting processing; ignoring.", file=sys.stderr)
        else:
            from meeting_summary import read_agenda, normalize_agenda
            agenda_path = Path(args.agenda)
            if not agenda_path.exists():
                print(f"ERROR: Agenda file not found: {agenda_path}", file=sys.stderr)
                sys.exit(1)
            print("Loading and normalizing agenda...")
            agenda_md = normalize_agenda(client, read_agenda(agenda_path))

    # Load preaching schedule if provided
    schedule = None
    if args.schedule:
        from schedule_lookup import load_schedule
        schedule_path = Path(args.schedule).expanduser().resolve()
        if not schedule_path.exists():
            print(f"ERROR: Schedule file not found: {schedule_path}", file=sys.stderr)
            sys.exit(1)
        schedule = load_schedule(schedule_path)
        print(f"Loaded schedule: {len(schedule)} entries from {schedule_path.name}")

    # Collect all input files
    inputs = collect_inputs(args.paths, args.type)
    if not inputs:
        print("No input files found.", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else None

    for input_path in inputs:
        process_file(
            client,
            input_path,
            content_type=args.type,
            overwrite=args.overwrite,
            skip_whisper=args.skip_whisper,
            style=args.style,
            agenda_md=agenda_md,
            output_dir=output_dir,
            speaker=args.speaker or None,
            event=args.event or None,
            title=args.title or None,
            schedule=schedule,
            scripture=args.scripture or None,
        )

    print("\nDONE.")


if __name__ == "__main__":
    main()
