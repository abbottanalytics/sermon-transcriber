#!/usr/bin/env python3
"""
Copy finished sermon documents into a shared Google Drive folder.

This doesn't talk to Google itself: Google Drive for Desktop, signed in as the
AV account, keeps a folder on this Mac in sync with Drive. publish_dir names a
folder inside it, and this module copies the finished documents there, one
folder per recording:

    <publish_dir>/Sermons/2026/2026-11-01 AM - Praising God's Justice (Derek Rishmawy)/
        2026-11-01 AM Summary.docx
        2026-11-01 AM Outline.docx
        2026-11-01 AM Scripture.docx
        2026-11-01 AM Transcript.docx
        2026-11-01 AM Podcast description.txt
    <publish_dir>/Higher Ed/2026/2026-11-01 Higher Ed - Romans (Elder Smith)/   (if publish_classes=true)
        2026-11-01 Higher Ed Summary.docx
        2026-11-01 Higher Ed Outline.docx
        2026-11-01 Higher Ed Discussion guide.docx

Rules:
  - A sermon is published only when it's done and nothing needs review, so a
    guessed or missing speaker never reaches Drive. Fixing it in Sermon Helper
    publishes it.
  - Redoing a recording replaces its published copy; if the title or speaker
    changed, the old folder is removed (Drive keeps it in its trash).
  - If the Drive folder isn't there (Drive for Desktop not running, signed out,
    offline at startup), the recording stays marked publish_pending in
    processed.json and is published on a later run.

Settings (config.txt):
    publish_dir       Folder inside Google Drive to publish to (blank: don't publish)
    publish_classes   true to publish Higher Ed class documents too (default false)
    publish_class_transcripts
                      true to include a class's full transcript as well (default
                      false: unlike the summaries, it has everything members said)
    publish_captions  true to add .srt/.vtt caption files (default false; for a
                      class, only with publish_class_transcripts)

USAGE:
    python3 drive_publish.py check      # is publishing set up and working?
    python3 drive_publish.py backfill   # publish everything already finished
"""

import argparse
import filecmp
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

from recording_names import parse_recording_name

SERMON_FILES = [                    # (output suffix, published name)
    (".summary.docx", "Summary.docx"),
    (".outline.docx", "Outline.docx"),
    (".scripture.docx", "Scripture.docx"),
    (".cleaned.docx", "Transcript.docx"),
    (".podcast.txt", "Podcast description.txt"),
]
CLASS_FILES = [
    (".summary.docx", "Summary.docx"),
    (".outline.docx", "Outline.docx"),
    (".discussion.docx", "Discussion guide.docx"),
]
CLASS_TRANSCRIPT = [(".cleaned.docx", "Transcript.docx")]
CAPTION_FILES = [(".srt", "Captions.srt"), (".vtt", "Captions.vtt")]
MAX_FOLDER_NAME = 120


class PublishError(Exception):
    pass


def _true(value) -> bool:
    return str(value or "").strip().lower() in ("true", "yes", "1")


def publish_root(config: dict) -> Path | None:
    value = config.get("publish_dir", "").strip()
    return Path(value).expanduser() if value else None


def _safe(name: str) -> str:
    """A folder or file name Drive and Finder both accept."""
    name = re.sub(r'[/:\\\n\r\t]+', "-", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if len(name) > MAX_FOLDER_NAME:
        name = name[:MAX_FOLDER_NAME].rstrip(" .-") + "…"
    return name


# ── What gets published, and where ───────────────────────────────────────────

def eligible(entry: dict, config: dict, kind: str) -> bool:
    if kind == "class":
        return entry.get("status") == "done" and _true(config.get("publish_classes"))
    return entry.get("status") == "done" and not entry.get("needs_review")


def destination(audio: Path, entry: dict, root: Path) -> tuple[Path, str, str]:
    """(folder, file-name prefix, kind) for a recording."""
    rec = parse_recording_name(audio.stem)
    if rec:
        day = f"{rec.date:%Y-%m-%d}"
        year = str(rec.date.year)
        kind = rec.kind
        label = f"{day} {rec.service}" if kind == "sermon" else f"{day} Higher Ed"
    else:                       # an unusual name, done by hand in Sermon Helper
        year = Path(entry.get("output_dir", "")).name
        year = year if year.isdigit() else entry.get("updated", "")[:4]
        kind, label = "sermon", audio.stem

    title, speaker = entry.get("title"), entry.get("speaker")
    folder = label + (f" - {title}" if title and title != label else "")
    folder += f" ({speaker})" if speaker else ""
    section = "Higher Ed" if kind == "class" else "Sermons"
    return root / section / year / _safe(folder), label, kind


def files_for(kind: str, config: dict) -> list[tuple[str, str]]:
    if kind == "class":
        if not _true(config.get("publish_class_transcripts")):
            return CLASS_FILES
        files = CLASS_FILES + CLASS_TRANSCRIPT
    else:
        files = SERMON_FILES
    return files + (CAPTION_FILES if _true(config.get("publish_captions")) else [])


# ── Publishing ────────────────────────────────────────────────────────────────

def _remove_old(old_dir: Path, names: list[str]):
    """Remove only the files this module put there, then the folder if empty —
    anything a person added in Drive is left alone."""
    for name in names:
        (old_dir / name).unlink(missing_ok=True)
    try:
        old_dir.rmdir()
    except OSError:
        pass


def _remove_old_extra(folder: Path, old_names: list[str], names: list[str]):
    for name in set(old_names) - set(names):
        (folder / name).unlink(missing_ok=True)


def publish_files(audio: Path, entry: dict, config: dict) -> tuple[Path, list[str]] | None:
    """Copy one recording's documents. Returns (folder, file names), or None if
    it isn't eligible. Raises PublishError if it should be retried later."""
    root = publish_root(config)
    if root is None:
        return None
    folder, prefix, kind = destination(audio, entry, root)
    if not eligible(entry, config, kind):
        return None
    if not root.is_dir():
        raise PublishError(f"Google Drive folder not found: {root} "
                           f"(is Google Drive for Desktop running and signed in?)")

    out_dir = Path(entry.get("output_dir", ""))
    wanted = [(out_dir / f"{audio.stem}{suffix}", f"{prefix} {name}")
              for suffix, name in files_for(kind, config)]
    wanted = [(src, name) for src, name in wanted if src.exists()]
    if not wanted:
        raise PublishError(f"No finished documents found in {out_dir}")

    try:
        folder.mkdir(parents=True, exist_ok=True)
        for src, name in wanted:
            dest = folder / name
            # Unchanged files aren't rewritten, so Drive doesn't re-upload them
            if not (dest.exists() and filecmp.cmp(src, dest, shallow=False)):
                shutil.copyfile(src, dest)
    except OSError as e:
        raise PublishError(f"Couldn't write to {folder}: {e}") from e

    names = [name for _, name in wanted]
    old = entry.get("published_dir")
    if old and Path(old) != folder:
        _remove_old(Path(old), entry.get("published_files") or [])
    elif old:       # same folder: drop files no longer published (e.g. captions turned off)
        _remove_old_extra(folder, entry.get("published_files") or [], names)
    return folder, names


def publish(ledger, audio: Path, config: dict, log=None) -> Path | None:
    """Publish one recording and note the result in the ledger. Never raises:
    a problem is logged and left for a later run. Returns the folder, if published."""
    entry = ledger.entry(audio)
    if entry is None or not entry.get("publish_pending") or publish_root(config) is None:
        return None
    try:
        result = publish_files(audio, entry, config)
    except PublishError as e:
        if log:
            log.warning("Not published yet: %s — %s", audio.name, e)
        ledger.annotate(audio, publish_error=str(e)[:300])
        return None
    if result is None:          # not eligible (needs review, or classes not published)
        return None
    folder, names = result
    ledger.annotate(audio, publish_pending=None, publish_error=None, published_dir=str(folder),
                    published_files=names, published_at=datetime.now().isoformat(timespec="seconds"))
    if log:
        log.info("Published %s to %s", audio.name, folder)
    return folder


def publish_pending(ledger, config: dict, log=None) -> list[Path]:
    """Publish everything still waiting (e.g. Drive wasn't running last time)."""
    if publish_root(config) is None:
        return []
    done = []
    for path_str, entry in list(ledger.files.items()):
        if entry.get("publish_pending") and Path(path_str).exists():
            if publish(ledger, Path(path_str), config, log):
                done.append(Path(path_str))
    return done


# ── Command line ──────────────────────────────────────────────────────────────

def _check(config: dict) -> int:
    root = publish_root(config)
    if root is None:
        print("publish_dir isn't set in config.txt — finished documents aren't published.")
        return 1
    print(f"publish_dir: {root}")
    if not root.is_dir():
        print("  ✗ That folder doesn't exist. Is Google Drive for Desktop running and signed in,\n"
              "    and was the folder created in Drive? (See README \"Publishing to Google Drive\".)")
        return 1
    probe = root / ".sermon-transcriber-check"
    try:
        probe.write_text("ok")
        probe.unlink()
    except OSError as e:
        print(f"  ✗ Can't write there: {e}")
        return 1
    if "CloudStorage" not in str(root.resolve()):
        print("  ! This folder isn't inside Google Drive for Desktop (~/Library/CloudStorage/...),\n"
              "    so files copied here won't reach Drive.")
    print("  ✓ Writable.")
    classes = "not published"
    if _true(config.get("publish_classes")):
        classes = "published" + (", with transcripts" if _true(config.get("publish_class_transcripts")) else "")
    print(f"  Higher Ed classes: {classes}; captions: {'yes' if _true(config.get('publish_captions')) else 'no'}")
    return 0


def main():
    from app_home import ensure, read_config
    from auto_transcribe import LEDGER_NAME, Ledger

    ap = argparse.ArgumentParser(description="Publish finished documents to Google Drive.")
    ap.add_argument("command", choices=["check", "backfill"])
    args = ap.parse_args()
    config = read_config()
    if args.command == "check":
        sys.exit(_check(config))

    if _check(config) != 0:
        sys.exit(1)
    ledger = Ledger(ensure() / LEDGER_NAME)
    for path_str, entry in ledger.files.items():
        if entry.get("status") in ("done", "transcribed") and Path(path_str).exists():
            ledger.annotate(Path(path_str), publish_pending=True)
    published = publish_pending(ledger, config)
    held = [Path(p).name for p, e in ledger.files.items()
            if e.get("publish_pending") and e.get("status") == "done"]
    print(f"Published {len(published)} recording(s).")
    if held:
        print(f"Not published (needs review in Sermon Helper, or Drive problem): {', '.join(held)}")


if __name__ == "__main__":
    main()
