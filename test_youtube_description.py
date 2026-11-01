#!/usr/bin/env python3
"""Checks for youtube_description.py that need no API key or recordings.

    python3 -m unittest test_youtube_description
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import youtube_description as yd
from special_events import parse

SRT = """1
00:00:00,000 --> 00:00:04,000
Thank you.

2
00:00:04,000 --> 00:00:08,000
Thank you.

3
00:00:08,500 --> 00:00:15,000
Good evening, it's a joy to be here.

4
00:05:00,000 --> 00:05:10,000
So first, what is holiness?

5
00:20:00,000 --> 00:20:12,000
Second, holiness and glory.

6
00:20:12,000 --> 00:20:20,000
Second, holiness and glory.

7
00:35:00,000 --> 00:35:30,000
Finally, the fire of glory in the church.

8
00:40:00,000 --> 00:40:05,000
Thank you very much!
"""

OUTLINE = """# Outline
I. Introduction and Greeting
   A. Thanks to the host
   B. Stories
   C. Purpose of the series
II. **What Is Holiness?**
## III. Holiness and Glory
- not a point
VI. Out of order, not a main point
IV. The Fire of Glory in the Church
"""


class Times(unittest.TestCase):
    def test_format(self):
        self.assertEqual(yd.format_time(0), "0:00")
        self.assertEqual(yd.format_time(23.9), "0:23")
        self.assertEqual(yd.format_time(725), "12:05")
        self.assertEqual(yd.format_time(3723), "1:02:03")

    def test_parse_srt(self):
        segs = yd.parse_srt(SRT)
        self.assertEqual(len(segs), 8)
        self.assertEqual(segs[3], {"start": 300.0, "end": 310.0,
                                   "text": "So first, what is holiness?"})

    def test_speech_segments_drop_hallucinations_and_repeats(self):
        texts = [s["text"] for s in yd.speech_segments(yd.parse_srt(SRT))]
        self.assertEqual(texts, ["Good evening, it's a joy to be here.",
                                 "So first, what is holiness?",
                                 "Second, holiness and glory.",
                                 "Finally, the fire of glory in the church."])


class Rules(unittest.TestCase):
    good = [(0, "Welcome"), (23, "I. A"), (300, "II. B"), (1200, "III. C")]

    def test_good(self):
        yd.check_chapters(self.good, duration=3051)

    def test_first_not_zero(self):
        with self.assertRaisesRegex(yd.ChapterError, "not 0:00"):
            yd.check_chapters(self.good[1:] + [(2000, "IV")])

    def test_too_few(self):
        with self.assertRaisesRegex(yd.ChapterError, "at least 3"):
            yd.check_chapters(self.good[:2])

    def test_not_ascending(self):
        with self.assertRaisesRegex(yd.ChapterError, "doesn't come after"):
            yd.check_chapters([(0, "a"), (300, "b"), (200, "c"), (400, "d")])

    def test_too_short(self):
        with self.assertRaisesRegex(yd.ChapterError, "lasts 9 s"):
            yd.check_chapters([(0, "a"), (100, "b"), (109, "c")])

    def test_last_chapter_too_short_for_video(self):
        with self.assertRaisesRegex(yd.ChapterError, "lasts 5 s"):
            yd.check_chapters(self.good, duration=1205)


class Building(unittest.TestCase):
    def test_main_points(self):
        self.assertEqual(yd.main_points(OUTLINE),
                         ["Introduction and Greeting", "What Is Holiness?",
                          "Holiness and Glory", "The Fire of Glory in the Church"])

    def test_roman(self):
        self.assertEqual([yd.roman(n) for n in (1, 4, 9, 14, 31, 49)],
                         ["I", "IV", "IX", "XIV", "XXXI", "XLIX"])

    def test_intro_chapter_and_talk_start(self):
        starts = [(31.5, "I. A"), (323, "II. B"), (1223, "III. C")]
        chapters = yd.build_chapters(starts, intro_length=23, duration=3051)
        self.assertEqual(chapters, [(0.0, "Welcome"), (23.0, "I. A"),
                                    (323, "II. B"), (1223, "III. C")])
        yd.check_chapters(chapters, 3051)

    def test_no_chapter_after_the_talk_ends(self):
        # Talk ends at 41:06, video (with closing slides) at 41:21
        chapters = yd.build_chapters([(0, "a"), (600, "b"), (1200, "c"), (2461, "end")],
                                     duration=2481, talk_end=2466)
        self.assertEqual([t for _, t in chapters], ["a", "b", "c"])

    def test_no_intro_first_point_at_zero(self):
        chapters = yd.build_chapters([(8.5, "I. A"), (300, "II. B"), (1200, "III. C")])
        self.assertEqual(chapters[0], (0.0, "I. A"))

    def test_close_points_merged(self):
        chapters = yd.build_chapters([(0, "I"), (300, "II"), (305, "III"), (900, "IV"),
                                      (3045, "V")], duration=3051)
        self.assertEqual([t for _, t in chapters], ["I", "II", "IV"])
        yd.check_chapters(chapters, 3051)

    def test_description_layout(self):
        text = yd.build_description(
            summary="A talk about holiness.", chapters=[(0, "Welcome"), (23, "I. A"),
                                                        (300, "II. B")],
            event="RefCon 2026", conference="Reforming Holiness: The Fire of Glory",
            speaker="Dr. Derek Rishmawy", session="Session One",
            title="Reforming Our View of Spirituality", notes="Audio note.")
        self.assertEqual(text, (
            "RefCon 2026\n" + yd.HOST_LINE + "\nReforming Holiness: The Fire of Glory\n"
            "Dr. Derek Rishmawy\nSession One: Reforming Our View of Spirituality\n\n"
            "A talk about holiness.\n\nChapters\n0:00 Welcome\n0:23 I. A\n"
            "5:00 II. B\n\nAudio note.\n"))

    def test_sermon_layout_skips_missing_fields(self):
        text = yd.build_description(summary="S.", chapters=None, event="Morning Worship",
                                    speaker="Pastor Joel Wood", title="Joshua 1")
        self.assertEqual(text, "Morning Worship\n" + yd.HOST_LINE +
                         "\nPastor Joel Wood\nJoshua 1\n\nS.\n")


class EndToEnd(unittest.TestCase):
    """write_youtube_description with the model calls faked."""

    def run_with(self, located, **kw):
        replies = iter([json.dumps(located), "A talk about holiness."])
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("transcription_summary_core.call_llm",
                           side_effect=lambda *a, **k: next(replies)):
            base = Path(tmp) / "talk"
            base.with_suffix(".srt").write_text(SRT, encoding="utf-8")
            yd.write_youtube_description(None, base, base.with_suffix(".srt"), OUTLINE,
                                         "summary", False, speaker="Dr. X",
                                         event="RefCon 2026", **kw)
            return base.with_suffix(".youtube.txt").read_text(encoding="utf-8")

    def test_offset(self):
        # Segments (after dropping "Thank you."): 0 greeting, 1 first, 2 second, 3 finally
        located = [{"chapter": 1, "segment": 0, "title": "Greeting"},
                   {"chapter": 2, "segment": 1, "title": "What Is Holiness?"},
                   {"chapter": 3, "segment": 2, "title": "Holiness and Glory"},
                   {"chapter": 4, "segment": 3, "title": "The Fire of Glory"}]
        text = self.run_with(located, timestamp_offset=23, duration=2450)
        self.assertIn("Chapters\n0:00 Welcome\n0:23 Greeting\n5:23 What Is "
                      "Holiness?\n20:23 Holiness and Glory\n35:23 The Fire of Glory\n",
                      text)

    def test_many_points_are_grouped(self):
        replies = iter([json.dumps([{"first": 1, "title": "A"}, {"first": 9, "title": "B"}]),
                        json.dumps([{"chapter": 1, "segment": 0, "title": "A"},
                                    {"chapter": 2, "segment": 2, "title": "B"}])])
        prompts = []
        def fake(client, system, user):
            prompts.append(user)
            return next(replies)
        segs = yd.speech_segments(yd.parse_srt(SRT))
        with mock.patch("transcription_summary_core.call_llm", side_effect=fake):
            starts = yd.locate_points(None, segs, [f"P{n}" for n in range(1, 21)])
        self.assertIn("2. B (points: P9; P10;", prompts[1])
        self.assertEqual(starts, [(8.5, "A"), (1200.0, "B")])

    def test_grouping_falls_back_to_even_runs(self):
        too_many = json.dumps([{"first": n, "title": "x"} for n in range(1, 21)])
        with mock.patch("transcription_summary_core.call_llm", return_value=too_many):
            groups = yd.group_points(None, [f"P{n}" for n in range(1, 31)])
        self.assertEqual(len(groups), 10)            # runs of 3
        self.assertEqual(groups[:2], [("P1", 0), ("P4", 3)])

    def test_bad_reply_still_writes_description(self):
        with mock.patch("sys.stderr"):
            text = self.run_with([{"chapter": 1, "segment": 0}])
        self.assertNotIn("Chapters", text)
        self.assertIn("A talk about holiness.", text)

    def test_model_failure_is_a_warning(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch("sys.stderr"), \
                mock.patch("transcription_summary_core.call_llm",
                           side_effect=RuntimeError("LLM call failed after retries")):
            base = Path(tmp) / "talk"
            base.with_suffix(".srt").write_text(SRT, encoding="utf-8")
            self.assertIsNone(yd.write_youtube_description(
                None, base, base.with_suffix(".srt"), OUTLINE, "summary", False))
            self.assertFalse(base.with_suffix(".youtube.txt").exists())

    def test_no_srt_still_writes_description(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("transcription_summary_core.call_llm", return_value="Summary."):
            base = Path(tmp) / "sermon"
            yd.write_youtube_description(None, base, base.with_suffix(".srt"), OUTLINE,
                                         "summary", False, event="Morning Worship")
            self.assertEqual(base.with_suffix(".youtube.txt").read_text(),
                             "Morning Worship\n" + yd.HOST_LINE + "\n\nSummary.\n")


class SpecialEventsColumns(unittest.TestCase):
    def test_optional_youtube_columns(self):
        rows = parse("date,code,speaker,title,scripture,event,conference,session,notes\n"
                     '10/30/26,RC1,Dr. D,Title,,RefCon 2026,"Holiness: Glory",Session One,\n'
                     "10/31/26,RC1,Dr. D,Title,,RefCon 2026\n")
        first, second = rows.values()
        self.assertEqual(first["youtube"], {"conference": "Holiness: Glory",
                                            "session": "Session One", "notes": None})
        self.assertEqual(second["youtube"], {"conference": None, "session": None, "notes": None})


if __name__ == "__main__":
    unittest.main()
