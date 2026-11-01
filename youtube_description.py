"""
YouTube description: a pasteable video description with clickable chapters.

    RefCon 2026
    Host: New Life Presbyterian Church of La Mesa — https://www.newlifelamesa.org
    Reforming Holiness: The Fire of Glory
    Dr. Derek Rishmawy
    Session One: Reforming Our View of Spirituality

    <one-sentence summary>

    Chapters
    0:00 Welcome
    0:23 <first main point>
    ...

    <optional notes>

Each main outline point (I, II, III...) gets its start time from Whisper's
.srt segments, so the description needs the .srt that Whisper writes next to
the transcript. YouTube only turns description timestamps into chapters when
the first is 0:00, there are at least 3, they go up, and each chapter lasts at
least 10 seconds; check_chapters() enforces that before anything is written.

Timing options, for a video with an intro before the talk (e.g. title slides):
  timestamp_offset  seconds added to every Whisper time — use it when the
                    transcript is of the talk alone but the video has an intro
  intro_length      where the talk starts in the video (default: the offset).
                    Above 0, a 0:00 "Welcome" chapter covers the intro.

Written by run_pipeline.py for sermons, talks and classes (see --conference,
--session, --notes, --timestamp-offset, --intro-length there).
"""

import json
import re
import subprocess
import sys
from pathlib import Path

HOST_LINE = "Host: New Life Presbyterian Church of La Mesa — https://www.newlifelamesa.org"
MIN_CHAPTERS = 3
MIN_CHAPTER_SECONDS = 10
# More main points than this are combined, a run of points per chapter
MAX_CHAPTERS = 12
INTRO_TITLE = "Welcome"

# What Whisper writes during silence, music and applause, not what anyone said
_HALLUCINATIONS = {"thank you", "thank you very much", "thanks for watching", "you",
                   "bye", "amen", "music", "applause", "silence"}
_SRT_TIME = re.compile(r"(\d+):(\d\d):(\d\d)[,.](\d{3})")
# Unindented: an indented "C." or "I." is a lettered subpoint
_ROMAN = re.compile(r"^(?:#+\s*)?(?:\*\*)?\s*([IVXLC]+)\.\s+(.+?)\s*(?:\*\*)?\s*$")


class ChapterError(ValueError):
    pass


# ── Whisper segments ─────────────────────────────────────────────────────────

def _seconds(stamp: str) -> float:
    h, m, s, ms = map(int, _SRT_TIME.match(stamp.strip()).groups())
    return h * 3600 + m * 60 + s + ms / 1000


def parse_srt(text: str) -> list[dict]:
    """.srt text → [{start, end, text}] in seconds."""
    segments = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.strip().splitlines()
        timing = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing is None:
            continue
        start, end = lines[timing].split("-->")
        segments.append({"start": _seconds(start), "end": _seconds(end),
                         "text": " ".join(lines[timing + 1:]).strip()})
    return segments


def is_hallucination(text: str) -> bool:
    return re.sub(r"[^a-z ]", "", text.lower()).strip() in _HALLUCINATIONS


def speech_segments(segments: list[dict]) -> list[dict]:
    """The segments someone actually said: no "Thank you." in the silences,
    and no line Whisper repeats back to back (it loops in quiet stretches)."""
    kept = []
    for seg in segments:
        if not seg["text"] or is_hallucination(seg["text"]):
            continue
        if kept and seg["text"] == kept[-1]["text"]:
            continue
        kept.append(seg)
    return kept


def sentences(segments: list[dict], pause: float = 0.8, longest: float = 15) -> list[dict]:
    """Whisper sometimes writes a word or two per segment, unpunctuated. Join
    segments into sentence-sized lines (ending at . ? !, a pause, or `longest`
    seconds), so a chapter starts where a sentence does."""
    lines = []
    for seg in segments:
        last = lines[-1] if lines else None
        if (last and not re.search(r"[.?!][\"')\]]*$", last["text"])
                and seg["start"] - last["end"] < pause
                and seg["end"] - last["start"] <= longest):
            last["text"] += " " + seg["text"]
            last["end"] = seg["end"]
        else:
            lines.append(dict(seg))
    return lines


def talk_end(segments: list[dict], gap: float = 10, stray_words: int = 8,
             words_per_second: float = 1.0) -> float | None:
    """When the talk ends: the last segment's end, leaving out what follows a
    long silence if it's a few words or far slower than speech (2-3 words a
    second): Whisper's guesses at closing music."""
    if not segments:
        return None
    for i in range(len(segments) - 1, 0, -1):
        if segments[i]["start"] - segments[i - 1]["end"] >= gap:
            words = sum(len(s["text"].split()) for s in segments[i:])
            seconds = max(segments[-1]["end"] - segments[i]["start"], 1)
            if words <= stray_words or words / seconds < words_per_second:
                return segments[i - 1]["end"]
            break
    return segments[-1]["end"]


# ── Chapters ─────────────────────────────────────────────────────────────────

def format_time(seconds: float) -> str:
    """YouTube's form: 0:00, 12:05, 1:02:03."""
    s = int(seconds)
    h, m, s = s // 3600, s // 60 % 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def check_chapters(chapters: list[tuple[float, str]], duration: float | None = None):
    """Raise ChapterError unless YouTube will make chapters from these
    (seconds, title) pairs. Times are compared as written (whole seconds)."""
    problems = []
    if len(chapters) < MIN_CHAPTERS:
        problems.append(f"{len(chapters)} chapters; YouTube needs at least {MIN_CHAPTERS}")
    if chapters and int(chapters[0][0]) != 0:
        problems.append(f"the first chapter starts at {format_time(chapters[0][0])}, not 0:00")
    ends = [int(t) for t, _ in chapters[1:]] + ([int(duration)] if duration else [])
    for (start, title), end in zip(chapters, ends):
        if end <= int(start):
            problems.append(f"{format_time(end)} doesn't come after {format_time(start)}")
        elif end - int(start) < MIN_CHAPTER_SECONDS:
            problems.append(f"'{title}' at {format_time(start)} lasts {end - int(start)} s; "
                            f"YouTube needs {MIN_CHAPTER_SECONDS}")
    for _, title in chapters:
        if not title.strip():
            problems.append("a chapter has no title")
    if problems:
        raise ChapterError("; ".join(problems))


def roman(n: int) -> str:
    out = ""
    for value, letters in ((100, "C"), (90, "XC"), (50, "L"), (40, "XL"), (10, "X"),
                           (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while n >= value:
            out, n = out + letters, n - value
    return out


def main_points(outline_md: str) -> list[str]:
    """The main points of an outline, without their numerals: the lines that
    start I., II., III... in order (anything else is a subpoint or a stray)."""
    points = []
    for m in map(_ROMAN.match, outline_md.splitlines()):
        if m and m.group(1) == roman(len(points) + 1):
            points.append(m.group(2).strip("* "))
    return points


def build_chapters(starts: list[tuple[float, str]], intro_length: float = 0,
                   duration: float | None = None,
                   talk_end: float | None = None) -> list[tuple[float, str]]:
    """Outline points with video times → chapters YouTube accepts.

    The first point starts when the talk does (intro_length), with a
    Welcome chapter at 0:00 before it if there is an intro. A point that
    would start out of order, or within 10 s of the one before it or of the
    end, is merged into the one before. The end is when the talk ends
    (talk_end, the last speech) if that's before the video's end: a chapter
    of one sentence and the closing slides helps no one."""
    ends = [t for t in (duration, talk_end) if t]
    end = min(ends) if ends else None
    chapters = [(0.0, INTRO_TITLE)] if intro_length >= MIN_CHAPTER_SECONDS else []
    talk_start = float(intro_length) if chapters else 0.0
    for i, (start, title) in enumerate(starts):
        start = talk_start if i == 0 else start
        if chapters and int(start) - int(chapters[-1][0]) < MIN_CHAPTER_SECONDS:
            if i == 0:          # a too-short intro: the talk takes over 0:00
                chapters = []
                start = 0.0
            else:
                continue
        if end and int(end) - int(start) < MIN_CHAPTER_SECONDS:
            continue
        chapters.append((start, title))
    return chapters


def _json_list(reply: str) -> list:
    return json.loads(re.search(r"\[.*\]", reply, re.S).group(0))


def group_points(client, points: list[str],
                 max_chapters: int = MAX_CHAPTERS) -> list[tuple[str, int]]:
    """At most max_chapters (title, index of first point) pairs: the points
    themselves, or runs of consecutive points named for what they cover."""
    if len(points) <= max_chapters:
        return [(p, i) for i, p in enumerate(points)]
    from transcription_summary_core import call_llm
    system = (
        f"These are the {len(points)} main points of a talk's outline, in order. "
        f"Group consecutive points into at most {max_chapters} sections, the talk's "
        "main movements, for YouTube chapters. Every point belongs to exactly one "
        "section and sections keep the outline's order.\n"
        "Return only JSON: a list of objects {\"first\": <number of the section's "
        "first point>, \"title\": <a short chapter title for the section, at most 60 "
        "characters, no numbering>}."
    )
    try:
        found = _json_list(call_llm(client, system, "\n".join(
            f"{n}. {p}" for n, p in enumerate(points, 1))))
        firsts = [(int(x["first"]), str(x.get("title") or "").strip()) for x in found]
    except (ValueError, AttributeError, KeyError, TypeError):
        firsts = []
    if (firsts and firsts[0][0] == 1 and len(firsts) <= max_chapters
            and all(a[0] < b[0] <= len(points) for a, b in zip(firsts, firsts[1:]))):
        return [(title or points[n - 1], n - 1) for n, title in firsts]
    # The model's grouping didn't hold: even runs, named for their first point
    size = -(-len(points) // max_chapters)
    return [(points[i], i) for i in range(0, len(points), size)]


def locate_points(client, segments: list[dict], points: list[str],
                  max_chapters: int = MAX_CHAPTERS) -> list[tuple[float, str]]:
    """(video time, title) for each chapter: one per main point, or one per run
    of points when there are more than max_chapters, starting where the speaker
    begins it. segments are speech_segments() with times already in video time."""
    from transcription_summary_core import call_llm
    chapters = group_points(client, points, max_chapters)
    numbered = "\n".join(f"[{i}] {format_time(s['start'])} {s['text']}"
                         for i, s in enumerate(segments))
    system = (
        "You are given a talk's chapters, each with the outline points it covers, and "
        "a numbered transcript, one speech segment per line ([number] time text).\n"
        "For each chapter, find the segment where the speaker begins it (the "
        "transition into its first point, not a later mention).\n"
        "Return only JSON: a list of objects {\"chapter\": <chapter number>, "
        "\"segment\": <segment number>, \"title\": <a short YouTube chapter title, at "
        "most 60 characters, no numbering>}, one per chapter.\n"
        "Segment numbers must increase from chapter to chapter."
    )
    ends = [first for _, first in chapters[1:]] + [len(points)]
    listing = "\n".join(f"{n}. {title} (points: {'; '.join(points[first:end])})"
                        for n, ((title, first), end) in enumerate(zip(chapters, ends), 1))
    reply = call_llm(client, system, "CHAPTERS:\n" + listing + "\n\nTRANSCRIPT:\n" + numbered)

    starts = []
    for item in sorted(_json_list(reply), key=lambda x: int(x["chapter"])):
        n, seg = int(item["chapter"]), int(item["segment"])
        if not (1 <= n <= len(chapters) and 0 <= seg < len(segments)):
            continue
        title = (item.get("title") or chapters[n - 1][0]).strip()
        starts.append((segments[seg]["start"], title))
    # Keep only chapters in time order (a later one placed earlier is a miss)
    ordered = []
    for start, title in starts:
        if not ordered or start > ordered[-1][0]:
            ordered.append((start, title))
    return ordered[:max_chapters]


# ── Description ──────────────────────────────────────────────────────────────

def one_sentence_summary(client, summary_md: str, kind: str = "talk") -> str:
    from transcription_summary_core import call_llm
    system = ("Write one sentence (at most 40 words) for a YouTube video description, "
              f"saying what this {kind} is about. Call it a {kind}. Plain text, no quotation marks, no hype.")
    return call_llm(client, system, summary_md[:8000]).strip().strip('"')


def build_description(*, summary: str, chapters: list[tuple[float, str]] | None,
                      event: str = None, conference: str = None, speaker: str = None,
                      session: str = None, title: str = None, notes: str = None,
                      host_line: str = HOST_LINE) -> str:
    heading = ": ".join(x for x in (session, title) if x)
    lines = [x for x in (event, host_line, conference, speaker, heading) if x]
    text = "\n".join(lines) + "\n\n" + summary.strip() + "\n"
    if chapters:
        text += "\nChapters\n" + "\n".join(f"{format_time(t)} {name}"
                                           for t, name in chapters) + "\n"
    if notes and notes.strip():
        text += "\n" + notes.strip() + "\n"
    return text


def media_duration(path: Path) -> float | None:
    """A recording's length in seconds, from ffmpeg's header read (no decoding)."""
    try:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        ffmpeg = "ffmpeg"
    try:
        out = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)],
                             capture_output=True, text=True).stderr
    except OSError:
        return None
    m = re.search(r"Duration:\s*(\d+):(\d\d):(\d\d(?:\.\d+)?)", out)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None


def write_youtube_description(client, base: Path, srt_path: Path, outline_md: str,
                              summary_md: str, overwrite: bool, **fields) -> Path | None:
    """<base>.youtube.txt. fields: speaker, event, title, conference, session,
    notes, kind ("sermon" or "talk"), timestamp_offset, intro_length, duration.
    Without a usable .srt or valid chapters, the description is still written,
    without chapters, and the reason printed. It's the last output and an
    extra: a failure here is printed, not raised, so it never fails a run whose
    other documents are already written."""
    try:
        return _write_youtube_description(client, base, srt_path, outline_md, summary_md,
                                          overwrite, **fields)
    except Exception as e:
        print(f"  WARNING: no YouTube description — {e}", file=sys.stderr)
        return None


def _write_youtube_description(client, base, srt_path, outline_md, summary_md, overwrite, *,
                               speaker=None, event=None, title=None, conference=None,
                               session=None, notes=None, kind="talk", timestamp_offset=0,
                               intro_length=None, duration=None):
    from transcription_summary_core import write_text
    path = base.with_suffix(".youtube.txt")
    if path.exists() and not overwrite:
        print(f"SKIP (exists): {path}")
        return path
    timestamp_offset = timestamp_offset or 0
    intro_length = timestamp_offset if intro_length is None else intro_length

    chapters = None
    points = main_points(outline_md)
    if not srt_path.exists():
        print(f"  YouTube: no {srt_path.name}, so no chapters")
    elif not points:
        print("  YouTube: the outline has no Roman-numeral points, so no chapters")
    else:
        segments = sentences(speech_segments(parse_srt(srt_path.read_text(encoding="utf-8"))))
        for seg in segments:
            seg["start"] += timestamp_offset
            seg["end"] += timestamp_offset
        end_of_talk = talk_end(segments)
        duration = duration or end_of_talk
        try:
            chapters = build_chapters(locate_points(client, segments, points),
                                      intro_length, duration, end_of_talk)
            check_chapters(chapters, duration)
        except (ChapterError, ValueError, AttributeError, KeyError, TypeError) as e:
            print(f"  WARNING: YouTube chapters left out — {e}", file=sys.stderr)
            chapters = None

    description = build_description(summary=one_sentence_summary(client, summary_md, kind),
                                    chapters=chapters, event=event, conference=conference,
                                    speaker=speaker, session=session, title=title, notes=notes)
    write_text(path, description, overwrite=True)
    return path
