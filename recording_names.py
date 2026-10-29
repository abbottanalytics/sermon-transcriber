#!/usr/bin/env python3
"""
Recording filename rules for the automatic job.

Church recordings are named MMDDYY plus a service code, e.g. 110126AM.mp3:

    AM   morning sermon
    PM   evening sermon
    HE   Higher Ed (adult Sunday School) class
    SS   Higher Ed — older recordings from when it was called Sunday School

Case doesn't matter, and anything after the code is ignored
("110126am.mp3", "110126AM-final.mp3"). Any other name isn't a recording
the automatic job processes.

USAGE (as a CLI, for testing):
    python3 recording_names.py 110126AM 110126he.mp3 sermon.mp3
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

# MMDDYY + code, not followed by another letter (so "110126AMX" isn't a match)
_NAME = re.compile(r"^(\d{2})(\d{2})(\d{2})(AM|PM|HE|SS)(?![A-Za-z])", re.IGNORECASE)


@dataclass(frozen=True)
class Recording:
    date: date
    service: str    # AM, PM, HE or SS
    kind: str       # "sermon" or "class"
    event: str

    @property
    def schedule_stem(self) -> str:
        """Key for the preaching schedule lookup, e.g. "110126AM"."""
        return self.date.strftime("%m%d%y") + self.service


def parse_recording_name(name: str) -> Recording | None:
    """Parse a filename or stem; None if it isn't a church recording name."""
    m = _NAME.match(name)
    if not m:
        return None
    month, day, yy, service = m.groups()
    try:
        recorded = date(2000 + int(yy), int(month), int(day))
    except ValueError:      # e.g. 133126AM
        return None
    service = service.upper()
    kind, event = SERVICES[service]
    return Recording(recorded, service, kind, event)


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        rec = parse_recording_name(arg)
        print(f"{arg}: {rec if rec else 'not a recording name'}")
