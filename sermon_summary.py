from pathlib import Path
from transcription_summary_core import (
    call_llm, read_text, write_docx, write_text,
    clean_transcript, estimate_tokens, build_metadata_header,
)


def create_outline(client, cleaned_md: str) -> str:
    system = (
        "Create a structured outline of the sermon.\n"
        "Output in Markdown with:\n"
        "- Roman numerals for major points (I, II, III...)\n"
        "- Lettered subpoints (A, B, C...)\n"
        "- Include key Scripture references explicitly mentioned.\n"
        "- Keep it faithful to the sermon; do not invent content.\n"
        "- Use plain text indentation only (spaces or hyphens). "
        "Do NOT use HTML entities such as &nbsp;."
    )
    return call_llm(client, system, cleaned_md).strip()


def create_summary(client, cleaned_md: str) -> str:
    system = (
        "Write a clear 1–2 page summary of the sermon for church leaders.\n"
        "- Capture main thesis, flow, doctrinal emphasis, and applications.\n"
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
                   title: str = None, scripture: str = None):
    base = out_base if out_base else txt_path.with_suffix("")
    meta = build_metadata_header({"Speaker": speaker, "Title": title,
                                  "Scripture": scripture, "Event": event})

    print("  Cleaning transcript...")
    cleaned = clean_transcript(client, read_text(txt_path))
    write_docx(base.with_suffix(".cleaned.docx"), meta + cleaned, overwrite)

    print("  Generating outline...")
    outline = create_outline(client, cleaned)
    write_docx(base.with_suffix(".outline.docx"), meta + outline, overwrite)

    print("  Generating summary...")
    summary = create_summary(client, cleaned)
    write_docx(base.with_suffix(".summary.docx"), meta + summary, overwrite)

    print("  Inferring Scripture...")
    scripture = infer_scripture(client, cleaned)
    write_docx(base.with_suffix(".scripture.docx"), meta + scripture, overwrite)

    print("  Writing podcast description...")
    podcast = create_podcast_description(client, cleaned, speaker, event, scripture)
    write_text(base.with_suffix(".podcast.txt"), podcast, overwrite)
