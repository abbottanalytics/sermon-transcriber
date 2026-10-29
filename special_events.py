#!/usr/bin/env python3
"""
Special events: conferences and other services the church hosts that aren't
Sunday services, listed in special_events.csv in the settings folder.

    date,code,speaker,title,scripture,event
    11/6/26,RC1,Dr. First Speaker,Title of the Session,2 Timothy 3:14-17,Reformation Conference
    11/7/26,RC1,...
    11/7/26,RC2,...

A recording named with the date and a code from this file, e.g. 110726RC2.mp3,
is processed like a sermon, with the speaker, title and passage from its row.
A code is only recognized for the dates it's listed under, so a typo in a
file name is still reported rather than processed with no details.

Codes are two letters plus an optional session number (RC, RC1, RC2...).
AM, PM, HE and SS are the Sunday codes and can't be used here.

USAGE:
    python3 special_events.py           # list the events as the pipeline reads them
"""

import csv
import re
import sys
from datetime import date, datetime
from pathlib import Path

FILE_NAME = "special_events.csv"
RESERVED = {"AM", "PM", "HE", "SS"}
CODE = re.compile(r"^[A-Za-z]{2}\d{0,2}$")
DATE_FORMATS = ["%m/%d/%y", "%m/%d/%Y", "%m%d%y", "%Y-%m-%d"]


class SpecialEventsError(ValueError):
    pass


def _parse_date(value: str) -> date:
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    raise SpecialEventsError(f"date {value!r} isn't like 11/6/26")


def parse(text: str) -> dict[tuple[date, str], dict]:
    """special_events.csv text → {(date, CODE): {speaker, title, text, event}}."""
    numbered = [(n, line) for n, line in enumerate(text.splitlines(), start=1)
                if line.strip() and not line.lstrip().startswith("#")]
    line_numbers = [n for n, _ in numbered[1:]]       # the first is the header
    events = {}
    for n, row in zip(line_numbers, csv.DictReader([line for _, line in numbered])):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        if not any(row.values()):
            continue
        code = row.get("code", "").upper()
        if not CODE.match(code) or code[:2] in RESERVED:
            raise SpecialEventsError(f"line {n}: code {code!r} should be two letters and an "
                                     f"optional number (e.g. RC1), and not AM/PM/HE/SS")
        try:
            when = _parse_date(row.get("date", ""))
        except SpecialEventsError as e:
            raise SpecialEventsError(f"line {n}: {e}") from None
        if not row.get("event"):
            raise SpecialEventsError(f"line {n}: the event name is missing")
        events[(when, code)] = {"speaker": row.get("speaker") or None,
                                "title": row.get("title") or None,
                                "text": row.get("scripture") or None,
                                "event": row["event"]}
    return events


_cache: dict = {}


def load() -> dict[tuple[date, str], dict]:
    """The settings folder's special_events.csv, re-read whenever it changes.
    A file with a mistake in it is reported once and treated as empty."""
    from app_home import data_file
    path: Path = data_file(FILE_NAME)
    stamp = path.stat().st_mtime_ns
    if _cache.get("stamp") != stamp:
        try:
            events = parse(path.read_text(encoding="utf-8"))
        except SpecialEventsError as e:
            print(f"WARNING: {path} — {e}. Special events are ignored until it's fixed.",
                  file=sys.stderr)
            events = {}
            _cache["problem"] = f"{path.name} {e}"
        else:
            _cache["problem"] = None
        _cache.update(stamp=stamp, events=events)
    return _cache["events"]


def problem() -> str | None:
    """What's wrong with special_events.csv, or None if it reads fine."""
    load()
    return _cache.get("problem")


def lookup(when: date, code: str) -> dict | None:
    return load().get((when, code.upper()))


def main():
    from app_home import data_file
    path = data_file(FILE_NAME)
    try:
        events = parse(path.read_text(encoding="utf-8"))
    except SpecialEventsError as e:
        sys.exit(f"ERROR in {path}: {e}")
    if not events:
        print(f"No special events listed in {path}")
    for (when, code), e in sorted(events.items()):
        print(f"{when:%m%d%y}{code}.mp3  {when:%a %-m/%-d/%y}  {e['event']}: "
              f"{e['speaker'] or '(speaker?)'} — {e['title'] or '(title?)'}"
              + (f" — {e['text']}" if e["text"] else ""))


if __name__ == "__main__":
    main()
