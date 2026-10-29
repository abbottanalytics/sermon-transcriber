#!/usr/bin/env python3
"""
Sermon Helper — fix or finish a recording's documents, in plain Mac dialogs.

Double-click "Sermon Helper.command". It lists recent recordings, with the
ones that need a person first (⚠ — e.g. the preacher wasn't in the schedule,
or processing failed). For the one picked it asks:

    Type        Sermon (the default) or Higher Ed class
    Speaker     the preaching schedule's preacher, someone from the speaker
                list (preachers.txt), or a name typed in
    Title       pre-filled from the preaching schedule
    Scripture   pre-filled from the preaching schedule

and then makes the sermon documents. A Higher Ed class asks for the teacher,
topic and passage instead (all optional, pre-filled from the last class), and
makes the class summary, lesson outline and discussion guide. An existing transcript is reused, so a
correction takes a minute or two rather than a new transcription.
"Choose a different file…" handles any recording, including one the
automatic job doesn't pick up (an unusual name, or before process_from).

What a person confirms here is saved in processed.json and used again if the
automatic job ever redoes that recording.

Test mode: see mac_dialogs.py (SERMON_HELPER_ANSWERS).
"""

import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import mac_dialogs as dlg
from app_home import data_file, ensure, read_config
from class_summary import HIGHER_ED_EVENT
from drive_publish import publish, publish_root
from auto_transcribe import (LEDGER_NAME, Ledger, ScheduleSource, log, output_dir_for,
                             schedule_details, setup_logging)
from recording_names import parse_recording_name
from run_pipeline import DEFAULT_WHISPER_MODEL, process_file

RECENT_DAYS = 21            # done recordings older than this aren't listed
PREACHER_CAP = 5            # same rule as pipeline_helpers.sh
SERMON, CLASS = "Sermon", "Higher Ed class"
OTHER = "Other (type a name)…"
CHOOSE_FILE = "Choose a different file…"


# ── Speaker list (preachers.txt) ──────────────────────────────────────────────

def _preacher_lines() -> list[str]:
    return data_file("preachers.txt").read_text(encoding="utf-8").splitlines()


def speaker_menu() -> list[str]:
    """Speakers entered at least twice (or capped), as in the Terminal menus."""
    names = []
    for line in _preacher_lines():
        if not line.strip() or line.startswith("#"):
            continue
        name, _, count = line.partition("|")
        if count == f"{PREACHER_CAP}+" or (count.isdigit() and int(count) >= 2):
            names.append(name)
    return names


def bump_speaker_count(name: str):
    """Add one to a speaker's count (capped at N+), or add them with 1 —
    the same rules as update_preacher_count in pipeline_helpers.sh."""
    cap = f"{PREACHER_CAP}+"
    out, found = [], False
    for line in _preacher_lines():
        pname, sep, count = line.partition("|")
        if line.startswith("#") or not line.strip() or pname != name:
            out.append(line)
            continue
        found = True
        if count == cap:
            out.append(f"{pname}|{cap}")
        elif count.isdigit():
            n = int(count) + 1
            out.append(f"{pname}|{cap if n >= PREACHER_CAP else n}")
        else:
            out.append(f"{pname}|1")
    if not found:
        out.append(f"{name}|1")
    data_file("preachers.txt").write_text("\n".join(out) + "\n", encoding="utf-8")


def sermon_events() -> list[str]:
    """The [sermon] section of events.txt."""
    events, section = [], ""
    for line in data_file("events.txt").read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
        elif section == "sermon":
            events.append(line.strip())
    return events


# ── The list of recordings ────────────────────────────────────────────────────

def _needs_person(entry: dict) -> bool:
    return entry["status"] in ("failed", "gave_up") or (
        entry["status"] == "done" and bool(entry.get("needs_review")))


def recent_recordings(ledger: Ledger) -> list[tuple[str, Path]]:
    """(label, path) for the picker: needs-a-person first, then newest first."""
    rows = []
    today = date.today()
    for path_str, entry in ledger.files.items():
        audio = Path(path_str)
        if entry.get("status") == "ignored" or not audio.exists():
            continue
        rec = parse_recording_name(audio.stem)
        when = rec.date if rec else date.fromisoformat(entry["updated"][:10])
        flagged = _needs_person(entry)
        if not flagged and (today - when).days > RECENT_DAYS:
            continue

        if flagged:
            mark = "⚠"
            what = entry.get("error") or "; ".join(entry.get("needs_review") or [])
            what = f"{'failed: ' if entry.get('error') else ''}{what}"[:70]
        elif entry["status"] == "transcribed":
            mark, what = "📝", "transcript only"
        else:
            mark, what = "✓", entry.get("title") or ""
        who = entry.get("speaker") or ""
        label = " — ".join(part for part in (f"{mark} {audio.stem}", who, what) if part)
        rows.append((not flagged, -when.toordinal(), audio.stem, label, audio))

    rows.sort()
    labels, out = set(), []
    for *_, label, audio in rows:
        if label in labels:                     # same name in two folders
            label = f"{label} ({audio.parent.name})"
        labels.add(label)
        out.append((label, audio))
    return out


# ── One recording ─────────────────────────────────────────────────────────────

class Helper:
    def __init__(self):
        self.home = ensure()
        self.config = read_config()
        self.ledger = Ledger(self.home / LEDGER_NAME)
        self.schedules = ScheduleSource(self.config)
        self.output_root = Path(self.config.get("output_dir") or self.home / "output").expanduser()
        self.whisper_model = self.config.get("whisper_model") or DEFAULT_WHISPER_MODEL
        watch = self.config.get("watch_dir") or self.config.get("input_dir") or ""
        self.watch_dir = Path(watch).expanduser() if watch else None
        self._client = None

    def client(self):
        if self._client is None:
            api_key = os.getenv("OPENAI_API_KEY") or self.config.get("api_key", "")
            if not api_key:
                return None
            from openai import OpenAI
            os.environ["OPENAI_API_KEY"] = api_key
            self._client = OpenAI(api_key=api_key)
        return self._client

    def handle(self, audio: Path):
        entry = self.ledger.entry(audio) or {}
        rec = parse_recording_name(audio.stem)
        default_kind = CLASS if rec and rec.kind == "class" else SERMON
        kind = dlg.choose(f"{audio.name}\n\nWhat kind of recording is this?",
                          [SERMON, CLASS], default_kind)
        if kind is None:
            return
        if kind == CLASS:
            self.higher_ed(audio, entry)
        else:
            self.sermon(audio, rec, entry)

    def last_class(self, audio: Path) -> dict:
        """Teacher/topic/passage of the latest earlier class: a series usually
        has the same teacher and topic from week to week."""
        rec = parse_recording_name(audio.stem)
        latest, details = None, {}
        for path_str, entry in self.ledger.files.items():
            other = parse_recording_name(Path(path_str).stem)
            if (other and other.kind == "class" and entry.get("confirmed")
                    and (rec is None or other.date < rec.date)
                    and (latest is None or other.date > latest)):
                latest, details = other.date, entry["confirmed"]
        return details

    def higher_ed(self, audio: Path, entry: dict):
        base = entry.get("confirmed") or self.last_class(audio)
        teacher_default = base.get("speaker") or self.config.get("higher_ed_teacher") or ""
        teacher = dlg.ask("Who taught the class? (Leave blank if you're not sure.)", teacher_default)
        if teacher is None:
            return
        title = dlg.ask("Class topic or series (optional):", base.get("title") or "")
        if title is None:
            return
        scripture = dlg.ask("Passage studied (optional):", base.get("text") or "")
        if scripture is None:
            return

        out_dir = output_dir_for(audio, self.output_root)
        have_transcript = (out_dir / f"{audio.stem}.txt").exists()
        timing = ("about a minute (the existing transcript is reused)" if have_transcript else
                  "a while: the recording is transcribed first, up to an hour on an older Mac")
        summary = "\n".join(f"{k}: {v}" for k, v in (("Teacher", teacher), ("Topic", title),
                            ("Passage", scripture)) if v)
        go = dlg.buttons(f"Make the class documents for {audio.name}?\n\n{summary}\n\n"
                         f"You'll get a class summary, a lesson outline, a discussion guide "
                         f"and a podcast description. "
                         f"Class members aren't named in them. This takes {timing}. "
                         f"Progress shows in the Terminal window.",
                         ["Cancel", "Make documents"], "Make documents")
        if go is None:
            return
        client = self.client()
        if client is None:
            dlg.info(f"There's no OpenAI API key yet. Add it on the api_key line of\n\n"
                     f"{self.home / 'config.txt'}")
            return

        print(f"\nMaking class documents for {audio.name}...")
        try:
            process_file(client, audio, content_type="class", overwrite=True,
                         skip_whisper=have_transcript, style="normal", agenda_md=None,
                         output_dir=out_dir, speaker=teacher or None,
                         event=HIGHER_ED_EVENT, title=title or None,
                         scripture=scripture or None, whisper_model=self.whisper_model)
        except Exception as e:
            log.exception("Sermon Helper: failed for %s", audio.name)
            dlg.info(f"Making the class documents for {audio.name} failed:\n\n{e}")
            return

        confirmed = {"speaker": teacher, "title": title, "text": scripture}
        self.ledger.record(audio, status="done", needs_review=[], confirmed=confirmed,
                           speaker=teacher or None, title=title or None,
                           scripture=scripture or None, output_dir=str(out_dir),
                           error=None, publish_pending=True)
        log.info("Sermon Helper: made class documents for %s", audio.name)
        self.show(out_dir / f"{audio.stem}.summary.docx",
                  f"Done — the class documents for {audio.name} are ready.{self.publish(audio)}")

    def sermon(self, audio: Path, rec, entry: dict):
        # Defaults: what a person confirmed before, else the preaching schedule
        sched, notes = ({}, [])
        if rec and rec.kind == "sermon":
            sched, notes = schedule_details(rec, self.schedules)
        base = entry.get("confirmed") or sched

        speaker = self.pick_speaker(base.get("speaker"), sched, notes, bool(entry.get("confirmed")))
        if speaker is None:
            return
        title = dlg.ask("Sermon title:", base.get("title") or "")
        if title is None:
            return
        scripture = dlg.ask("Scripture passage (e.g. Acts 24 or John 1:1-18):", base.get("text") or "")
        if scripture is None:
            return
        if rec and rec.kind == "sermon":
            event = rec.event
        else:
            events = sermon_events() or ["Morning Worship Service"]
            event = dlg.choose("Which service or event?", events, events[0])
            if event is None:
                return

        out_dir = output_dir_for(audio, self.output_root)
        have_transcript = (out_dir / f"{audio.stem}.txt").exists()
        timing = ("about a minute (the existing transcript is reused)" if have_transcript else
                  "a while: the recording is transcribed first, up to an hour on an older Mac")
        summary = "\n".join(f"{k}: {v}" for k, v in (("Speaker", speaker), ("Title", title),
                            ("Scripture", scripture), ("Event", event)) if v)
        go = dlg.buttons(f"Make the sermon documents for {audio.name}?\n\n{summary}\n\n"
                         f"This takes {timing}. Progress shows in the Terminal window.",
                         ["Cancel", "Make documents"], "Make documents")
        if go is None:
            return

        client = self.client()
        if client is None:
            dlg.info(f"There's no OpenAI API key yet. Add it on the api_key line of\n\n"
                     f"{self.home / 'config.txt'}")
            return

        print(f"\nMaking documents for {audio.name}...")
        try:
            process_file(client, audio, content_type="sermon", overwrite=True,
                         skip_whisper=have_transcript, style="normal", agenda_md=None,
                         output_dir=out_dir, speaker=speaker, event=event,
                         title=title or None, scripture=scripture or None,
                         whisper_model=self.whisper_model)
        except Exception as e:
            log.exception("Sermon Helper: failed for %s", audio.name)
            dlg.info(f"Making the documents for {audio.name} failed:\n\n{e}")
            return

        confirmed = {"speaker": speaker, "title": title, "text": scripture}
        self.ledger.record(audio, status="done", needs_review=[], confirmed=confirmed,
                           speaker=speaker, title=title or None, scripture=scripture or None,
                           output_dir=str(out_dir), error=None, publish_pending=True)
        bump_speaker_count(speaker)
        log.info("Sermon Helper: made documents for %s (speaker %s)", audio.name, speaker)
        self.show(out_dir / f"{audio.stem}.summary.docx",
                  f"Done — the documents for {audio.name} are ready.{self.publish(audio)}")

    def publish(self, audio: Path) -> str:
        """Copy to the Google Drive folder; returns a line for the done message."""
        if publish_root(self.config) is None:
            return ""
        if publish(self.ledger, audio, self.config, log):
            return "\n\nThey're also in the shared Google Drive folder."
        error = (self.ledger.entry(audio) or {}).get("publish_error")
        if error:
            return (f"\n\nThey aren't in Google Drive yet ({error}). The automatic job "
                    f"will try again.")
        return ""

    def pick_speaker(self, default: str | None, sched: dict, notes: list[str],
                     was_confirmed: bool) -> str | None:
        if was_confirmed:
            source = f"Last confirmed here: {default}"
        elif default:
            source = f"From the preaching schedule: {default}"
        elif sched.get("speaker_raw"):
            source = (f"The preaching schedule says '{sched['speaker_raw']}', which isn't in "
                      f"speaker_initials.csv yet.")
        else:
            source = notes[0][0].upper() + notes[0][1:] + "." if notes else "Not in the preaching schedule."
        options = [default] if default else []
        options += [name for name in speaker_menu() if name != default] + [OTHER]
        picked = dlg.choose(f"Who preached?\n\n{source}", options, default or None)
        if picked == OTHER:
            picked = dlg.ask("Speaker's name, with title (e.g. Pastor Joel E. Wood):", "")
        return picked or None

    def show(self, path: Path, message: str):
        if dlg.buttons(message, ["OK", "Show in Finder"], "Show in Finder") == "Show in Finder":
            subprocess.run(["open", "-R", str(path)], check=False)

    def run(self):
        while True:
            self.ledger.reload()
            items = recent_recordings(self.ledger)
            if items:
                labels = [label for label, _ in items] + [CHOOSE_FILE]
                picked = dlg.choose("Pick a recording to fix or finish:\n"
                                    "⚠ needs a person   ✓ done   📝 transcript only",
                                    labels, labels[0])
                if picked is None:
                    return
                audio = dict(items).get(picked)
            else:
                picked = CHOOSE_FILE
                audio = None
            if picked == CHOOSE_FILE:
                audio = dlg.choose_file("Choose a sermon or Higher Ed recording:", self.watch_dir)
                if audio is None:
                    if not items:
                        return
                    continue

            self.handle(audio)
            if dlg.buttons("Anything else?", ["Done", "Another recording"], "Done") != "Another recording":
                return


def main():
    # Whisper runs "ffmpeg" by name: use the one in this Python's environment
    os.environ["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}"
    helper = Helper()
    setup_logging(helper.home)
    helper.run()


if __name__ == "__main__":
    main()
