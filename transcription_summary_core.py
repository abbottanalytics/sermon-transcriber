#!/usr/bin/env python3

# -------------------------------------------------
# PURPOSE:
# Shared core utilities for transcription processing.
#
# This module provides:
# - LLM interaction
# - transcript chunking
# - docx/text writing
# - transcript cleaning
#
# DESIGN PRINCIPLES:
# - No meeting/sermon-specific logic
# - Reusable across multiple workflows
# - Safe for large transcripts via chunking
# -------------------------------------------------

import re
import time
from pathlib import Path
from typing import List

try:
    import tiktoken
except ImportError:
    tiktoken = None

from openai import OpenAI
from docx import Document
from docx.shared import Pt

MODEL = "gpt-4.1-mini"
# Transcript cleaning goes in chunks of about this many tokens. Given much
# more at once, the model condenses (a 7,000-word class came back as 2,100
# words); at this size it tidies instead.
CLEAN_CHUNK_TOKENS = 3000
SLEEP_BETWEEN_CALLS = 0.4


# -------------------------------------------------
# METADATA HELPERS
# -------------------------------------------------

def build_metadata_header(fields: dict) -> str:
    """
    Build a markdown metadata block to prepend to document content.

    Example:
        build_metadata_header({"Speaker": "Pastor Joel Wood", "Event": "Morning Worship"})
        → "**Speaker:** Pastor Joel Wood\n**Event:** Morning Worship\n\n---\n\n"
    """
    lines = [f"**{k}:** {v}" for k, v in fields.items() if v]
    return ("\n".join(lines) + "\n\n---\n\n") if lines else ""


def build_document_header(title: str | None, theme: str | None, fields: dict) -> str:
    """
    A document's top: the title as a heading, then the metadata block.

    A given title (often a series name, e.g. 'Thinking Christianly about
    Raising Children, week 7') stays the heading and the inferred theme goes
    beside the other fields; without a title the theme is the heading.
    """
    heading = title or theme
    extra = {"Theme": theme} if title and theme and theme.lower() != title.lower() else {}
    return (f"# {heading}\n\n" if heading else "") + build_metadata_header({**fields, **extra})


def infer_theme(client: "OpenAI", cleaned_md: str, kind: str = "talk") -> str:
    """A short title naming what a sermon, talk or class was about."""
    system = (
        f"Give a short title (3–8 words) naming the main theme of this {kind}.\n"
        "- Title case. Return only the title: no quotes, no 'Title:', no speaker, "
        "event, series or week number."
    )
    return call_llm(client, system, cleaned_md).strip().strip('"“”*#').strip()


def speaker_rule(name: str | None, pronouns: str | None = None,
                 role: str = "speaker") -> str:
    """
    Prompt line telling the model to call the person leading by name.

    Without it the documents say 'the speaker' throughout. A name says nothing
    reliable about pronouns, so they are used only when given.
    """
    if not name:
        return ""
    pronoun_rule = (f"Use {pronouns} pronouns for {name}." if pronouns else
                    f"Don't guess {name}'s pronouns from the name: repeat the name or "
                    "rephrase instead.")
    return (f"- The {role} is {name}. Refer to them by name (a shorter form, such as the "
            f"first name, is fine after the first mention), not as 'the {role}' or "
            f"'the speaker'. {pronoun_rule}\n")


# Shared by the sermon, talk and class outlines: the short one is the
# .outline.docx people read; the detailed one follows the talk point by point
# (.outline_detailed.docx, and the source of YouTube chapters).
BRIEF_OUTLINE_RULES = (
    "- 4 to 6 major points (I, II, III...), grouped by idea rather than in the order "
    "every topic came up\n"
    "- 2 to 4 short lettered subpoints (A, B, C...) under each, a phrase rather than a "
    "sentence\n"
    "- Leave out announcements, scheduling, opening and closing prayers\n"
    "- About half a page in all\n"
)
DETAILED_OUTLINE_RULES = (
    "- Roman numerals for major points (I, II, III...)\n"
    "- Lettered subpoints (A, B, C...)\n"
)


# -------------------------------------------------
# FILE OUTPUT HELPERS
# -------------------------------------------------

# **bold**, __bold__, *italic* or _italic_ inside a line
_INLINE = re.compile(r"(\*\*.+?\*\*|__.+?__|(?<![*\w])\*(?!\s).+?(?<!\s)\*(?![*\w])|(?<!\w)_(?!\s).+?(?<!\s)_(?!\w))")
_BULLET = re.compile(r"^(\s*)[-*•]\s+(.*)$")
# An outline line: "I. ...", "A. ...", "1. ...", "a. ..."
_OUTLINE_LINE = re.compile(r"^\s*([IVXLC]+|[A-Za-z]|\d+)[.)]\s")


def _add_inline(paragraph, text: str):
    """Add text to a paragraph, turning Markdown bold/italic marks into formatting."""
    for part in _INLINE.split(text):
        if not part:
            continue
        if (part.startswith("**") and part.endswith("**") or
                part.startswith("__") and part.endswith("__")) and len(part) > 4:
            paragraph.add_run(part[2:-2]).bold = True
        elif part[0] in "*_" and part[-1] == part[0] and len(part) > 2:
            paragraph.add_run(part[1:-1]).italic = True
        else:
            paragraph.add_run(part)


def _set_spacing(doc):
    """Space between paragraphs comes from the styles, so the documents need no
    empty paragraphs (the hard returns people otherwise delete by hand)."""
    doc.styles["Normal"].paragraph_format.space_after = Pt(8)
    for name in ("List Bullet", "List Bullet 2"):
        doc.styles[name].paragraph_format.space_after = Pt(3)


def write_docx(path, markdown_text, overwrite):
    if path.exists() and not overwrite:
        print(f"SKIP (exists): {path}")
        return

    doc = Document()
    _set_spacing(doc)

    for line in markdown_text.splitlines():
        line = line.rstrip()            # Markdown's trailing-space line breaks
        heading = re.match(r"^(#{1,3})\s+(.*)$", line)
        bullet = _BULLET.match(line)
        if heading:
            # Headings are bold already; drop any marks inside them
            doc.add_heading(re.sub(r"\*\*|__", "", heading.group(2)), level=len(heading.group(1)))
        elif re.fullmatch(r"\s*([-*_])(\s*\1){2,}\s*", line):
            continue                    # Markdown '---': headings already separate sections
        elif line.startswith("> "):
            p = doc.add_paragraph()
            _add_inline(p, line[2:])
            p.paragraph_format.left_indent = Pt(18)
        elif bullet:
            # Indented bullets (sub-points) go one level in
            level = 2 if len(bullet.group(1).expandtabs(4)) >= 2 else 1
            p = doc.add_paragraph(style="List Bullet" if level == 1 else "List Bullet 2")
            _add_inline(p, bullet.group(2))
        elif line.strip() == "":
            continue                    # paragraph spacing is in the styles
        else:
            p = doc.add_paragraph()
            _add_inline(p, line)
            if _OUTLINE_LINE.match(line):
                # Outline lines sit close together, like a list
                p.paragraph_format.space_after = Pt(3)

    doc.save(path)
    print(f"WROTE: {path}")


def write_text(path: Path, content: str, overwrite: bool):
    if path.exists() and not overwrite:
        print(f"SKIP (exists): {path}")
        return
    path.write_text(content.strip() + "\n", encoding="utf-8")
    print(f"WROTE: {path}")


# -------------------------------------------------
# TOKEN + CHUNKING
# -------------------------------------------------

def estimate_tokens(text: str) -> int:
    if not tiktoken:
        return len(text) // 4
    enc = tiktoken.encoding_for_model(MODEL)
    return len(enc.encode(text))


def chunk_text(text: str, max_tokens: int) -> List[str]:
    """
    Split text into chunks of about max_tokens, ending at sentence breaks.

    WHY:
    - Each chunk is cleaned separately, and the cleaned chunks are joined, so
      chunks don't overlap (overlap would repeat sentences in the output)
    - Breaking between sentences keeps each chunk's text whole
    """
    max_chars = max_tokens * 4
    sentences = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    chunks, current = [], ""
    for sentence in sentences:
        if current and len(current) + len(sentence) + 1 > max_chars:
            chunks.append(current)
            current = ""
        current = f"{current} {sentence}" if current else sentence
    if current:
        chunks.append(current)
    return chunks


# -------------------------------------------------
# INPUT HELPERS
# -------------------------------------------------

def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore").strip()


# -------------------------------------------------
# LLM CALL (WITH RETRY + SAFE OUTPUT)
# -------------------------------------------------

def call_llm(client: OpenAI, system: str, user: str, retries=3) -> str:
    """
    Safe LLM call wrapper.

    Adds:
    - retry logic
    - robust output extraction
    """

    for attempt in range(retries):
        try:
            resp = client.responses.create(
                model=MODEL,
                input=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )

            # SAFER OUTPUT EXTRACTION
            if hasattr(resp, "output_text") and resp.output_text:
                return resp.output_text

            # fallback (rare but safer)
            return resp.output[0].content[0].text

        except Exception as e:
            print(f"LLM error (attempt {attempt+1}): {e}")
            time.sleep(1 + attempt)

    raise RuntimeError("LLM call failed after retries")


# -------------------------------------------------
# TRANSCRIPT CLEANING
# -------------------------------------------------

def clean_transcript(client: OpenAI, raw_text: str) -> str:
    """
    Clean raw ASR transcript into readable structured text.

    DESIGN CHOICES:
    - No summarization
    - Preserve meaning
    - Add light structure (headings)
    - Avoid speaker hallucination
    """

    system = (
        "You are editing a transcript produced by automatic speech recognition.\n"
        "- Preserve meaning; do not summarize, shorten or paraphrase. Keep every point, "
        "example and story, in the speaker's own words.\n"
        "- Fix punctuation and structure.\n"
        "- Remove obvious filler words.\n"
        "- Add section headings (##) when topics shift.\n"
        "- Do NOT guess speaker identities.\n"
    )

    chunks = chunk_text(raw_text, CLEAN_CHUNK_TOKENS)
    parts = []

    for i, chunk in enumerate(chunks, 1):
        print(f"  Cleaning chunk {i}/{len(chunks)}")
        parts.append(call_llm(client, system, chunk))
        time.sleep(SLEEP_BETWEEN_CALLS)

    return "\n\n".join(parts).strip()

