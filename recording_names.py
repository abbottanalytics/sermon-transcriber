#!/usr/bin/env python3
"""
Recording filename rules for the automatic job.

Church recordings are named MMDDYY plus a service code, e.g. 110126AM.mp3:

    AM   morning sermon
    PM   evening sermon
    HE   Higher Ed (adult Sunday School) class
    SS   Higher Ed — older recordings from when it was called Sunday School

Case doesn't matter, and anything after the code is ignored
("110126am.mp3", "110126AM-final.mp3").

Special events (conferences and the like) use their own codes, listed with
their dates in special_events.csv: 110726RC2.mp3 is session RC2 on 11/7/26
(see special_events.py). Any other name isn't a recording the automatic job
processes.

USAGE (as a CLI, for testing):
    python3 recording_names.py 110126AM 110126he.mp3 110726RC2.mp3 sermon.mp3
"""

import re
import sys
from dataclasses import dataclass
from datetime import date

# service code → (kind, event name used in the documents)
SERVICES = {
    "AM": ("sermon", "Morning Worship Service"),
    "PM": ("sermon", "Evening Worship Service"),
    "HE": ("class",  "Higher Ed (Adult Sunday School)"),
    "SS": ("class",  "Higher Ed (Adult Sunday School)"),
}

# MMDDYY + two-letter code + optional session number, not followed by another
# letter (so "110126AMX" isn't a match)
_NAME = re.compile(r"^(\d{2})(\d{2})(\d{2})([A-Za-z]{2})(\d{0,2})(?![A-Za-z])")


@dataclass(frozen=True)
class Recording:
    date: date
    service: str    # AM, PM, HE or SS, or a special event's code (RC1)
    kind: str       # "sermon" or "class"
    event: str
    special: dict | None = None     # a special event's row: speaker, title, text

    @property
    def schedule_stem(self) -> str:
        """Key for the preaching schedule lookup, e.g. "110126AM"."""
        return self.date.strftime("%m%d%y") + self.service


def parse_recording_name(name: str) -> Recording | None:
    """Parse a filename or stem; None if it isn't a church recording name."""
    m = _NAME.match(name)
    if not m:
        return None
    month, day, yy, code, number = m.groups()
    try:
        recorded = date(2000 + int(yy), int(month), int(day))
    except ValueError:      # e.g. 133126AM
        return None
    code = code.upper()
    if code in SERVICES:                    # Sunday: any number after it is ignored
        kind, event = SERVICES[code]
        return Recording(recorded, code, kind, event)

    from special_events import lookup
    row = lookup(recorded, code + number)
    if row is None:
        return None
    return Recording(recorded, code + number, "sermon", row["event"], row)


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        rec = parse_recording_name(arg)
        print(f"{arg}: {rec if rec else 'not a recording name'}")
