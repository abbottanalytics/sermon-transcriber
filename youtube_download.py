#!/usr/bin/env python3
"""
Download from YouTube with yt-dlp: a church service from its playlist, or any
video or playlist link.

yt-dlp is not pinned with the rest of the code: YouTube changes often enough
that a copy a few weeks old can stop working. Each run uses the newest yt-dlp
through uv (cached after the first download), with Deno for YouTube's
JavaScript and this environment's bundled ffmpeg, so nothing else needs to be
installed.

The worship playlists are New Life's, unless config.txt sets others:

    youtube_morning=https://www.youtube.com/playlist?list=...
    youtube_evening=https://www.youtube.com/playlist?list=...

Downloads go in youtube_dir from config.txt (default ~/Downloads/YouTube).

USAGE:
    python3 youtube_download.py                      # Mac dialogs ("Download from YouTube.command")
    python3 youtube_download.py find AM 10/25/26     # that Sunday's morning service
    python3 youtube_download.py get <link> [--video] [--days 7 | --newest 1] [--to DIR]
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

# The service code in a recording name → its playlist setting in config.txt
PLAYLIST_SETTINGS = {"AM": "youtube_morning", "PM": "youtube_evening"}
DEFAULT_PLAYLISTS = {
    "youtube_morning": "https://www.youtube.com/playlist?list=PLlG-TnDpO3fET94b3KlXusxYABfldSEVQ",
    "youtube_evening": "https://www.youtube.com/playlist?list=PLlG-TnDpO3fFPxzt-OuaC9-Hv_vLOLgT_",
}
SERVICE_NAMES = {"AM": "Morning Worship", "PM": "Evening Worship"}
SEARCH_DEPTH = 40           # newest videos in a playlist searched for a date
# "Morning Worship Service: 25-October-2026; ..." — the church's title format
TITLE_DATE = re.compile(r"(\d{1,2})[- ]([A-Za-z]+)[-, ]+(\d{4})")


class YouTubeError(RuntimeError):
    pass


@dataclass
class Video:
    id: str
    title: str
    duration: int | None = None

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.id}"

    def url_at(self, seconds: float) -> str:
        return f"{self.url}&t={int(seconds)}s"


# ── Running yt-dlp ────────────────────────────────────────────────────────────

def find_uv() -> str:
    """uv as installed by install.sh (same search as update.sh)."""
    for candidate in (shutil.which("uv"),
                      os.path.join(os.getenv("UV_INSTALL_DIR", ""), "uv"),
                      os.path.expanduser("~/.local/bin/uv")):
        if candidate and os.access(candidate, os.X_OK):
            return candidate
    raise YouTubeError("uv isn't installed — run update.command first.")


def ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def yt_dlp(*args: str, show: bool = False) -> str:
    """Run the newest yt-dlp; returns what it printed. With show, its
    progress goes to the Terminal window instead."""
    cmd = [find_uv(), "tool", "run", "--quiet", "--python", "3.12",
           "--from", "yt-dlp[default]@latest", "--with", "deno",
           "yt-dlp", "--ffmpeg-location", ffmpeg(), "--no-warnings", *args]
    # uv's own Python, as for the rest of the code (see update.sh)
    env = {**os.environ, "UV_PYTHON_PREFERENCE": "only-managed"}
    result = subprocess.run(cmd, stdout=None if show else subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, env=env)
    if result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()
        message = detail[-1].removeprefix("ERROR: ") if detail else f"yt-dlp failed ({result.returncode})"
        raise YouTubeError(message)
    return result.stdout or ""


def fetch(*args: str) -> list[Path]:
    """Download with progress showing; the files it saved (or already had)."""
    with tempfile.TemporaryDirectory() as tmp:
        saved = Path(tmp) / "saved.txt"
        yt_dlp(*args, "--newline", "--print-to-file", "after_move:filepath", str(saved), show=True)
        lines = saved.read_text(encoding="utf-8").splitlines() if saved.exists() else []
    return [Path(line) for line in lines if line.strip()]


# ── Finding a service ─────────────────────────────────────────────────────────

def title_date(title: str) -> date | None:
    m = TITLE_DATE.search(title)
    if not m:
        return None
    try:
        return datetime.strptime(" ".join(m.groups()), "%d %B %Y").date()
    except ValueError:
        try:
            return datetime.strptime(" ".join(m.groups()), "%d %b %Y").date()
        except ValueError:
            return None


def playlist_videos(url: str, limit: int = SEARCH_DEPTH) -> list[Video]:
    """The playlist's videos, in its own order (newest first for the church's)."""
    out = yt_dlp("--flat-playlist", "--playlist-end", str(limit),
                 "--print", "%(.{id,title,duration})j", url)
    videos = []
    for line in out.splitlines():
        if line.strip():
            d = json.loads(line)
            videos.append(Video(d["id"], d.get("title") or "", d.get("duration")))
    return videos


def video_info(url: str) -> Video:
    """One video's id, title and length (just the video, for a link in a playlist)."""
    out = yt_dlp("--skip-download", "--no-playlist", "--print", "%(.{id,title,duration})j", url)
    d = json.loads(out.strip().splitlines()[-1])
    return Video(d["id"], d.get("title") or "", d.get("duration"))


def playlist_url(service: str, config: dict) -> str:
    setting = PLAYLIST_SETTINGS.get(service)
    if not setting:
        raise YouTubeError(f"There's no YouTube playlist for {service} services.")
    return config.get(setting, "").strip() or DEFAULT_PLAYLISTS[setting]


def find_service(service: str, when: date, config: dict) -> Video | None:
    """That date's video in the service's playlist, by the date in its title."""
    for video in playlist_videos(playlist_url(service, config)):
        if title_date(video.title) == when:
            return video
    return None


def last_sunday(today: date | None = None) -> date:
    today = today or date.today()
    return today - timedelta(days=(today.weekday() + 1) % 7)


# ── Downloading ───────────────────────────────────────────────────────────────

def download_audio(video: Video, folder: Path) -> Path:
    """The video's best audio track as .m4a (no re-encoding)."""
    folder.mkdir(parents=True, exist_ok=True)
    saved = fetch("-f", "bestaudio[ext=m4a]/bestaudio", "-x", "--audio-format", "m4a",
                  "--no-playlist", "-o", str(folder / f"{video.id}.%(ext)s"), video.url)
    if not saved:
        raise YouTubeError("the download finished without saving a file")
    return saved[-1]


def download_captions(video: Video, folder: Path) -> Path | None:
    """YouTube's English captions (its own, else automatic) as .vtt, or None."""
    folder.mkdir(parents=True, exist_ok=True)
    for kind in ("--write-subs", "--write-auto-subs"):
        yt_dlp("--skip-download", kind, "--sub-langs", "en,en-US,en-orig", "--sub-format", "vtt",
               "--no-playlist", "-o", str(folder / f"{video.id}.%(ext)s"), video.url)
        found = sorted(folder.glob(f"{video.id}*.vtt"))
        if found:
            return found[0]
    return None


def is_playlist(url: str) -> bool:
    """A playlist or channel link, rather than one video (which may be in a playlist)."""
    return "watch?v=" not in url and "youtu.be/" not in url and "/shorts/" not in url


def download(url: str, folder: Path, video: bool = False, days: int | None = None,
             newest: int | None = None) -> list[Path]:
    """Any link: one video, or a playlist's videos (only its newest few, or
    those from the last `days` days, if given). Files are named after the
    video's title; one already there is skipped."""
    folder.mkdir(parents=True, exist_ok=True)
    args = (["-f", "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720]/b",
             "--merge-output-format", "mp4"] if video else
            ["-f", "bestaudio[ext=m4a]/bestaudio", "-x", "--audio-format", "m4a"])
    if not is_playlist(url):
        args += ["--no-playlist"]
    elif days:
        args += ["--dateafter", f"now-{days}days", "--break-on-reject"]
    elif newest:
        args += ["--playlist-end", str(newest)]
    return fetch(*args, "--no-overwrites", "-o", str(folder / "%(title).150B.%(ext)s"), url)


def download_folder(config: dict) -> Path:
    return Path(config.get("youtube_dir") or "~/Downloads/YouTube").expanduser()


def dialogs():
    """Paste a link, pick audio or video: the Senior Pastor's download."""
    import mac_dialogs as dlg
    from app_home import read_config
    dlg.TITLE = "Download from YouTube"
    folder = download_folder(read_config())
    url = dlg.ask("Paste a YouTube link (a video, or a playlist or channel):")
    if not url:
        return
    kind = dlg.buttons("Download the audio or the video?\n\nAudio (.m4a) is much smaller and "
                       "is all that's needed for a transcript. Video is .mp4, up to 720p.",
                       ["Cancel", "Video", "Audio"], "Audio")
    if kind is None:
        return
    days = newest = None
    if is_playlist(url):
        how = dlg.choose("That's a playlist or channel. Which videos?",
                         ["The newest one", "The last 7 days", "The last 30 days"], "The newest one")
        if how is None:
            return
        if how == "The newest one":
            newest = 1
        else:
            days = 7 if "7" in how else 30
    print(f"Downloading to {folder}...")
    try:
        saved = download(url.strip(), folder, video=(kind == "Video"), days=days, newest=newest)
    except YouTubeError as e:
        dlg.info(f"The download didn't work:\n\n{e}\n\nCheck the link, or try again in a few minutes.")
        return
    if not saved:
        dlg.info(f"Nothing new to download: it's already in {folder}, or the playlist has "
                 f"nothing that recent.")
        return
    names = "\n".join(p.name for p in saved[:8]) + (f"\n…and {len(saved) - 8} more" if len(saved) > 8 else "")
    if dlg.buttons(f"In {folder}:\n\n{names}", ["OK", "Show in Finder"], "Show in Finder") == "Show in Finder":
        subprocess.run(["open", "-R", str(saved[0])], check=False)


def _parse_date(value: str) -> date:
    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%m%d%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(f"{value!r} isn't a date like 10/25/26")


def main():
    from app_home import read_config
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    f = sub.add_parser("find", help="find a service's video in its playlist")
    f.add_argument("service", choices=sorted(PLAYLIST_SETTINGS))
    f.add_argument("date", nargs="?", type=_parse_date, help="default: last Sunday")
    g = sub.add_parser("get", help="download a video or playlist")
    g.add_argument("url")
    g.add_argument("--video", action="store_true", help="video (720p mp4) instead of audio")
    g.add_argument("--days", type=int, help="for a playlist: only the last N days")
    g.add_argument("--newest", type=int, help="for a playlist: only its newest N videos")
    g.add_argument("--to", type=Path, help="folder (default: youtube_dir in config.txt)")
    args = ap.parse_args()
    if args.cmd is None:
        return dialogs()
    try:
        if args.cmd == "find":
            when = args.date or last_sunday()
            found = find_service(args.service, when, read_config())
            print(f"{found.title}\n{found.url}" if found else
                  f"No {SERVICE_NAMES[args.service]} video for {when:%-m/%-d/%y}.")
        else:
            folder = args.to.expanduser() if args.to else download_folder(read_config())
            for path in download(args.url, folder, args.video, args.days, args.newest):
                print(f"Saved {path}")
    except YouTubeError as e:
        sys.exit(f"ERROR: {e}")


if __name__ == "__main__":
    main()
