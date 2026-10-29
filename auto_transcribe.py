#!/usr/bin/env python3
"""
Automatic job: process new church recordings in the watch folder.

Run by the launchd agent (see agent.sh) at run_times (Sundays 1, 7 and 11 pm) and at login, or by
hand. Each run:

  1. Scans watch_dir (and its year subfolders) for recordings named
     MMDDYY + AM/PM/HE/SS, or a special event's code from
     special_events.csv (see recording_names.py)
  2. Skips anything already done, dated before process_from, or still being
     written (modified less than settle_minutes ago)
  3. Sermons: Whisper transcript, then the full sermon documents, with the
     speaker, title and Scripture from the preaching schedule when it has them.
     Higher Ed classes: Whisper transcript, then a class summary, lesson
     outline and discussion guide (class_summary.py).
  4. Records every result in processed.json in the settings folder, so a run
     that was interrupted (shutdown, sleep) just picks up where it left off,
     and posts a Mac notification with what it did.
  5. Copies finished documents to the Google Drive folder, if publish_dir is
     set (see drive_publish.py); anything that needs review is held back.

Settings (config.txt in the settings folder):
    watch_dir        Folder the recordings land in (required)
    output_dir       Where outputs go, in a subfolder per year
                     (default: output/ in the settings folder)
    process_from     YYYY-MM-DD — recordings dated earlier are ignored.
                     Set to today on the first run, so the back catalog
                     isn't processed.
    settle_minutes   Minutes a file must be unchanged before it's processed (10)
    whisper_model    Whisper model (turbo)
    higher_ed_teacher  Teacher named in Higher Ed class documents (optional)
    schedule_sheet   Preaching schedule Google Sheet URL (see google_sheet.py), or
    schedule_file    a preaching schedule CSV instead (optional)
    api_key          OpenAI key (or OPENAI_API_KEY in the environment)
    publish_dir      Google Drive folder for finished documents (optional)

USAGE:
    python3 auto_transcribe.py             # process whatever is new
    python3 auto_transcribe.py --dry-run   # list what would be processed
"""

import argparse
import fcntl
import json
import logging
import os
import subprocess
import sys
import time
from datetime import date, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app_home import ensure, read_config, set_config_value
from drive_publish import publish, publish_pending
from recording_names import parse_recording_name
from run_pipeline import AUDIO_EXTENSIONS, DEFAULT_WHISPER_MODEL, process_file

LEDGER_NAME = "processed.json"
MAX_ATTEMPTS = 3            # per version of a file, then it's left for a person
RETRY_HOURS = 2             # wait between attempts, so a short outage doesn't use them all
DEFAULT_SETTLE_MINUTES = 10
# Same-day order: AM, Higher Ed, PM
SERVICE_ORDER = {"AM": 0, "HE": 1, "SS": 1, "PM": 2}     # special events: by code, after

log = logging.getLogger("auto_transcribe")


# ── Ledger ────────────────────────────────────────────────────────────────────

class Ledger:
    """processed.json: one entry per recording path.

    status: done        — all outputs written
            transcribed — transcript only (Higher Ed from before class summaries
                          existed; picked up again and finished)
            failed      — retried on later runs, up to MAX_ATTEMPTS
            gave_up     — failed MAX_ATTEMPTS times; needs a person
            ignored     — audio file whose name isn't a recording name
    """

    def __init__(self, path: Path):
        self.path = path
        self.reload()

    def reload(self):
        self.data = {"version": 1, "files": {}, "state": {}}
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
            self.data.setdefault("state", {})

    @property
    def files(self) -> dict:
        return self.data["files"]

    @property
    def state(self) -> dict:
        return self.data["state"]

    def _change(self, apply):
        """Re-read, apply a change and save, holding a short lock, so the
        automatic job and Sermon Helper can both write without losing updates."""
        with open(self.path.with_suffix(".lock"), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.reload()
            apply()
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2, sort_keys=True), encoding="utf-8")
            tmp.replace(self.path)     # atomic: never a half-written ledger

    def entry(self, audio: Path) -> dict | None:
        return self.files.get(str(audio))

    def record(self, audio: Path, **fields):
        st = audio.stat()

        def apply():
            entry = self.files.setdefault(str(audio), {})
            entry.update(fields, size=st.st_size, mtime=int(st.st_mtime),
                         updated=datetime.now().isoformat(timespec="seconds"))
        self._change(apply)

    def annotate(self, audio: Path, **fields):
        """Change fields of an existing entry without touching its file details
        (fields set to None are removed)."""
        def apply():
            entry = self.files.setdefault(str(audio), {})
            for key, value in fields.items():
                if value is None:
                    entry.pop(key, None)
                else:
                    entry[key] = value
        self._change(apply)

    def set_state(self, key: str, value):
        """Set (or, with value None, remove) a run-to-run state value."""
        self._change(lambda: self.state.__setitem__(key, value) if value is not None
                     else self.state.pop(key, None))


def _hours_since(iso_time: str) -> float:
    return (datetime.now() - datetime.fromisoformat(iso_time)).total_seconds() / 3600


def file_changed(entry: dict, audio: Path) -> bool:
    """True if the recording was replaced since the ledger entry was written."""
    st = audio.stat()
    return entry.get("size") != st.st_size or entry.get("mtime") != int(st.st_mtime)


# ── Helpers ───────────────────────────────────────────────────────────────────

def notify(message: str):
    """Mac notification (skipped when SERMON_TRANSCRIBER_NO_NOTIFY=1)."""
    log.info("notify: %s", message)
    if os.getenv("SERMON_TRANSCRIBER_NO_NOTIFY") == "1":
        return
    script = ['-e', 'on run argv',
              '-e', 'display notification (item 1 of argv) with title "Sermon Transcriber"',
              '-e', 'end run']
    subprocess.run(["/usr/bin/osascript", *script, message], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def notify_once_a_day(ledger: Ledger, key: str, message: str):
    """For standing problems (no key, no access) — remind daily, not every run."""
    today = date.today().isoformat()
    if ledger.state.get(f"notified_{key}") != today:
        notify(message)
        ledger.set_state(f"notified_{key}", today)


def setup_logging(home: Path):
    logs = home / "logs"
    logs.mkdir(exist_ok=True)
    handler = RotatingFileHandler(logs / "auto.log", maxBytes=1_000_000, backupCount=5)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.addHandler(logging.StreamHandler(sys.stdout))
    log.setLevel(logging.INFO)


def acquire_lock(home: Path):
    """Return an open lock file, or None if another run holds it."""
    lock = open(home / "auto.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        return None
    return lock


class ScheduleSource:
    """The preaching schedule, from the Google Sheet (schedule_sheet) or a CSV
    file (schedule_file). Read once per run and year, only when needed."""

    def __init__(self, config: dict):
        self.config = config
        self.years = {}     # year → schedule dict, or None if unavailable

    @property
    def configured(self) -> bool:
        return bool(self.config.get("schedule_sheet") or self.config.get("schedule_file"))

    def for_year(self, year: int) -> dict | None:
        if year not in self.years:
            self.years[year] = self._load(year)
        return self.years[year]

    def _load(self, year: int) -> dict | None:
        if self.config.get("schedule_sheet"):
            from google_sheet import SheetError, load_year
            try:
                schedule, source = load_year(self.config, year)
            except SheetError as e:
                log.error("Preaching schedule for %d unavailable: %s", year, e)
                return None
            log.info("Preaching schedule %d: %d services from %s", year, len(schedule), source)
            return schedule
        if self.config.get("schedule_file"):
            from schedule_lookup import load_schedule
            path = Path(self.config["schedule_file"]).expanduser()
            if not path.exists():
                log.warning("schedule_file not found: %s", path)
                return None
            return load_schedule(path)
        return None


def schedule_details(rec, schedules: ScheduleSource) -> tuple[dict, list[str]]:
    """Speaker / title / scripture for a sermon, and what a person should review."""
    if rec.special is not None:         # a special event: its row in special_events.csv
        return dict(rec.special), ([] if rec.special.get("speaker") else
                                   [f"no speaker for {rec.service} on {rec.date:%-m/%-d/%y} "
                                    f"in special_events.csv"])
    if not schedules.configured:
        return {}, ["no preaching schedule set up — speaker unknown"]
    schedule = schedules.for_year(rec.date.year)
    if schedule is None:
        return {}, ["preaching schedule unavailable — speaker unknown (see logs/auto.log)"]

    from schedule_lookup import get_entry_for_stem
    entry = get_entry_for_stem(rec.schedule_stem, schedule)
    if entry is None:
        return {}, [f"{rec.date:%-m/%-d/%y} {rec.service} isn't in the preaching schedule"]
    review = []
    if not entry.get("speaker"):
        raw = entry.get("speaker_raw", "")
        review.append(f"preacher initials '{raw}' aren't in speaker_initials.csv" if raw
                      else "no preacher listed in the schedule")
    return entry, review


# ── Scan ──────────────────────────────────────────────────────────────────────

def scan(watch_dir: Path, ledger: Ledger, process_from: date, settle_minutes: int):
    """Return (to_process, waiting, newly_ignored) lists of Paths."""
    to_process, waiting, newly_ignored = [], [], []
    now = time.time()

    for audio in sorted(watch_dir.rglob("*")):
        if (not audio.is_file() or audio.name.startswith(".")
                or audio.suffix.lower() not in AUDIO_EXTENSIONS):
            continue
        entry = ledger.entry(audio)
        rec = parse_recording_name(audio.stem)
        mtime = audio.stat().st_mtime

        if rec is None:
            # Only mention odd names for files that arrived after process_from
            if entry is None and date.fromtimestamp(mtime) >= process_from:
                newly_ignored.append(audio)
            continue
        if rec.date < process_from:
            continue
        if entry and not file_changed(entry, audio):
            if entry["status"] in ("done", "gave_up"):
                continue
            if entry["status"] == "failed" and _hours_since(entry["updated"]) < RETRY_HOURS:
                continue
        if now - mtime < settle_minutes * 60:
            waiting.append(audio)
            continue
        to_process.append(audio)

    to_process.sort(key=lambda p: (parse_recording_name(p.stem).date,
                                   SERVICE_ORDER.get(parse_recording_name(p.stem).service, 3),
                                   parse_recording_name(p.stem).service))
    return to_process, waiting, newly_ignored


# ── Process one recording ─────────────────────────────────────────────────────

def output_dir_for(audio: Path, output_root: Path) -> Path:
    """Outputs go in a folder per year: the recording's date, or for a file
    without a recording name, the year it was last modified."""
    rec = parse_recording_name(audio.stem)
    year = rec.date.year if rec else date.fromtimestamp(audio.stat().st_mtime).year
    return output_root / str(year)


def process_recording(audio: Path, client, output_root: Path, schedules: ScheduleSource,
                      whisper_model: str, confirmed: dict | None = None
                      ) -> tuple[str, list[str], dict]:
    """Returns (status, needs_review notes, schedule details used).

    confirmed: speaker/title/text a person set in Sermon Helper for this
    recording; used instead of the schedule if the recording is redone."""
    rec = parse_recording_name(audio.stem)
    out_dir = output_dir_for(audio, output_root)
    transcript = out_dir / f"{audio.stem}.txt"
    # A transcript from an interrupted earlier run saves re-running Whisper
    have_transcript = transcript.exists()
    review = []

    if rec.kind == "class":
        # The pulpit sheet doesn't list classes: the teacher is what a person
        # confirmed in Sermon Helper, else higher_ed_teacher, else left out
        entry = confirmed or {"speaker": schedules.config.get("higher_ed_teacher")}
        review = []
    elif confirmed:
        entry, review = confirmed, []
    else:
        entry, review = schedule_details(rec, schedules)
    details = {k: entry.get(k) or None for k in ("speaker", "title", "text")}

    process_file(client, audio, content_type=rec.kind, overwrite=True,
                 skip_whisper=have_transcript, style="normal", agenda_md=None,
                 output_dir=out_dir, speaker=details["speaker"], event=rec.event,
                 title=details["title"], scripture=details["text"],
                 whisper_model=whisper_model)
    return "done", review, details


def _remind_unpublished(ledger: Ledger):
    unpublished = [Path(path).name for path, e in ledger.files.items()
                   if e.get("publish_pending") and e.get("publish_error")]
    if unpublished:
        notify_once_a_day(ledger, "publish", f"Couldn't copy {', '.join(unpublished)} to Google Drive "
                          f"— is Google Drive for Desktop running and signed in? (logs/auto.log)")


# ── Main ──────────────────────────────────────────────────────────────────────

def run(dry_run: bool) -> int:
    # Whisper runs "ffmpeg" by name: use the one in this Python's environment
    # (.venv/bin/ffmpeg, linked by update.sh) ahead of anything else installed
    os.environ["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}"

    home = ensure()
    setup_logging(home)

    lock = acquire_lock(home)
    if lock is None:
        log.info("Another run is in progress — exiting.")
        return 0

    ledger = Ledger(home / LEDGER_NAME)
    config = read_config()

    watch_value = config.get("watch_dir", "")
    if not watch_value:
        log.error("watch_dir is not set in %s", home / "config.txt")
        notify_once_a_day(ledger, "no_watch_dir", "Not set up yet: watch_dir is missing in config.txt.")
        return 1
    watch_dir = Path(watch_value).expanduser()

    # A launchd job without permission to read ~/Documents gets EPERM here
    try:
        if not watch_dir.is_dir():
            raise FileNotFoundError(watch_dir)
        next(watch_dir.iterdir(), None)
    except PermissionError:
        log.error("No permission to read %s — grant Full Disk Access (see README).", watch_dir)
        ledger.set_state("access_denied", True)
        notify_once_a_day(ledger, "access", "Can't read the Sermons folder. It needs Full Disk Access — see README.")
        return 3
    except FileNotFoundError:
        log.error("watch_dir not found: %s", watch_dir)
        notify_once_a_day(ledger, "missing_watch_dir", f"Sermons folder not found: {watch_dir}")
        return 1
    if ledger.state.get("access_denied"):
        ledger.set_state("access_denied", None)

    if not config.get("process_from"):
        today = date.today().isoformat()
        config["process_from"] = today
        if not dry_run:
            set_config_value("process_from", today)
            log.info("First run: process_from set to %s — earlier recordings are ignored.", today)
    process_from = date.fromisoformat(config["process_from"])

    # A mistake in special_events.csv makes every special event's recording look
    # like a bad name, so say what's actually wrong
    from special_events import problem
    if problem():
        log.error("Special events are off until this is fixed: %s", problem())
        notify_once_a_day(ledger, "special_events", f"Special events are off: {problem()}")

    settle = int(config.get("settle_minutes") or DEFAULT_SETTLE_MINUTES)
    to_process, waiting, newly_ignored = scan(watch_dir, ledger, process_from, settle)

    if dry_run:
        print(f"Watch folder: {watch_dir}   (recordings from {process_from})")
        for audio in to_process:
            entry = ledger.entry(audio)
            why = ("" if not entry else " (finish: transcript only so far)" if entry["status"] == "transcribed"
                   else f" (retry: {entry['status']})")
            print(f"  would process: {audio.relative_to(watch_dir)}{why}")
        for audio in waiting:
            print(f"  still settling: {audio.relative_to(watch_dir)}")
        for audio in newly_ignored:
            print(f"  not a recording name, ignored: {audio.relative_to(watch_dir)}")
        if not (to_process or waiting or newly_ignored):
            print("  nothing new")
        return 0

    for audio in newly_ignored:
        ledger.record(audio, status="ignored")
        log.info("Ignored (not a recording name): %s", audio)
        notify(f"Skipped {audio.name}: name isn't MMDDYY + AM/PM/HE/SS, or a special "
               f"event listed in special_events.csv.")
    for audio in waiting:
        log.info("Waiting for %s to finish copying.", audio.name)

    # Anything finished earlier that couldn't be published then (Drive not running)
    publish_pending(ledger, config, log)

    if not to_process:
        _remind_unpublished(ledger)
        return 0

    api_key = os.getenv("OPENAI_API_KEY") or config.get("api_key", "")
    if not api_key:
        log.error("No OpenAI API key — set api_key in %s", home / "config.txt")
        notify_once_a_day(ledger, "no_key", "Can't make sermon documents: no OpenAI API key in config.txt.")
        return 1
    from openai import OpenAI
    os.environ["OPENAI_API_KEY"] = api_key
    client = OpenAI(api_key=api_key)

    output_root = Path(config.get("output_dir") or home / "output").expanduser()
    whisper_model = config.get("whisper_model") or DEFAULT_WHISPER_MODEL
    schedules = ScheduleSource(config)

    finished, review_notes, failures = [], [], []
    for audio in to_process:
        entry = ledger.entry(audio)
        attempts = 0 if entry is None or file_changed(entry, audio) else entry.get("attempts", 0)
        log.info("Processing %s (attempt %d)", audio, attempts + 1)
        started = time.time()
        try:
            status, review, details = process_recording(
                audio, client, output_root, schedules, whisper_model,
                confirmed=(entry or {}).get("confirmed"))
        except Exception as e:     # one bad file must not stop the rest
            attempts += 1
            status = "gave_up" if attempts >= MAX_ATTEMPTS else "failed"
            log.exception("Failed: %s", audio.name)
            ledger.record(audio, status=status, attempts=attempts, error=str(e)[:500])
            failures.append(audio.name + (" (gave up)" if status == "gave_up" else ""))
            continue
        minutes = (time.time() - started) / 60
        out_dir = output_dir_for(audio, output_root)
        ledger.record(audio, status=status, attempts=attempts + 1, needs_review=review,
                      speaker=details.get("speaker"), title=details.get("title"),
                      scripture=details.get("text"), output_dir=str(out_dir),
                      minutes=round(minutes, 1), error=None, publish_pending=True)
        publish(ledger, audio, config, log)
        log.info("Finished %s in %.1f min: %s%s", audio.name, minutes, status,
                 f" — review: {'; '.join(review)}" if review else "")
        finished.append(audio.name)
        review_notes += [f"{audio.name}: {note}" for note in review]

    _remind_unpublished(ledger)

    if finished:
        notify(f"Transcribed {len(finished)}: {', '.join(finished)}"
               + (f". Review in Sermon Helper: {'; '.join(review_notes)}" if review_notes else ""))
    if failures:
        notify(f"Problem processing {', '.join(failures)} — see logs/auto.log.")
    return 0 if not failures else 2


def main():
    ap = argparse.ArgumentParser(description="Process new church recordings in the watch folder.")
    ap.add_argument("--dry-run", action="store_true", help="List what would be processed, then stop")
    args = ap.parse_args()
    sys.exit(run(args.dry_run))


if __name__ == "__main__":
    main()
