#!/usr/bin/env python3
"""
Preaching schedule lookup.

Reads a CSV schedule (exported from the pulpit planning spreadsheet) and
returns the preacher's full name for a given sermon filename stem.

Filename stems are expected to follow the MMDDYY pattern (e.g. 010724AM
for January 7, 2024 AM). AM/PM is determined from the suffix.

USAGE (as a module):
    from schedule_lookup import load_schedule, get_speaker_for_stem
    schedule = load_schedule(Path("pulpit_schedule.csv"))
    speaker = get_speaker_for_stem("010724AM", schedule)
    # → "Pastor Joel E. Wood"

USAGE (as a CLI, for testing):
    python3 schedule_lookup.py pulpit_schedule.csv 010724AM

Initials → full names come from speaker_initials.csv, and fixes for blank
preacher cells from schedule_overrides.csv. Both live in the per-machine
settings folder (see app_home.py) so each computer can keep its own.
"""

import csv
import re
import sys
from functools import lru_cache
from pathlib import Path

from app_home import data_file


def _letters_only(text: str) -> str:
    """Lower-case letters only — "J W", "jw " and "JW?" all become "jw"."""
    return re.sub(r"[^a-z]", "", text.lower())


def _read_csv_rows(path: Path) -> list[dict]:
    """Read a CSV that may contain # comment lines."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        lines = [line for line in f if not line.lstrip().startswith("#")]
    return list(csv.DictReader(lines))


@lru_cache(maxsize=None)
def preacher_map() -> dict:
    """Initials / name → full name with title, from speaker_initials.csv."""
    return {
        _letters_only(row["initials"]): row["full_name"].strip()
        for row in _read_csv_rows(data_file("speaker_initials.csv"))
        if (row.get("initials") or "").strip() and (row.get("full_name") or "").strip()
    }


@lru_cache(maxsize=None)
def date_overrides() -> dict:
    """"MMDDYY_AM" / "MMDDYY_PM" → full name, from schedule_overrides.csv.
    Used when the schedule's preacher cell is blank for that service."""
    return {
        f"{row['date'].strip()}_{row['service'].strip().upper()}": row["speaker"].strip()
        for row in _read_csv_rows(data_file("schedule_overrides.csv"))
        if all((row.get(k) or "").strip() for k in ("date", "service", "speaker"))
    }


def resolve_initials(raw: str) -> str | None:
    """
    Map a raw preacher cell value (initials, surname, or full name) to a
    canonical full name. Returns None if the cell is blank or holds initials
    that aren't in speaker_initials.csv — a name is never guessed from
    initials.
    """
    if not raw:
        return None

    # Ignore case, spaces and punctuation like "?" (e.g. "AP?", "J M")
    cleaned = _letters_only(raw)

    if not cleaned:
        return None

    # Direct lookup (handles initials, surnames, full names)
    if cleaned in preacher_map():
        return preacher_map()[cleaned]

    # Unknown initials ("SE") — leave the speaker unknown so it gets reviewed
    if len(cleaned) <= 3:
        return None

    # A written-out name (e.g. a guest preacher) — use it as written
    name = " ".join(raw.split())
    return name.title() if name.isupper() else name


def _parse_date_to_stem(date_str: str) -> str | None:
    """
    Convert a schedule date like "1/7/24" or "1/7/2024" to "MMDDYY".
    Returns None if unparseable.
    """
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", date_str.strip())
    if not m:
        return None
    month, day, year = m.groups()
    yy = year[-2:]  # last two digits
    return f"{int(month):02d}{int(day):02d}{yy}"


def _detect_name_in_title(title: str) -> str | None:
    """
    Some rows have the guest preacher's name in the title column instead of
    the preacher column (e.g. "GREG BEALE", "DAVID ZADOK", "LIGON DUNCAN").
    Detect this by checking if the title looks like an all-caps name and
    matches a known preacher.
    """
    if not title:
        return None
    # All-caps words (at least 2), no digits — looks like a name
    if re.match(r"^[A-Z][A-Z\s]+$", title.strip()) and len(title.split()) >= 2:
        return resolve_initials(title.strip())
    return None


# ── Columns ───────────────────────────────────────────────────────────────────
# Header names in the pulpit schedule, matched ignoring case and spacing.
# Other columns (Leader, Supper, Notes, Song Ideas...) are ignored, so columns
# can be added or moved from year to year.
COLUMNS = {
    "date": "date", "event": "event",
    "am text": "am_text", "am title": "am_title", "am preacher": "am_preacher",
    "pm text": "pm_text", "pm title": "pm_title", "pm preacher": "pm_preacher",
}
# The first three header cells have been typed over in some years (2026 reads
# "cvv", "cv", "ynn b"), so when those names are missing use their positions.
POSITION_FALLBACKS = {"date": 0, "event": 1, "am_text": 2}


def _norm_header(cell: str) -> str:
    return " ".join(cell.lower().split())


def _find_columns(rows: list[list[str]]) -> tuple[int, dict] | None:
    """Return (header row index, field → column index), or None if no header."""
    for i, row in enumerate(rows[:10]):
        found = {}
        for col, cell in enumerate(row):
            field = COLUMNS.get(_norm_header(cell))
            if field and field not in found:
                found[field] = col
        # A real header has the preacher/title columns even when its first
        # cells are mangled
        if len({"am_title", "am_preacher", "pm_title", "pm_preacher"} & found.keys()) >= 2:
            taken = set(found.values())
            for field, col in POSITION_FALLBACKS.items():
                if field not in found and col not in taken:
                    found[field] = col
            return i, found
    return None


def _cell(row: list[str], columns: dict, field: str, joiner: str = " ") -> str:
    """Cell value with line breaks inside the cell joined (two passages in one cell)."""
    col = columns.get(field)
    if col is None or col >= len(row):
        return ""
    return joiner.join(part.strip() for part in str(row[col]).splitlines() if part.strip())


def parse_schedule_rows(rows: list[list[str]]) -> dict:
    """
    Parse schedule rows (header row + one row per Sunday, from a CSV file or
    the Google Sheet) into a lookup dict:

        {
            "MMDDYY_AM": {"speaker": "Full Name" or None, "speaker_raw": "JM",
                          "text": "...", "title": "...", "event": "..."},
            "MMDDYY_PM": {...},
        }

    Handles:
    - Mangled or moved header cells (see COLUMNS / POSITION_FALLBACKS)
    - Multiple rows for the same date (keeps the most useful preacher entry)
    - Blank preacher cells with name in title
    - Date overrides for known blanks
    - Trailing spaces, "AP?", etc.
    """
    schedule = {}
    located = _find_columns(rows)
    if located is None:
        return schedule
    header_index, columns = located

    for row in rows[header_index + 1:]:
        date_str = _cell(row, columns, "date")
        if not date_str:
            continue

        stem = _parse_date_to_stem(date_str)
        if not stem:
            continue

        event = _cell(row, columns, "event")
        for service in ("AM", "PM"):
            key = f"{stem}_{service}"
            prefix = service.lower()
            preacher_raw = _cell(row, columns, f"{prefix}_preacher")
            title        = _cell(row, columns, f"{prefix}_title")
            text         = _cell(row, columns, f"{prefix}_text", joiner="; ")

            # Skip placeholder rows ("X")
            if text == "X" or title == "X":
                continue

            speaker = resolve_initials(preacher_raw)
            if not speaker:
                speaker = _detect_name_in_title(title)
            if not speaker:
                speaker = date_overrides().get(key)

            # Only write an entry if we have useful data; don't overwrite a
            # good entry with a blank one (handles the 3/31 Easter/Garden case
            # by keeping whichever non-blank entry we see last)
            if speaker or text or title:
                existing = schedule.get(key, {})
                if speaker or not existing.get("speaker"):
                    schedule[key] = {
                        "speaker":     speaker,
                        "speaker_raw": preacher_raw,
                        "text":        text,
                        "title":       title,
                        "event":       event,
                    }

    return schedule


def load_schedule(csv_path: Path) -> dict:
    """Parse a schedule CSV (exported from the pulpit sheet) — see parse_schedule_rows."""
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        return parse_schedule_rows(list(csv.reader(f)))


def get_entry_for_stem(stem: str, schedule: dict) -> dict | None:
    """
    Given a filename stem like "010724AM" or "010724pm", return its schedule
    entry, or None. A bare date ("010724") means AM; other service codes
    ("010724HE") have no schedule entry.
    """
    m = re.match(r"^(\d{6})([A-Za-z]{2})?", stem.strip())
    if not m:
        return None
    service = (m.group(2) or "AM").upper()
    return schedule.get(f"{m.group(1)}_{service}")


def get_speaker_for_stem(stem: str, schedule: dict) -> str | None:
    """The preacher's full name for a filename stem, or None if not found."""
    return (get_entry_for_stem(stem, schedule) or {}).get("speaker")


# ── CLI for testing ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 schedule_lookup.py <schedule.csv> [stem ...]")
        sys.exit(1)

    csv_path = Path(sys.argv[1])
    schedule = load_schedule(csv_path)

    if len(sys.argv) == 2:
        # Dump the whole schedule
        for key in sorted(schedule):
            entry = schedule[key]
            spk   = entry.get("speaker") or "(unknown)"
            title = entry.get("title") or ""
            text  = entry.get("text") or ""
            print(f"{key}  {spk:<35}  {text:<25}  {title}")
    else:
        for stem in sys.argv[2:]:
            speaker = get_speaker_for_stem(stem, schedule)
            print(f"{stem}: {speaker or '(not found)'}")
