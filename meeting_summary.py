from pathlib import Path
from transcription_summary_core import *

# -----------------------------
# AGENDA INGESTION
# -----------------------------

def read_docx(path: Path) -> str:
    from docx import Document
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs)


def read_txt(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore").strip()


def read_pdf(path: Path) -> str:
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages).strip()


def read_agenda(path: Path) -> str:
    """Read an agenda file in .docx, .txt, or .pdf format."""
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return read_docx(path)
    elif suffix == ".txt":
        return read_txt(path)
    elif suffix == ".pdf":
        return read_pdf(path)
    else:
        raise ValueError(f"Unsupported agenda format: {suffix}. Use .docx, .txt, or .pdf")


def normalize_agenda(client, raw_agenda: str) -> str:
    system = (
        "Reconstruct a structured meeting agenda from raw text.\n\n"
        "Rules:\n"
        "- Add numbering to all items\n"
        "- Group sub-items under logical parents\n"
        "- Preserve order exactly\n"
        "- Remove duplicates\n"
        "- Preserve wording faithfully\n"
        "- Do NOT invent agenda items\n"
    )
    return call_llm(client, system, raw_agenda).strip()


# -----------------------------
# MEETING OUTPUTS
# -----------------------------
# -------------------------------------------------
# PURPOSE:
# Generate formal meeting minutes with optional
# agenda alignment and configurable verbosity.
#
# KEY DESIGN CHOICES:
# - Agenda mapping is conservative (no guessing)
# - Unmapped discussion is explicitly surfaced
#   as "Unknown Agenda Item #n"
# - Style parameter controls level of detail
#
# WHY THIS EXISTS:
# Prevents hallucinated structure and ensures
# governance-grade accuracy for Session review.
# -------------------------------------------------

def create_summary(client, cleaned_md: str) -> str:
    system = (
        "Create a structured meeting summary.\n\n"
        "## Key Decisions\n"
        "- ...\n\n"
        "## Major Discussion Topics\n"
        "- ...\n\n"
        "## Open Questions\n"
        "- ...\n"
    )
    return call_llm(client, system, cleaned_md).strip()


def create_actions(client, cleaned_md: str) -> str:
    system = (
        "Extract ACTION ITEMS from this meeting.\n\n"
        "## Action Items\n"
        "- [ ] Task — Owner (or Unassigned)\n\n"
        "Rules:\n"
        "- Include only clear, actionable items\n"
        "- Do not include vague discussion\n"
        "- Combine duplicates\n"
        "- Do not invent details\n"
    )
    return call_llm(client, system, cleaned_md).strip()


def extract_motions(client, cleaned_md: str) -> str:
    system = (
        "Extract formal MOTIONS from this meeting.\n\n"
        "## Motions\n"
        "1. Motion: <text>\n"
        "   - Moved by: Unknown if not stated\n"
        "   - Seconded by: Unknown if not stated\n"
        "   - Result: Approved / Denied / Tabled / Unclear\n\n"
        "Rules:\n"
        "- Only include actual motions (not suggestions)\n"
        "- Preserve wording as closely as possible\n"
        "- Do not invent names\n"
    )
    return call_llm(client, system, cleaned_md).strip()


# -----------------------------
# MINUTES (STYLE + AGENDA)
# -----------------------------

def create_minutes(client, cleaned_md: str, style: str, agenda_md: str = None) -> str:

    style_instructions = {
        "minimal": (
            "Write concise minutes.\n"
            "- Bullet points only\n"
            "- Capture decisions, motions, and key actions\n"
            "- No narrative\n"
        ),
        "normal": (
            "Write standard meeting minutes.\n"
            "- Brief summaries per topic\n"
            "- Include motions, actions, decisions, and key discussion\n"
            "- Moderate detail\n"
        ),
        "verbose": (
            "Write detailed meeting minutes.\n"
            "- Include discussion summaries, discussion flow and context\n"
            "- Capture reasoning behind decisions\n"
            "- Still structured and readable\n"
        )
    }

    base_prompt = (
        "Generate structured meeting minutes from this transcript.\n\n"

        "## Core Requirements:\n"
        "- Use the agenda as the primary structure if provided\n"
        "- Organize discussion under the appropriate agenda item\n\n"

#       These rules deliberately bias toward UNDER-assignment
#       rather than incorrect assignment. This is critical for
#       maintaining trust in the output.

        "## Critical Rules:\n"

        # --- Agenda Mapping ---
        "- Only assign discussion to an agenda item if there is strong semantic alignment\n"
        "- Prefer leaving content unassigned rather than incorrectly assigning it\n"
        "- If discussion does NOT clearly match any agenda item:\n"
        "  - DO NOT guess\n"
        "  - Create a section labeled 'Unknown Agenda Item #n'\n"
        "  - Number sequentially (1, 2, 3...)\n"
        "- Do NOT merge unrelated topics into agenda items\n"

        # --- Motions & Approvals ---
        "- Preserve motions and actions faithfully\n"
        "- Treat the following as clear approval signals:\n"
        "  - The moderator asks for objections and none are raised\n"
        "  - The moderator states 'so ordered'\n"
        "- If 'so ordered' appears, treat it as definitive approval\n"
        "- In these cases, record the outcome as 'motion carried' or 'approved'\n"
        "- Do NOT infer approval without a clear procedural signal\n"

        # --- Language & Style ---
        "- Prefer concise parliamentary phrasing:\n"
        "  - 'Motion carried'\n"
        "  - 'Approved'\n"
        "  - 'So ordered'\n"
        "- Avoid narrating process (e.g., 'no objections were noted') unless necessary\n"
        "- Use formal, neutral minutes language (not conversational)\n"

        # --- Safety ---
        "- Do not invent details\n\n"

        "## Output Structure:\n"
        "- Use agenda items as section headers\n"
        "- Place Unknown Agenda Items at the end\n"
    )

    system = base_prompt + "\n" + style_instructions[style]

    if agenda_md:
        user_input = f"AGENDA:\n{agenda_md}\n\nTRANSCRIPT:\n{cleaned_md}"
    else:
        user_input = cleaned_md

    return call_llm(client, system, user_input).strip()


# -----------------------------
# MAIN PROCESSOR
# -----------------------------

def process_meeting(client, txt_path: Path, overwrite: bool, style="normal", agenda_md=None, out_base=None):
    base = out_base if out_base else txt_path.with_suffix("")

    print("Cleaning transcript...")
    cleaned = clean_transcript(client, read_text(txt_path))
    write_docx(base.with_suffix(".cleaned.docx"), cleaned, overwrite)

    print("Generating minutes...")
    minutes = create_minutes(client, cleaned, style, agenda_md)
    write_docx(base.with_suffix(".minutes.docx"), minutes, overwrite)

    print("Generating summary...")
    summary = create_summary(client, cleaned)
    write_docx(base.with_suffix(".meeting_summary.docx"), summary, overwrite)

    print("Extracting actions...")
    actions = create_actions(client, cleaned)
    write_docx(base.with_suffix(".actions.docx"), actions, overwrite)

    print("Extracting motions...")
    motions = extract_motions(client, cleaned)
    write_docx(base.with_suffix(".motions.docx"), motions, overwrite)

    combined = f"{motions}\n\n{actions}"
    write_text(base.with_suffix(".motions_and_actions.txt"), combined, overwrite)

