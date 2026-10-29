#!/usr/bin/env python3
"""
Sermon from YouTube — when a service wasn't recorded on the AV Mac, take the
sermon from the church's YouTube livestream instead.

Double-click "Sermon from YouTube.command". Plain Mac dialogs ask:

    Service     Morning or Evening Worship
    Sunday      last Sunday unless changed

It finds that Sunday's video in the service's playlist, downloads its audio,
and suggests where the sermon starts and ends (from YouTube's captions: see
sermon_trim.py). Once the times are confirmed, the sermon is saved in the
Sermons folder with the usual name (e.g. 102526AM.mp3), just like an
Audacity export. From there it's an ordinary recording: documents are made
now, through Sermon Helper's questions, or at the next automatic check.

For any other video, e.g. a special event's livestream:

    python3 youtube_sermon.py --url <link> --name 110726RC2

Test mode: see mac_dialogs.py (SERMON_HELPER_ANSWERS).
"""

import argparse
import os
import shutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import mac_dialogs as dlg
from app_home import ensure, read_config
from recording_names import parse_recording_name
from sermon_trim import format_time, parse_time, suggest, words_at, caption_lines, cut
from youtube_download import (SERVICE_NAMES, Video, YouTubeError, download_audio,
                              download_captions, find_service, last_sunday, video_info)

dlg.TITLE = "Sermon from YouTube"
SERVICES = {f"{name} ({code})": code for code, name in SERVICE_NAMES.items()}
USE, CHANGE, WATCH = "Use these times", "Change times", "Watch on YouTube"
NOW, LATER = "Make documents now", "Leave for the automatic check"


def _date(value: str) -> date | None:
    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%m%d%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _minutes(seconds: float) -> str:
    return f"{round(seconds / 60)} minutes"


class SermonFromYouTube:
    def __init__(self):
        self.home = ensure()
        self.config = read_config()
        watch = self.config.get("watch_dir") or self.config.get("input_dir") or ""
        self.watch_dir = Path(watch).expanduser() if watch else None
        self.work = self.home / "youtube"
        self._client = None

    def client(self):
        if self._client is None:
            api_key = os.getenv("OPENAI_API_KEY") or self.config.get("api_key", "")
            if api_key:
                from openai import OpenAI
                os.environ["OPENAI_API_KEY"] = api_key
                self._client = OpenAI(api_key=api_key)
        return self._client

    def folder_for(self, when: date) -> Path:
        """Where an Audacity export of that Sunday would go."""
        if self.watch_dir:
            return self.watch_dir / str(when.year)
        return Path.home() / "Downloads"

    # ── Which video ───────────────────────────────────────────────────────

    def pick(self) -> tuple[Video, str] | None:
        """Ask for the service and Sunday; the video and recording name."""
        choice = dlg.choose("Which service wasn't recorded?", list(SERVICES), list(SERVICES)[0])
        if choice is None:
            return None
        service = SERVICES[choice]
        default = last_sunday()
        while True:
            typed = dlg.ask("Which Sunday? (month/day/year)", f"{default:%-m/%-d/%y}")
            if typed is None:
                return None
            when = _date(typed)
            if when:
                break
            dlg.info(f"“{typed}” isn't a date like {default:%-m/%-d/%y}.")

        print(f"Looking for the {SERVICE_NAMES[service]} video for {when:%-m/%-d/%y}...")
        video = find_service(service, when, self.config)
        if video is None:
            dlg.info(f"There's no {SERVICE_NAMES[service]} video for {when:%A %-m/%-d/%y} "
                     f"in the YouTube playlist yet.\n\nA livestream can take a while to show "
                     f"up after the service ends. Try again later, or ask Dean.")
            return None
        return video, f"{when:%m%d%y}{service}"

    # ── Where the sermon is ───────────────────────────────────────────────

    def times(self, video: Video, captions: Path | None) -> tuple[float, float] | None:
        """Suggested start and end, confirmed or changed by a person."""
        lines = caption_lines(captions.read_text(encoding="utf-8")) if captions else []
        start = end = None
        if lines and self.client():
            print("Finding the sermon in YouTube's captions...")
            found = suggest(self.client(), captions.read_text(encoding="utf-8"))
            if found:
                start, end = found.start, found.end
        if start is None:
            why = ("YouTube doesn't have captions for this video yet" if not lines else
                   "the sermon couldn't be found in YouTube's captions")
            go = dlg.buttons(f"{video.title}\n\nThe sermon's start and end have to be typed in: "
                             f"{why}. Watch the video to find where the sermon text is "
                             f"announced and where the prayer after the sermon ends.",
                             ["Cancel", WATCH, "Type the times"], WATCH)
            if go is None:
                return None
            if go == WATCH:
                subprocess.run(["open", video.url], check=False)
            return self.type_times(video, 0, video.duration or 0)

        while True:
            shown = (f"\n\nStarts: {words_at(lines, start)}\n\nEnds: {words_at(lines, end, before=True)}"
                     if lines else "")
            picked = dlg.buttons(
                f"{video.title}\n\nThe sermon looks like it runs from {format_time(start)} "
                f"to {format_time(end)} ({_minutes(end - start)}).{shown}\n\n"
                f"“{WATCH}” opens the video at the start, to check.",
                [WATCH, CHANGE, USE], USE)
            if picked == USE:
                return start, end
            if picked == WATCH:
                subprocess.run(["open", video.url_at(start)], check=False)
                continue
            changed = self.type_times(video, start, end)
            if changed is None:
                return None
            start, end = changed

    def type_times(self, video: Video, start: float, end: float) -> tuple[float, float] | None:
        while True:
            a = dlg.ask("Where does the sermon start? (hours:minutes:seconds, as YouTube shows "
                        "it, e.g. 29:08 or 1:02:30)", format_time(start) if start else "")
            if a is None:
                return None
            b = dlg.ask("Where does it end?", format_time(end) if end else "")
            if b is None:
                return None
            try:
                new_start, new_end = parse_time(a), parse_time(b)
            except ValueError as e:
                dlg.info(str(e))
                continue
            if new_end <= new_start:
                dlg.info("The end has to be after the start.")
            elif video.duration and new_end > video.duration + 1:
                dlg.info(f"The video is only {format_time(video.duration)} long.")
            else:
                return new_start, new_end

    # ── The whole flow ────────────────────────────────────────────────────

    def run(self, video: Video | None = None, name: str | None = None, folder: Path | None = None):
        if video is None:
            picked = self.pick()
            if picked is None:
                return
            video, name = picked
        rec = parse_recording_name(name)
        folder = folder or self.folder_for(rec.date if rec else date.today())
        dest = folder / f"{name}.mp3"
        existing = sorted(folder.glob(f"{name}*.*")) if folder.is_dir() else []
        existing = [p for p in existing if p.suffix.lower() in (".mp3", ".m4a", ".wav", ".aif", ".aiff")]
        if existing:
            if dlg.buttons(f"{existing[0].name} is already in {folder}.\n\nReplace it with the "
                           f"sermon from YouTube?", ["Cancel", "Replace"], "Cancel") is None:
                return
        elif dlg.buttons(f"Found it:\n\n{video.title}\n\nDownload its audio? This takes a "
                         f"minute or two.", ["Cancel", "Download"], "Download") is None:
            return

        work = self.work / video.id
        try:
            print(f"Downloading the audio of {video.title}...")
            audio = download_audio(video, work)
            captions = download_captions(video, work)
            span = self.times(video, captions)
            if span is None:
                return
            print(f"Saving the sermon ({format_time(span[0])} to {format_time(span[1])}) "
                  f"as {dest.name}...")
            folder.mkdir(parents=True, exist_ok=True)
            for old in existing:
                old.unlink()
            cut(audio, dest, *span)
        except YouTubeError as e:
            dlg.info(f"Couldn't get the video from YouTube:\n\n{e}\n\nTry again in a few "
                     f"minutes; if it keeps failing, ask Dean.")
            return
        finally:
            shutil.rmtree(work, ignore_errors=True)

        self.after(dest, rec)

    def after(self, dest: Path, rec):
        """Make the documents now, or leave the file for the automatic check."""
        where = f"in the Sermons folder ({dest.parent})" if self.watch_dir else f"in {dest.parent}"
        options = [NOW] if not self.watch_dir or rec is None else [LATER, NOW]
        picked = dlg.buttons(f"Saved the sermon as {dest.name} {where}.\n\n"
                             f"Its documents can be made now (in this window — transcription "
                             f"takes up to an hour on an older Mac)"
                             + (", or at the next automatic check (Sundays 1, 7 and 11 pm)."
                                if len(options) == 2 else "."),
                             ["Cancel", *options], NOW)
        if picked == NOW:
            from auto_transcribe import setup_logging
            from sermon_helper import Helper
            helper = Helper()
            setup_logging(helper.home)
            dlg.TITLE = "Sermon Helper"
            helper.sermon(dest, rec, helper.ledger.entry(dest) or {})


def main():
    # Whisper runs "ffmpeg" by name: use the one in this Python's environment
    os.environ["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}"
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", help="a video link, instead of choosing a service")
    ap.add_argument("--name", help="recording name for --url, e.g. 110726RC2")
    ap.add_argument("--to", type=Path, help="folder to save in (default: the Sermons folder)")
    args = ap.parse_args()
    if bool(args.url) != bool(args.name):
        ap.error("--url and --name go together")

    app = SermonFromYouTube()
    if args.url:
        if parse_recording_name(args.name) is None:
            sys.exit(f"ERROR: {args.name} isn't a recording name the automatic job knows: "
                     f"MMDDYY plus AM/PM, or a code listed for that date in special_events.csv.")
        try:
            video = video_info(args.url)
        except YouTubeError as e:
            sys.exit(f"ERROR: couldn't read {args.url}: {e}")
        app.run(video, args.name, args.to.expanduser() if args.to else None)
    else:
        try:
            app.run(folder=args.to.expanduser() if args.to else None)
        except YouTubeError as e:
            dlg.info(f"Couldn't reach YouTube:\n\n{e}")


if __name__ == "__main__":
    main()
