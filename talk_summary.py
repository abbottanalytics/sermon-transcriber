from pathlib import Path
from transcription_summary_core import (
    call_llm, read_text, write_docx, write_text,
    clean_transcript, build_document_header, infer_theme, speaker_rule,
    BRIEF_OUTLINE_RULES, DETAILED_OUTLINE_RULES,
)
from youtube_description import write_youtube_description


def create_outline(client, cleaned_md: str, detailed: bool = False,
                   speaker: str = None, pronouns: str = None) -> str:
    system = (
        ("Create a detailed outline of this talk or presentation, following it point by point.\n"
         if detailed else "Create a brief outline of this talk or presentation.\n")
        + "Output in Markdown with:\n"
        + (DETAILED_OUTLINE_RULES if detailed else BRIEF_OUTLINE_RULES)
        + speaker_rule(speaker, pronouns)
        + "- Keep it faithful to the talk; do not invent content.\n"
        "- Use plain text indentation only (spaces or hyphens). "
        "Do NOT use HTML entities such as &nbsp;."
    )
    return call_llm(client, system, cleaned_md).strip()


def create_summary(client, cleaned_md: str, speaker: str = None,
                   pronouns: str = None) -> str:
    system = (
        "Write a clear 1–2 page summary of this talk or presentation.\n"
        + speaker_rule(speaker, pronouns)
        + "- Capture the main thesis, key arguments, and takeaways.\n"
        "- Use short headings if helpful.\n"
        "- Note any data, research, or examples cited.\n"
        "- Do not invent content."
    )
    return call_llm(client, system, cleaned_md).strip()


def create_podcast_description(client, cleaned_md: str,
                                speaker: str = None, event: str = None,
                                title: str = None, pronouns: str = None) -> str:
    speaker_str = speaker or "the speaker"
    title_str   = f' "{title}"' if title else ""
    event_str   = f" at {event}" if event else ""
    system = (
        "Write a 2-3 sentence podcast episode description for a conference talk.\n"
        f"- Begin the description with: "
        f"'{speaker_str} presenting{title_str}{event_str}.'\n"
        "- Follow with 1-2 sentences capturing the main topic and key takeaways.\n"
        + speaker_rule(speaker, pronouns)
        + "- Plain text only — no markdown, no bullet points.\n"
        "- Keep it engaging and suitable for a podcast app listing."
    )
    excerpt = cleaned_md[:6000]
    return call_llm(client, system, excerpt).strip()


def process_talk(client, txt_path: Path, overwrite: bool,
                 out_base: Path = None, speaker: str = None,
                 event: str = None, title: str = None, youtube: dict = None,
                 pronouns: str = None):
    base = out_base if out_base else txt_path.with_suffix("")

    print("  Cleaning transcript...")
    cleaned = clean_transcript(client, read_text(txt_path))

    print("  Naming the theme...")
    theme = infer_theme(client, cleaned, "talk")
    meta = build_document_header(title, theme, {"Speaker": speaker, "Event": event})
    write_docx(base.with_suffix(".cleaned.docx"), meta + cleaned, overwrite)

    print("  Generating outlines...")
    outline = create_outline(client, cleaned, speaker=speaker, pronouns=pronouns)
    write_docx(base.with_suffix(".outline.docx"), meta + outline, overwrite)
    detailed = create_outline(client, cleaned, detailed=True, speaker=speaker, pronouns=pronouns)
    write_docx(base.with_suffix(".outline_detailed.docx"), meta + detailed, overwrite)

    print("  Generating summary...")
    summary = create_summary(client, cleaned, speaker, pronouns)
    write_docx(base.with_suffix(".summary.docx"), meta + summary, overwrite)

    print("  Writing podcast description...")
    podcast = create_podcast_description(client, cleaned, speaker, event, title or theme,
                                         pronouns)
    write_text(base.with_suffix(".podcast.txt"), podcast, overwrite)

    print("  Writing YouTube description...")
    # The detailed outline's finer points give chapters closer start times
    write_youtube_description(client, base, txt_path.with_suffix(".srt"), detailed, summary,
                              overwrite, kind="talk", speaker=speaker, event=event,
                              title=title, **(youtube or {}))
