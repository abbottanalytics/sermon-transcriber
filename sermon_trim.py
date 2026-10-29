#!/usr/bin/env python3
"""
Cut a worship service's audio down to the sermon.

Where the sermon starts and ends comes from YouTube's captions (free, and
already there for a past livestream), so the whole service needn't be
transcribed first. The model reads them and suggests the cut points, which a
person confirms in youtube_sermon.py. The cut matches the AV team's own
recordings: from the preacher announcing and reading the sermon text, to the
end of the prayer after the sermon (and the Lord's Prayer when it follows).

USAGE:
    python3 sermon_trim.py suggest captions.vtt          # print the suggested times
    python3 sermon_trim.py cut service.m4a out.mp3 29:08 1:07:08
"""

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from transcription_summary_core import call_llm

# Captions are condensed to numbered lines about this long. The model picks
# lines, and the cut keeps one more line on each side: a few seconds of hymn
# announcement don't matter, a clipped Scripture reading or Amen would.
LINE_SECONDS = 10
END_PAD = 8                 # line times are when words first show: the last ones run on

FIND_SERMON = """You are given the auto-captions of a recorded church worship service, one line per ~10 seconds, each starting with a line number and [h:mm:ss].
Find the sermon so the audio can be cut to just the sermon.
- start_line: the line where the preacher announces or begins reading the sermon's Scripture text (include the reading, and any remarks the preacher makes between the reading and the sermon). Not earlier readings, the call to worship, confession, announcements or hymns.
- last_line: the last line of the prayer that closes the sermon. That prayer often leads straight into the congregation praying the Lord's Prayer together; include it. The sermon never includes the hymn after it, the creed, the Lord's Supper, the offering, the closing announcements or the benediction.
- If there's no sermon in the captions, give confidence "none".
Return JSON only: {"start_line": N, "last_line": N, "confidence": "high|medium|low|none", "note": "one short sentence on where the sermon starts and ends"}"""


@dataclass
class Suggestion:
    start: float
    end: float
    confidence: str
    note: str
    lines: list                 # the captions, for words_at()

    def words_at(self, seconds: float, before: bool = False, count: int = 14) -> str:
        """The captions' own words just after (or before) a time, to show a
        person where a cut falls."""
        return words_at(self.lines, seconds, before, count)


# ── Times ─────────────────────────────────────────────────────────────────────

def parse_time(value: str) -> float:
    """'1:07:08', '67:08' or '4028' → seconds."""
    parts = value.strip().split(":")
    if not 1 <= len(parts) <= 3 or not all(re.fullmatch(r"\d+(\.\d+)?", p) for p in parts):
        raise ValueError(f"{value!r} isn't a time like 1:07:08 or 38:20")
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + float(part)
    return seconds


def format_time(seconds: float) -> str:
    """Seconds → '1:07:08' or '29:08', as YouTube shows it."""
    s = int(round(seconds))
    h, m, s = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# ── Captions ──────────────────────────────────────────────────────────────────

def caption_lines(vtt: str) -> list[tuple[float, str]]:
    """Each new line of caption text with the time it first appears.
    Automatic captions roll: each cue repeats the line before it."""
    lines, last = [], ""
    for h, m, s, ms, body in re.findall(
            r"(\d+):(\d\d):(\d\d)\.(\d+) --> [^\n]*\n(.*?)(?:\n\n|\Z)", vtt, re.S):
        t = int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
        for line in body.splitlines():
            line = re.sub(r"<[^>]+>", "", line).replace("&gt;", ">").replace("&amp;", "&").strip()
            if line and line != last:
                lines.append((t, line))
                last = line
    return lines


def condense(lines: list[tuple[float, str]], every: int = LINE_SECONDS) -> list[tuple[float, str]]:
    """Caption lines joined into (start time, words) about every `every`
    seconds: about 550 lines and 10,000 words for a 90-minute service."""
    out, start, words = [], None, []
    for t, line in lines:
        if start is None:
            start = t
        words.append(line)
        if t - start >= every:
            out.append((start, " ".join(words)))
            start, words = None, []
    if words:
        out.append((start, " ".join(words)))
    return out


def _hms(t: float) -> str:
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}"


def words_at(lines, seconds: float, before: bool = False, count: int = 14) -> str:
    if before:
        text = " ".join(l for t, l in lines if seconds - 40 <= t < seconds)
        words = text.split()[-count:]
        return ("…" if words else "") + " ".join(words)
    text = " ".join(l for t, l in lines if seconds <= t < seconds + 40)
    words = text.split()[:count]
    return " ".join(words) + ("…" if words else "")


def suggest(client, vtt_text: str) -> Suggestion | None:
    """The model's start and end of the sermon, or None if it found none."""
    lines = caption_lines(vtt_text)
    chunks = condense(lines)
    if not chunks:
        return None
    numbered = "\n".join(f"{i} [{_hms(t)}] {text}" for i, (t, text) in enumerate(chunks, start=1))
    reply = call_llm(client, FIND_SERMON, numbered).strip()
    reply = re.sub(r"^```(?:json)?|```$", "", reply, flags=re.M).strip()
    try:
        d = json.loads(reply)
        if d.get("confidence") == "none":
            return None
        first, last = int(d["start_line"]), int(d["last_line"])
    except (ValueError, KeyError, TypeError):
        print(f"  Couldn't read the suggested times: {reply[:300]!r}", file=sys.stderr)
        return None
    if not 1 <= first <= last <= len(chunks):
        return None
    # From the line before the start, to the end of the line after the last
    start = chunks[max(first - 2, 0)][0]
    end = (chunks[last + 1][0] if last + 1 < len(chunks) else lines[-1][0]) + END_PAD
    return Suggestion(start, end, d.get("confidence", "low"), d.get("note", ""), lines)


# ── Cutting ───────────────────────────────────────────────────────────────────

def cut(source: Path, dest: Path, start: float, end: float):
    """source[start:end] → dest .mp3, written beside it first so a folder
    being watched never sees half a file."""
    import imageio_ffmpeg
    partial = dest.with_name(f".{dest.stem}.partial.mp3")
    result = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
         "-ss", f"{start:.2f}", "-to", f"{end:.2f}", "-i", str(source),
         "-vn", "-c:a", "libmp3lame", "-b:a", "128k", str(partial)],
        capture_output=True, text=True)
    if result.returncode != 0:
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg couldn't cut the audio: {result.stderr.strip()}")
    partial.replace(dest)


def main():
    import os
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == "suggest":
        from openai import OpenAI
        from app_home import read_config
        key = os.getenv("OPENAI_API_KEY") or read_config().get("api_key", "")
        s = suggest(OpenAI(api_key=key), Path(args[1]).read_text(encoding="utf-8"))
        if s is None:
            sys.exit("No sermon found in the captions.")
        print(f"{format_time(s.start)} → {format_time(s.end)}  ({(s.end - s.start) / 60:.0f} min, "
              f"{s.confidence})\n  starts: {s.words_at(s.start)}\n  ends:   {s.words_at(s.end, before=True)}\n  {s.note}")
    elif len(args) == 5 and args[0] == "cut":
        cut(Path(args[1]), Path(args[2]), parse_time(args[3]), parse_time(args[4]))
        print(f"Saved {args[2]}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
