#!/usr/bin/env python3
"""Checks for the document header, speaker naming, the two outlines and
Whisper's kept formats. No API key or recordings needed: the model is stubbed.

    python3 -m unittest test_transcription_summary
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from docx import Document

import class_summary
import talk_summary
import transcription_summary_core as core
import run_pipeline
from run_pipeline import prune_whisper_outputs


def fake_llm(prompts):
    """A call_llm stand-in that records each system prompt and answers by task."""
    def call(client, system, user, retries=3):
        prompts.append(system)
        if "short title" in system:
            return '"Healthy Stress and Discipline"'
        if "brief outline" in system:
            return "I. Brief point\n   A. Sub"
        if "detailed outline" in system:
            return "I. First\nII. Second\nIII. Third"
        return "Some text."
    return call


def paragraphs(path: Path) -> list[str]:
    return [p.text for p in Document(path).paragraphs if p.text.strip()]


class HeaderTests(unittest.TestCase):
    def test_title_kept_and_theme_added(self):
        h = core.build_document_header("Series, week 8", "Healthy Stress", {"Teacher": "B"})
        self.assertTrue(h.startswith("# Series, week 8\n"))
        self.assertIn("**Theme:** Healthy Stress", h)

    def test_theme_is_heading_without_title(self):
        h = core.build_document_header(None, "Healthy Stress", {"Speaker": "B"})
        self.assertTrue(h.startswith("# Healthy Stress\n"))
        self.assertNotIn("Theme:", h)

    def test_speaker_rule(self):
        self.assertEqual(core.speaker_rule(None), "")
        self.assertIn("she/her", core.speaker_rule("Barbara Abbott", "she/her"))
        self.assertIn("Don't guess", core.speaker_rule("Barbara Abbott"))


class DocxSpacingTests(unittest.TestCase):
    def test_no_empty_paragraphs_or_rules(self):
        md = "**Teacher:** B\n\n---\n\n# Title\n\nFirst paragraph.\n\n\nSecond.\n\n- a\n- b\n\nI. Point\n   A. Sub\n"
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "x.docx"
            core.write_docx(path, md, overwrite=True)
            doc = Document(path)
        texts = [p.text for p in doc.paragraphs]
        self.assertNotIn("", texts)
        self.assertEqual(texts, ["Teacher: B", "Title", "First paragraph.", "Second.",
                                 "a", "b", "I. Point", "   A. Sub"])
        self.assertEqual(doc.styles["Normal"].paragraph_format.space_after.pt, 8)
        self.assertEqual(doc.paragraphs[-1].paragraph_format.space_after.pt, 3)


class WhisperOutputTests(unittest.TestCase):
    def test_only_txt_and_srt_kept(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            for ext in (".txt", ".srt", ".json", ".tsv", ".vtt"):
                (d / f"week 8{ext}").write_text("x")
            prune_whisper_outputs(d, "week 8")
            self.assertEqual(sorted(p.suffix for p in d.iterdir()), [".srt", ".txt"])

    def test_json_kept_with_word_times_on_request(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            for ext in (".txt", ".srt", ".json", ".tsv", ".vtt"):
                (d / f"week 8{ext}").write_text("x")
            with mock.patch.object(run_pipeline.subprocess, "run") as run:
                run_pipeline.run_whisper(d / "week 8.m4a", d, keep_json=True)
            self.assertIn("--word_timestamps", run.call_args.args[0])
            self.assertEqual(sorted(p.suffix for p in d.iterdir()), [".json", ".srt", ".txt"])

    def test_no_word_times_by_default(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(run_pipeline.subprocess, "run") as run:
            run_pipeline.run_whisper(Path(d) / "a.m4a", Path(d))
        self.assertNotIn("--word_timestamps", run.call_args.args[0])

    def test_config_setting(self):
        keep = run_pipeline.keep_whisper_json
        # Unset: the types that get cut into reels
        self.assertTrue(keep({}, "sermon"))
        self.assertTrue(keep({}, "talk"))
        self.assertFalse(keep({}, "class"))
        self.assertFalse(keep({"keep_whisper_json": ""}, "meeting"))
        self.assertTrue(keep({"keep_whisper_json": "sermon, class"}, "class"))
        self.assertFalse(keep({"keep_whisper_json": "sermon, class"}, "talk"))
        self.assertTrue(keep({"keep_whisper_json": "true"}, "meeting"))
        self.assertFalse(keep({"keep_whisper_json": "false"}, "sermon"))

    def test_process_file_default_by_type(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            for kind, expected in (("talk", True), ("class", False)):
                audio = d / f"{kind}.m4a"
                audio.write_text("x")
                with mock.patch.object(run_pipeline, "resolve_transcript",
                                       side_effect=RuntimeError("stop")) as rt:
                    with self.assertRaises(RuntimeError):
                        run_pipeline.process_file(None, audio, kind, True, False, "normal",
                                                  None, None, None, None, None)
                self.assertEqual(rt.call_args.args[4], expected, kind)


class ProviderTests(unittest.TestCase):
    def test_provider_names(self):
        self.assertEqual(core.provider_name("Claude"), "claude")
        self.assertEqual(core.provider_name("anthropic"), "claude")
        self.assertEqual(core.provider_name("ollama"), "local")
        self.assertEqual(core.provider_name("ChatGPT"), "openai")
        # Blank or unknown: OpenAI
        self.assertEqual(core.provider_name(""), "openai")
        self.assertEqual(core.provider_name(None), "openai")
        with mock.patch("sys.stderr"):
            self.assertEqual(core.provider_name("gemini"), "openai")

    def test_make_client(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(core.make_client({}))
            self.assertIsNone(core.make_client({"provider": "claude"}))
            claude = core.make_client({"provider": "claude", "api_key": "k"})
            self.assertEqual((claude.provider, claude.model), ("claude", "claude-opus-5-5"))
            local = core.make_client({"provider": "local", "model": "qwen3"})
            self.assertEqual((local.provider, local.model), ("local", "qwen3"))
            self.assertEqual(str(local.sdk.base_url), core.LOCAL_URL + "/")
            # OpenRouter needs its own key and defaults to its own address
            self.assertIsNone(core.make_client({"provider": "openrouter"}))
            router = core.make_client({"provider": "OpenRouter", "api_key": "sk-or-k"})
            self.assertEqual((router.provider, router.model), ("openrouter", "openai/gpt-4.1-mini"))
            self.assertEqual(str(router.sdk.base_url), core.OPENROUTER_URL + "/")
        with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "env"}, clear=True):
            self.assertEqual(core.provider_api_key({"api_key": "cfg"}, "claude"), "env")
            self.assertEqual(core.provider_api_key({"api_key": "cfg"}, "openai"), "cfg")

    def claude_client(self, stop_reason="end_turn", model="claude-opus-5-5"):
        resp = mock.Mock(stop_reason=stop_reason, content=[
            mock.Mock(type="thinking"), mock.Mock(type="text", text="Hello")])
        sdk = mock.Mock()
        sdk.beta.messages.create.return_value = resp
        return core.LLMClient("claude", model, sdk)

    def test_claude_call(self):
        client = self.claude_client()
        self.assertEqual(core.call_llm(client, "sys", "user"), "Hello")
        kwargs = client.sdk.beta.messages.create.call_args.kwargs
        self.assertEqual(kwargs["system"], "sys")
        self.assertEqual(kwargs["extra_body"], {"fallbacks": "default"})
        haiku = self.claude_client(model="claude-haiku-5-5")
        core.call_llm(haiku, "sys", "user")
        self.assertNotIn("extra_body", haiku.sdk.beta.messages.create.call_args.kwargs)

    def test_refusal_not_retried(self):
        client = self.claude_client(stop_reason="refusal")
        with self.assertRaises(core.LLMRefusal):
            core.call_llm(client, "sys", "user")
        self.assertEqual(client.sdk.beta.messages.create.call_count, 1)

    def test_local_call(self):
        sdk = mock.Mock()
        sdk.chat.completions.create.return_value.choices = [mock.Mock(message=mock.Mock(content="Hi"))]
        self.assertEqual(core.call_llm(core.LLMClient("local", "llama3.1", sdk), "s", "u"), "Hi")
        messages = sdk.chat.completions.create.call_args.kwargs["messages"]
        self.assertEqual([m["role"] for m in messages], ["system", "user"])

    def test_openrouter_call(self):
        sdk = mock.Mock()
        sdk.chat.completions.create.return_value.choices = [mock.Mock(message=mock.Mock(content="Hi"))]
        client = core.LLMClient("openrouter", "anthropic/claude-haiku-5-5", sdk)
        self.assertEqual(core.call_llm(client, "s", "u"), "Hi")
        self.assertEqual(sdk.chat.completions.create.call_args.kwargs["model"],
                         "anthropic/claude-haiku-5-5")


class ProcessTests(unittest.TestCase):
    def run_class(self, d: Path, prompts: list):
        txt = d / "week 8.txt"
        txt.write_text("so today we talk about discipline.")
        with mock.patch.object(core, "call_llm", fake_llm(prompts)), \
                mock.patch.object(class_summary, "call_llm", fake_llm(prompts)):
            class_summary.process_class(None, txt, overwrite=True, teacher="Barbara Abbott",
                                        title="Raising Children, week 8", pronouns="she/her")
        return d / "week 8"

    def test_class_writes_both_outlines_with_header(self):
        prompts = []
        with tempfile.TemporaryDirectory() as d:
            base = self.run_class(Path(d), prompts)
            brief = paragraphs(base.with_suffix(".outline.docx"))
            detailed = paragraphs(base.with_suffix(".outline_detailed.docx"))
            self.assertEqual(brief[0], "Raising Children, week 8")
            self.assertIn("Theme: Healthy Stress and Discipline", brief)
            self.assertIn("I. Brief point", brief)
            self.assertIn("III. Third", detailed)
            self.assertTrue(base.with_suffix(".discussion.docx").exists())
        teacher_prompts = [p for p in prompts if "The teacher is Barbara Abbott" in p]
        self.assertTrue(teacher_prompts)
        self.assertTrue(all("she/her" in p and "rather than 'the teacher'" in p
                            for p in teacher_prompts))
        self.assertTrue(any("4 to 6 major points" in p for p in prompts))

    def test_talk_theme_heading_and_detailed_outline_for_youtube(self):
        prompts = []
        with tempfile.TemporaryDirectory() as d:
            txt = Path(d) / "talk.txt"
            txt.write_text("thank you all for coming.")
            with mock.patch.object(core, "call_llm", fake_llm(prompts)), \
                    mock.patch.object(talk_summary, "call_llm", fake_llm(prompts)), \
                    mock.patch.object(talk_summary, "write_youtube_description") as yt:
                talk_summary.process_talk(None, txt, overwrite=True, speaker="Barbara Abbott")
            self.assertEqual(paragraphs(Path(d) / "talk.summary.docx")[0],
                             "Healthy Stress and Discipline")
            self.assertEqual(yt.call_args.args[3], "I. First\nII. Second\nIII. Third")
        self.assertTrue(any("The speaker is Barbara Abbott" in p and "Don't guess" in p
                            for p in prompts))


if __name__ == "__main__":
    unittest.main()
