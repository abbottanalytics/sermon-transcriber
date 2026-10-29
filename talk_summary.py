from pathlib import Path
from transcription_summary_core import (
    call_llm, read_text, write_docx, write_text,
    clean_transcript, build_metadata_header,
)


def create_outline(client, cleaned_md: str) -> str:
    system = (
        "Create a structured outline of this talk or presentation.\n"
        "Output in Markdown with:\n"
        "- Roman numerals for major points (I, II, III...)\n"
        "- Lettered subpoints (A, B, C...)\n"
        "- Keep it faithful to the talk; do not invent content.\n"
        "- Use plain text indentation only (spaces or hyphens). "
        "Do NOT use HTML entities such as &nbsp;."
    )
    return call_llm(client, system, cleaned_md).strip()


def create_summary(client, cleaned_md: str) -> str:
    system = (
        "Write a clear 1–2 page summary of this talk or presentation.\n"
        "- Capture the main thesis, key arguments, and takeaways.\n"
        "- Use short headings if helpful.\n"
        "- Note any data, research, or examples cited.\n"
        "- Do not invent content."
    )
    return call_llm(client, system, cleaned_md).strip()


def create_podcast_description(client, cleaned_md: str,
                                speaker: str = None, event: str = None,
                                title: str = None) -> str:
    speaker_str = speaker or "the speaker"
    title_str   = f' "{title}"' if title else ""
    event_str   = f" at {event}" if event else ""
    system = (
        "Write a 2-3 sentence podcast episode description for a conference talk.\n"
        f"- Begin the description with: "
        f"'{speaker_str} presenting{title_str}{event_str}.'\n"
        "- Follow with 1-2 sentences capturing the main topic and key takeaways.\n"
        "- Plain text only — no markdown, no bullet points.\n"
        "- Keep it engaging and suitable for a podcast app listing."
    )
    excerpt = cleaned_md[:6000]
    return call_llm(client, system, excerpt).strip()


def process_talk(client, txt_path: Path, overwrite: bool,
                 out_base: Path = None, speaker: str = None,
                 event: str = None, title: str = None):
    base = out_base if out_base else txt_path.with_suffix("")
    meta = build_metadata_header({"Speaker": speaker, "Title": title, "Event": event})

    print("  Cleaning transcript...")
    cleaned = clean_transcript(client, read_text(txt_path))
    write_docx(base.with_suffix(".cleaned.docx"), meta + cleaned, overwrite)

    print("  Generating outline...")
    outline = create_outline(client, cleaned)
    write_docx(base.with_suffix(".outline.docx"), meta + outline, overwrite)

    print("  Generating summary...")
    summary = create_summary(client, cleaned)
    write_docx(base.with_suffix(".summary.docx"), meta + summary, overwrite)

    print("  Writing podcast description...")
    podcast = create_podcast_description(client, cleaned, speaker, event, title)
    write_text(base.with_suffix(".podcast.txt"), podcast, overwrite)
