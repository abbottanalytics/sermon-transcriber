#!/usr/bin/env python3
"""
Per-sermon preaching analysis runner.

Reads an existing transcript (.txt or .cleaned.docx) and runs four
analysis tasks: component segmentation, application authenticity,
congregation critique, and application theme extraction.

Writes:
  <stem>.preaching_analysis.json   — structured data for corpus analysis
  <stem>.preaching_analysis.docx   — human-readable report

USAGE
-----
Single file:
  python3 run_sermon_analysis.py sermon.txt --speaker "Pastor Joel E. Wood"
  python3 run_sermon_analysis.py sermon.cleaned.docx

Batch directory:
  python3 run_sermon_analysis.py ./transcripts/ --speaker "Pastor Joel E. Wood"

Options:
  --speaker     Speaker name (reads from .cleaned.docx header if omitted)
  --event       Event name
  --date        Date string (e.g. "2025-10-18")
  --scripture   Scripture passage hint (reads from .scripture.docx if omitted)
  --output-dir  Where to write output files (default: same folder as input)
  --overwrite   Re-analyze files that already have output
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

from openai import OpenAI

from transcription_summary_core import read_text, write_docx
from sermon_analysis import analyze_sermon, build_report_markdown


def _read_docx_text(path: Path) -> str:
    """Extract plain text from a .docx using python-docx."""
    try:
        from docx import Document
        doc = Document(path)
        return "\n".join(p.text for p in doc.paragraphs)
    except Exception as e:
        print(f"  WARNING: could not read {path.name}: {e}")
        return ""


def _extract_metadata_from_cleaned(docx_path: Path) -> dict:
    """
    Read **Speaker:** / **Event:** header lines from a .cleaned.docx.
    Returns dict with keys speaker, event (values may be None).
    """
    meta = {"speaker": None, "event": None}
    if not docx_path.exists():
        return meta
    text = _read_docx_text(docx_path)
    for line in text.splitlines():
        m = re.match(r"\*?\*?Speaker:\*?\*?\s*(.+)", line)
        if m:
            meta["speaker"] = m.group(1).strip()
        m = re.match(r"\*?\*?Event:\*?\*?\s*(.+)", line)
        if m:
            meta["event"] = m.group(1).strip()
    return meta


def _read_scripture_hint(scripture_path: Path) -> str | None:
    """Read the first non-empty line from a .scripture.docx as the scripture hint."""
    if not scripture_path.exists():
        return None
    text = _read_docx_text(scripture_path)
    for line in text.splitlines():
        stripped = line.strip()
        # Skip metadata header lines
        if stripped and not stripped.startswith("**") and not stripped.startswith("---"):
            return stripped[:200]
    return None


def _try_parse_date_from_stem(stem: str) -> str | None:
    """
    Try to parse a date from filename stems like:
      101826AM  → 2026-10-18
      20251012  → 2025-10-12
    """
    # MMDDYY pattern (e.g. 101826AM)
    m = re.match(r"^(\d{2})(\d{2})(\d{2})", stem)
    if m:
        month, day, year = m.groups()
        return f"20{year}-{month}-{day}"
    # YYYYMMDD pattern
    m = re.match(r"^(\d{4})(\d{2})(\d{2})", stem)
    if m:
        year, month, day = m.groups()
        return f"{year}-{month}-{day}"
    return None


def resolve_transcript(input_path: Path) -> str:
    """Return transcript text from .txt or .cleaned.docx."""
    if input_path.suffix.lower() == ".docx":
        return _read_docx_text(input_path)
    return read_text(input_path)


def collect_inputs(paths: list[str]) -> list[Path]:
    """Expand paths to a flat list of transcript files to analyze."""
    results = []
    for p in paths:
        path = Path(p).expanduser().resolve()
        if path.is_file():
            results.append(path)
        elif path.is_dir():
            # Prefer .cleaned.docx; fall back to .txt (skip generated outputs)
            seen_stems = set()
            for f in sorted(path.rglob("*.cleaned.docx")):
                if f.name.startswith("._"):
                    continue
                results.append(f)
                seen_stems.add(f.stem.replace(".cleaned", ""))
            for f in sorted(path.rglob("*.txt")):
                if f.name.startswith("._"):
                    continue
                stem = f.stem
                # Skip our own generated outputs
                if any(stem.endswith(s) for s in [
                    ".scripture", ".podcast", ".motions_and_actions",
                    ".preaching_analysis"
                ]):
                    continue
                if stem in seen_stems:
                    continue
                results.append(f)
                seen_stems.add(stem)
        else:
            print(f"WARNING: path not found, skipping: {path}", file=sys.stderr)
    return results


def process_file(
    client,
    input_path: Path,
    overwrite: bool,
    cli_speaker: str | None,
    cli_event: str | None,
    cli_date: str | None,
    cli_scripture: str | None,
    output_dir: Path | None,
):
    # Determine stem and output locations
    if input_path.name.endswith(".cleaned.docx"):
        stem = input_path.name.replace(".cleaned.docx", "")
    else:
        stem = input_path.stem

    base_dir = output_dir if output_dir else input_path.parent
    json_out  = base_dir / f"{stem}.preaching_analysis.json"
    docx_out  = base_dir / f"{stem}.preaching_analysis.docx"

    if not overwrite and json_out.exists():
        print(f"\nSKIP (already analyzed): {input_path.name}")
        return

    print(f"\nANALYZING: {input_path.name}")

    # ── Gather metadata ──────────────────────────────────────────────────────
    # Prefer CLI args; fall back to reading from sibling files
    sibling_dir = input_path.parent

    cleaned_path   = sibling_dir / f"{stem}.cleaned.docx"
    scripture_path = sibling_dir / f"{stem}.scripture.docx"
    srt_path       = sibling_dir / f"{stem}.srt"

    auto_meta = _extract_metadata_from_cleaned(cleaned_path)

    speaker   = cli_speaker   or auto_meta.get("speaker")
    event     = cli_event     or auto_meta.get("event")
    date      = cli_date      or _try_parse_date_from_stem(stem)
    scripture = cli_scripture or _read_scripture_hint(scripture_path)

    metadata = {
        k: v for k, v in {
            "speaker": speaker,
            "event":   event,
            "date":    date,
            "stem":    stem,
        }.items() if v
    }

    # ── Read transcript ──────────────────────────────────────────────────────
    transcript = resolve_transcript(input_path)
    if not transcript.strip():
        print(f"  ERROR: empty transcript — skipping.")
        return

    # ── Run analysis ─────────────────────────────────────────────────────────
    analysis = analyze_sermon(
        client,
        transcript,
        srt_path=srt_path if srt_path.exists() else None,
        scripture_hint=scripture,
        metadata=metadata,
    )

    # ── Write JSON ───────────────────────────────────────────────────────────
    base_dir.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(analysis, indent=2), encoding="utf-8")
    print(f"  WROTE: {json_out.name}")

    # ── Write docx ───────────────────────────────────────────────────────────
    report_md = build_report_markdown(analysis)
    write_docx(docx_out, report_md, overwrite=True)


def main():
    ap = argparse.ArgumentParser(
        description="Run preaching analysis on sermon transcript(s).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("paths", nargs="+", help="Transcript file(s) or directories")
    ap.add_argument("--speaker",    help="Speaker name (auto-read from .cleaned.docx if omitted)")
    ap.add_argument("--event",      help="Event name")
    ap.add_argument("--date",       help="Date string e.g. 2025-10-18 (auto-parsed from filename if omitted)")
    ap.add_argument("--scripture",  help="Scripture passage hint (auto-read from .scripture.docx if omitted)")
    ap.add_argument("--output-dir", help="Write output files here (default: same folder as input)")
    ap.add_argument("--overwrite",  action="store_true", help="Re-analyze even if output exists")
    args = ap.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY is not set.", file=sys.stderr)
        sys.exit(1)

    client     = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    inputs     = collect_inputs(args.paths)
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else None

    if not inputs:
        print("No transcript files found.", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(inputs)} transcript(s) to analyze.")

    for input_path in inputs:
        process_file(
            client,
            input_path,
            overwrite=args.overwrite,
            cli_speaker=args.speaker,
            cli_event=args.event,
            cli_date=args.date,
            cli_scripture=args.scripture,
            output_dir=output_dir,
        )

    print("\nDONE.")


if __name__ == "__main__":
    main()
