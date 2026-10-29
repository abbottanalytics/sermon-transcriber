from pathlib import Path
from transcription_summary_core import (
    call_llm, read_text, write_docx,
    clean_transcript, build_metadata_header,
)

# A class is a teacher plus a room of people talking. The transcript has no
# speaker labels, and what members share (prayer requests, family, health) is
# not for a document others will read — every prompt below says so.
PRIVACY_RULES = (
    "This is an adult Sunday School class: a teacher plus discussion among class members. "
    "The transcript has no speaker labels.\n"
    "Privacy rules (important — these documents are shared with people who weren't there):\n"
    "- Never name class members, even if names are spoken in the recording. "
    "Write 'a participant', 'one member', 'several people'.\n"
    "- {teacher_rule}\n"
    "- Leave out personal details anyone shared: prayer requests, health, family, "
    "work, finances, struggles, confessions. Keep only the point a comment made "
    "about the lesson.\n"
    "- Do not invent content or attribute a comment to the teacher unless it clearly "
    "comes from the person leading.\n"
)


def _rules(teacher: str | None) -> str:
    teacher_rule = (f"The teacher is {teacher}; you may name them." if teacher else
                    "Refer to the person leading as 'the teacher'; don't guess their name.")
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


def process_class(client, txt_path: Path, overwrite: bool,
                  out_base: Path = None, teacher: str = None, event: str = None,
                  title: str = None, scripture: str = None):
    base = out_base if out_base else txt_path.with_suffix("")
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
