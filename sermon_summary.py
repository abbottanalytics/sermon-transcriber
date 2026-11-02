from pathlib import Path
from transcription_summary_core import (
    call_llm, read_text, write_docx, write_text,
    clean_transcript, estimate_tokens, build_document_header, infer_theme, speaker_rule,
    BRIEF_OUTLINE_RULES, DETAILED_OUTLINE_RULES,
)
from youtube_description import write_youtube_description


def create_outline(client, cleaned_md: str, detailed: bool = False,
                   speaker: str = None, pronouns: str = None) -> str:
    system = (
        ("Create a detailed outline of the sermon, following it point by point.\n"
         if detailed else "Create a brief outline of the sermon.\n")
        + "Output in Markdown with:\n"
        + (DETAILED_OUTLINE_RULES if detailed else BRIEF_OUTLINE_RULES)
        + speaker_rule(speaker, pronouns, role="preacher")
        + "- Include key Scripture references explicitly mentioned.\n"
        "- Keep it faithful to the sermon; do not invent content.\n"
        "- Use plain text indentation only (spaces or hyphens). "
        "Do NOT use HTML entities such as &nbsp;."
    )
    return call_llm(client, system, cleaned_md).strip()


def create_summary(client, cleaned_md: str, speaker: str = None,
                   pronouns: str = None) -> str:
    system = (
        "Write a clear 1–2 page summary of the sermon for church leaders.\n"
        + speaker_rule(speaker, pronouns, role="preacher")
        + "- Capture main thesis, flow, doctrinal emphasis, and applications.\n"
        "- Use short headings if helpful.\n"
        "- Include Scripture references explicitly mentioned.\n"
        "- Do not quote large blocks; short quotes are fine."
    )
    return call_llm(client, system, cleaned_md).strip()


def infer_scripture(client, cleaned_md: str) -> str:
    system = (
        "Infer the primary Scripture text(s) this sermon is based on.\n"
        "Return plain text with this structure:\n"
        "1) Best-guess primary passage(s)\n"
        "2) Confidence: High / Medium / Low\n"
        "3) Evidence: bullet points with short quotes from the sermon\n"
        "Rules:\n"
        "- Prefer passages explicitly cited by the speaker.\n"
        "- If only themes are present, guess cautiously and label Low confidence.\n"
        "- Do not fabricate precise verse numbers unless strongly supported by explicit cues."
    )
    if estimate_tokens(cleaned_md) > 16000:
        cleaned_md = cleaned_md[:60000]
    return call_llm(client, system, cleaned_md).strip()


def create_podcast_description(client, cleaned_md: str,
                                speaker: str = None, event: str = None,
                                scripture: str = None) -> str:
    speaker_str = speaker or "the preacher"
    event_str   = f" in the {event}" if event else ""
    # The preaching schedule's passage, when known, beats inferring one
    passage_step = (f"- The sermon's Scripture passage is {scripture} (from the preaching "
                    "schedule — use it exactly as written, even if the transcript cites "
                    "other verses).\n" if scripture else
                    "- Identify the primary Scripture passage from the sermon transcript.\n")
    passage_str = scripture or "[Scripture passage]"
    system = (
        "Write a 2-3 sentence podcast episode description for a sermon.\n"
        f"{passage_step}"
        f"- Begin the description with: "
        f"'{speaker_str} preaching from {passage_str}{event_str}.'\n"
        "- Follow with 1-2 sentences capturing the main theme and a key application.\n"
        "- Plain text only — no markdown, no bullet points.\n"
        "- Keep it engaging and suitable for a podcast app listing."
    )
    # First portion of transcript is sufficient for this
    excerpt = cleaned_md[:6000]
    return call_llm(client, system, excerpt).strip()


def process_sermon(client, txt_path: Path, overwrite: bool,
                   out_base: Path = None, speaker: str = None, event: str = None,
                   title: str = None, scripture: str = None, youtube: dict = None,
                   pronouns: str = None):
    base = out_base if out_base else txt_path.with_suffix("")

    print("  Cleaning transcript...")
    cleaned = clean_transcript(client, read_text(txt_path))

    print("  Naming the theme...")
    theme = infer_theme(client, cleaned, "sermon")
    meta = build_document_header(title, theme, {"Speaker": speaker, "Scripture": scripture,
                                                "Event": event})
    write_docx(base.with_suffix(".cleaned.docx"), meta + cleaned, overwrite)

    print("  Generating outlines...")
    outline = create_outline(client, cleaned, speaker=speaker, pronouns=pronouns)
    write_docx(base.with_suffix(".outline.docx"), meta + outline, overwrite)
    detailed = create_outline(client, cleaned, detailed=True, speaker=speaker, pronouns=pronouns)
    write_docx(base.with_suffix(".outline_detailed.docx"), meta + detailed, overwrite)

    print("  Generating summary...")
    summary = create_summary(client, cleaned, speaker, pronouns)
    write_docx(base.with_suffix(".summary.docx"), meta + summary, overwrite)

    print("  Inferring Scripture...")
    # Its own name: `scripture` is the schedule's passage, which the podcast text needs
    scripture_notes = infer_scripture(client, cleaned)
    write_docx(base.with_suffix(".scripture.docx"), meta + scripture_notes, overwrite)

    print("  Writing podcast description...")
    podcast = create_podcast_description(client, cleaned, speaker, event, scripture)
    write_text(base.with_suffix(".podcast.txt"), podcast, overwrite)

    print("  Writing YouTube description...")
    # The detailed outline's finer points give chapters closer start times
    write_youtube_description(client, base, txt_path.with_suffix(".srt"), detailed, summary,
                              overwrite, kind="sermon", speaker=speaker, event=event,
                              title=title, **(youtube or {}))
