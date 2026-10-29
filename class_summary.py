from pathlib import Path
from transcription_summary_core import (
    call_llm, read_text, write_docx, write_text,
    clean_transcript, build_metadata_header,
)

# Every class document is labeled with this unless another event is given
HIGHER_ED_EVENT = "Higher Ed (Adult Sunday School)"

# A class is a teacher plus a room of people talking. The transcript has no
# speaker labels, and what members share (prayer requests, family, health) is
# not for a document others will read — every prompt below says so.
PRIVACY_RULES = (
    "This is an adult Sunday School class: a teacher plus discussion among class members. "
    "The transcript has no speaker labels.\n"
    "Privacy rules (important — these documents are shared with people who weren't there):\n"
    "- Never use the name of anyone in the room or anyone they mention (family, friends, "
    "church members) — not for class members, and not for the teacher. Biblical, historical "
    "and published figures (Moses, Augustine, an author cited) are fine. "
    "Write 'a participant', 'one member', 'several people'.\n"
    "- {teacher_rule}\n"
    "- Leave out personal details anyone shared: prayer requests, health, family, "
    "work, finances, struggles, confessions. Keep only the point a comment made "
    "about the lesson.\n"
    "- Do not invent content or attribute a comment to the teacher unless it clearly "
    "comes from the person leading.\n"
)


def _rules(teacher: str | None) -> str:
    # Only the name a person entered is used: never one heard in the recording,
    # which may be wrong (Whisper) or belong to someone else in the room
    teacher_rule = (f"The teacher is {teacher}. Refer to the teacher only as '{teacher}' or "
                    "'the teacher' — never by any other name, even if the recording says one."
                    if teacher else
                    "Refer to the person leading only as 'the teacher'. Never use a name "
                    "from the recording for them.")
    return PRIVACY_RULES.format(teacher_rule=teacher_rule)


def create_summary(client, cleaned_md: str, teacher: str = None,
                   topic: str = None, scripture: str = None) -> str:
    known = "".join([f"- The lesson's topic is: {topic}\n" if topic else "",
                     f"- The passage studied is: {scripture}\n" if scripture else ""])
    system = (
        _rules(teacher)
        + "\nWrite a 1–2 page summary of the class for someone who missed it.\n"
        + known
        + "Use these Markdown headings:\n"
        "## Topic and Text — what was studied (the series or lesson, and the main passage)\n"
        "## Teaching — the teacher's main points, in order\n"
        "## Discussion — the main questions and themes members raised, and how they "
        "were answered; note real differences of view fairly\n"
        "## Scripture Referenced — every passage mentioned, one per line\n"
        "## Takeaways — 3–5 short points\n"
        "- Short quotes from the teacher are fine; don't quote members word for word."
    )
    return call_llm(client, system, cleaned_md).strip()


def create_outline(client, cleaned_md: str, teacher: str = None) -> str:
    system = (
        _rules(teacher)
        + "\nCreate an outline of the lesson as the teacher led it.\n"
        "Output in Markdown with:\n"
        "- Roman numerals for major points (I, II, III...)\n"
        "- Lettered subpoints (A, B, C...)\n"
        "- Scripture references where they come up\n"
        "- Where a discussion happened, one subpoint starting 'Discussion:' that "
        "names the question discussed, not who said what\n"
        "- Plain text indentation only (spaces or hyphens). "
        "Do NOT use HTML entities such as &nbsp;."
    )
    return call_llm(client, system, cleaned_md).strip()


def create_discussion_guide(client, cleaned_md: str, teacher: str = None) -> str:
    system = (
        _rules(teacher)
        + "\nWrite a short discussion guide from this class, for a small group, a family, "
        "or someone studying on their own.\n"
        "Use these Markdown headings:\n"
        "## Questions Raised in Class — the questions members actually asked or wrestled "
        "with, each followed by one or two sentences on where the class landed\n"
        "## Still Open — questions the class left unresolved or wanted to come back to "
        "(write 'None noted.' if there were none)\n"
        "## For Further Reflection — 4–6 new questions that build on the lesson, each "
        "tied to a passage where possible\n"
        "- Keep it to about one page."
    )
    return call_llm(client, system, cleaned_md).strip()


def create_podcast_description(client, cleaned_md: str, teacher: str = None,
                               topic: str = None, scripture: str = None,
                               event: str = HIGHER_ED_EVENT) -> str:
    subject = topic or scripture or "[the lesson's topic or passage]"
    opening = (f"{teacher} teaching on {subject} in {event}." if teacher else
               f"The {event} class studies {subject}.")
    known = (f"- The passage studied is {scripture}; use it exactly as written.\n"
             if scripture else "")
    system = (
        _rules(teacher)
        + "\nWrite a 2-3 sentence podcast episode description for this class.\n"
        + known
        + f"- Begin the description with: '{opening}' "
        "If the topic isn't given, put the lesson's topic or main passage in its place.\n"
        "- Follow with 1-2 sentences on what the class studied and discussed.\n"
        "- Plain text only — no markdown, no bullet points.\n"
        "- Keep it engaging and suitable for a podcast app listing."
    )
    return call_llm(client, system, cleaned_md[:6000]).strip()


def process_class(client, txt_path: Path, overwrite: bool,
                  out_base: Path = None, teacher: str = None, event: str = None,
                  title: str = None, scripture: str = None):
    base = out_base if out_base else txt_path.with_suffix("")
    event = event or HIGHER_ED_EVENT
    meta = build_metadata_header({"Teacher": teacher, "Topic": title,
                                  "Scripture": scripture, "Event": event})

    # The cleaned transcript keeps everything that was said, so it isn't
    # published unless publish_class_transcripts=true (see drive_publish.py)
    print("  Cleaning transcript...")
    cleaned = clean_transcript(client, read_text(txt_path))
    write_docx(base.with_suffix(".cleaned.docx"), meta + cleaned, overwrite)

    print("  Generating class summary...")
    summary = create_summary(client, cleaned, teacher, title, scripture)
    write_docx(base.with_suffix(".summary.docx"), meta + summary, overwrite)

    print("  Generating lesson outline...")
    outline = create_outline(client, cleaned, teacher)
    write_docx(base.with_suffix(".outline.docx"), meta + outline, overwrite)

    print("  Writing discussion guide...")
    guide = create_discussion_guide(client, cleaned, teacher)
    write_docx(base.with_suffix(".discussion.docx"), meta + guide, overwrite)

    print("  Writing podcast description...")
    podcast = create_podcast_description(client, cleaned, teacher, title, scripture, event)
    write_text(base.with_suffix(".podcast.txt"), podcast, overwrite)
