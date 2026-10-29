#!/usr/bin/env python3
"""
Read the preaching schedule straight from its Google Sheet.

The sheet stays private. It is shared (as Viewer) with a Google *service
account*, a robot Google identity whose key file sits in the settings
folder, so this computer can read it without anyone signing in.
README "Connecting the Google Sheet" walks through the one-time setup.

Settings (config.txt in the settings folder):
    schedule_sheet       The sheet's URL (or just its ID)
    google_credentials   Service-account key file
                         (default: google_service_account.json in the settings folder)

The sheet has one tab per year. For a 2026 recording the tab named "2026" is
used, or failing that a tab whose name contains 2026.

Every successful read is saved to schedules/sheet_<year>.csv in the settings
folder, and that copy is used when Google can't be reached.

USAGE:
    python3 google_sheet.py check        # test the connection, list the tabs
    python3 google_sheet.py show 2026    # print the 2026 schedule as read
"""

import csv
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from app_home import data_file, ensure, read_config
from schedule_lookup import parse_schedule_rows

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
# Overridable so tests can use a local stand-in for Google
API_BASE = os.getenv("SERMON_TRANSCRIBER_SHEETS_API", "https://sheets.googleapis.com/v4")
DEFAULT_CREDENTIALS = "google_service_account.json"
TIMEOUT_SECONDS = 30


class SheetError(Exception):
    """A problem reading the sheet, worded for whoever has to fix it."""


def sheet_id(value: str) -> str:
    """Accept a full sheet URL or a bare ID."""
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", value)
    return m.group(1) if m else value.strip()


def credentials_path(config: dict) -> Path:
    value = config.get("google_credentials", "")
    return Path(value).expanduser() if value else data_file(DEFAULT_CREDENTIALS)


def _credentials(config: dict):
    path = credentials_path(config)
    if not path.exists():
        raise SheetError(f"Service-account key file not found: {path}")
    from google.oauth2 import service_account
    try:
        return service_account.Credentials.from_service_account_file(str(path), scopes=SCOPES)
    except (ValueError, KeyError) as e:
        raise SheetError(f"{path.name} isn't a service-account key file ({e})") from e


def _access_token(creds) -> str:
    from google.auth.exceptions import GoogleAuthError, TransportError
    from google.auth.transport.requests import Request
    try:
        creds.refresh(Request())
    except TransportError as e:
        raise SheetError("Couldn't reach Google to sign in (is this computer online?)") from e
    except GoogleAuthError as e:
        raise SheetError(f"Google sign-in for the service account failed: {e}") from e
    return creds.token


def _get_json(url: str, token: str, creds) -> dict:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        try:
            detail = json.load(e).get("error", {}).get("message", "")
        except ValueError:
            detail = ""
        if e.code == 403:
            raise SheetError(
                f"The sheet isn't shared with {creds.service_account_email} "
                f"(share it with that address as Viewer). {detail}".strip()) from e
        if e.code == 404:
            raise SheetError("Sheet not found — check schedule_sheet in config.txt.") from e
        raise SheetError(f"Google Sheets error {e.code}: {detail or e.reason}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise SheetError(f"Couldn't reach Google Sheets: {e}") from e


class SheetClient:
    def __init__(self, config: dict):
        value = config.get("schedule_sheet", "")
        if not value:
            raise SheetError("schedule_sheet is not set in config.txt.")
        self.id = sheet_id(value)
        self.creds = _credentials(config)
        self.token = _access_token(self.creds)

    def _get(self, path: str, **params) -> dict:
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        return _get_json(f"{API_BASE}/spreadsheets/{self.id}{path}{query}", self.token, self.creds)

    def tab_titles(self) -> list[str]:
        meta = self._get("", fields="sheets.properties.title")
        return [s["properties"]["title"] for s in meta.get("sheets", [])]

    def tab_for_year(self, year: int) -> str:
        titles = self.tab_titles()
        wanted = str(year)
        for title in titles:
            if title.strip() == wanted:
                return title
        for title in titles:
            if wanted in title:
                return title
        raise SheetError(f"No tab for {year} in the sheet (tabs: {', '.join(titles)}).")

    def rows(self, tab: str) -> list[list[str]]:
        # Quote the tab name for A1 notation: 'My Tab' (a ' inside becomes '')
        a1 = "'" + tab.replace("'", "''") + "'"
        data = self._get(f"/values/{urllib.parse.quote(a1, safe='')}")
        return data.get("values", [])


def _cache_path(year: int) -> Path:
    return ensure() / "schedules" / f"sheet_{year}.csv"


def _save_cache(year: int, rows: list[list[str]]):
    path = _cache_path(year)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    tmp.replace(path)


def _read_cache(year: int) -> list[list[str]] | None:
    path = _cache_path(year)
    if not path.exists():
        return None
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


def load_year(config: dict, year: int, client: SheetClient | None = None) -> tuple[dict, str]:
    """
    The schedule for one year from the sheet, as a schedule_lookup dict, plus
    a note on where it came from. Falls back to the last saved copy when the
    sheet can't be read; raises SheetError if there is neither.
    """
    try:
        client = client or SheetClient(config)
        tab = client.tab_for_year(year)
        rows = client.rows(tab)
        _save_cache(year, rows)
        return parse_schedule_rows(rows), f"Google Sheet tab '{tab}'"
    except SheetError as e:
        rows = _read_cache(year)
        if rows is None:
            raise
        return parse_schedule_rows(rows), f"saved copy {_cache_path(year).name} (sheet unavailable: {e})"


# ── CLI ───────────────────────────────────────────────────────────────────────

def _check(config: dict) -> int:
    client = SheetClient(config)
    print(f"Connected as {client.creds.service_account_email}")
    print(f"Tabs: {', '.join(client.tab_titles())}")
    return 0


def _show(config: dict, year: int) -> int:
    schedule, source = load_year(config, year)
    print(f"{len(schedule)} services from {source}")
    for key in sorted(schedule, key=lambda k: (k[4:6], k[:4], k[-2:])):
        e = schedule[key]
        speaker = e["speaker"] or f"(unknown: {e['speaker_raw']!r})"
        print(f"  {key}  {speaker:<28} {e['text'][:30]:<30} {e['title']}")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    try:
        if args == ["check"]:
            sys.exit(_check(read_config()))
        if len(args) == 2 and args[0] == "show" and args[1].isdigit():
            sys.exit(_show(read_config(), int(args[1])))
    except SheetError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    print(__doc__.split("USAGE:")[1].rstrip())
    sys.exit(2)
