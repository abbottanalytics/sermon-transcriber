#!/usr/bin/env python3
"""
Preaching analysis module.

Four analysis tasks run per sermon:
  1. segment_components  — label transcript by type, compute % content per type
  2. assess_application  — does the application flow from the passage or lead it?
  3. detect_critique     — congregation critique present? winsome alternatives?
  4. extract_application_themes — short phrases for cross-sermon tracking

Each task returns a dict. analyze_sermon() runs all four and returns combined JSON.
The ANALYSIS_TASKS list controls what runs — add new functions there to extend.
"""

import json
import re
import time
from pathlib import Path

from transcription_summary_core import call_llm, SLEEP_BETWEEN_CALLS


# ── SRT helpers ───────────────────────────────────────────────────────────────

def parse_srt(srt_path: Path) -> list[dict]:
    """Parse a Whisper SRT into [{idx, start_sec, end_sec, text}, ...]."""
    segments = []
    text = srt_path.read_text(encoding="utf-8", errors="ignore")
    for block in re.split(r"\n\n+", text.strip()):
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        try:
            idx = int(lines[0].strip())
        except ValueError:
            continue
        m = re.match(
            r"(\d+):(\d+):(\d+),(\d+)\s*-->\s*(\d+):(\d+):(\d+),(\d+)", lines[1]
        )
        if not m:
            continue
        h1, m1, s1, ms1, h2, m2, s2, ms2 = (int(x) for x in m.groups())
        start = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000
        end   = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000
        segments.append({
            "idx": idx,
            "start_sec": start,
            "end_sec": end,
            "text": " ".join(lines[2:]).strip(),
        })
    return segments


def srt_duration_seconds(srt_path: Path) -> float | None:
    """Return total sermon duration in seconds, or None if no SRT."""
    if not srt_path or not srt_path.exists():
        return None
    segs = parse_srt(srt_path)
    return segs[-1]["end_sec"] if segs else None


def fmt_duration(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}h {m}m {s}s" if h else f"{m}m {s}s"


# ── JSON LLM helper ───────────────────────────────────────────────────────────

def _call_json(client, system: str, user: str) -> dict | list | None:
    """Call LLM, strip markdown fences, parse JSON. Returns None on failure."""
    raw = call_llm(client, system, user)
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    raw = re.sub(r"```\s*$", "", raw.strip(), flags=re.MULTILINE)
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        m = re.search(r"(\{.*\}|\[.*\])", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
    return None


# ── Task 1: Component segmentation ───────────────────────────────────────────

COMPONENT_TYPES = ["introduction", "exegesis", "application", "illustration", "transition", "conclusion"]

def segment_components(client, transcript: str, srt_path: Path = None) -> dict:
    """
    Label sermon content by type and estimate % of content per type.
    Uses word-count percentages from the transcript (reliable proxy for time).
    SRT is used only for total duration reporting.
    """
    system = (
        "You are analyzing a sermon transcript to identify how the preacher's time is distributed "
        "across different sermon components.\n\n"
        "COMPONENT TYPES:\n"
        "  introduction  — opening remarks, framing the passage, Scripture reading, opening prayer\n"
        "  exegesis      — direct engagement with the biblical text: reading, explaining, "
        "unpacking meaning of words, phrases, grammar, context, cross-references, theology\n"
        "  application   — explicit calls to action, 'this means for us...', 'we must...', "
        "'consider your own...', pressing the text into the listener's life or church\n"
        "  illustration  — stories, analogies, historical examples, personal anecdotes used "
        "to clarify or motivate\n"
        "  transition    — brief connecting phrases between major moves\n"
        "  conclusion    — closing summary, final exhortation, closing prayer\n\n"
        "TASK:\n"
        "1. Produce a SEGMENT MAP: identify 4-10 major sections in order. For each section give "
        "a short label, its primary component type, an approximate word count, and a one-sentence "
        "summary. Sections should be meaningful structural units, not individual paragraphs.\n\n"
        "2. IMPORTANT: Look for any section where the preacher explicitly signals a departure from "
        "the main flow — phrases like 'let me take an excursus', 'I want to digress', 'parenthesis', "
        "or an explicit return marker like 'excursus ended', 'back to the text'. If found, flag that "
        "section and quote the boundary phrases.\n\n"
        "3. Calculate COMPONENT TOTALS: sum word counts by component type and compute percentages. "
        "Application that is exegetically framed still counts as application if it explicitly "
        "presses the hearer to respond or change behavior.\n\n"
        "Estimate total word count of the sermon. Use plain text — no HTML entities.\n\n"
        "Return ONLY valid JSON:\n"
        "{\n"
        '  "total_word_count": <number>,\n'
        '  "segment_map": [\n'
        '    {\n'
        '      "label": "short title",\n'
        '      "type": "introduction|exegesis|application|illustration|transition|conclusion",\n'
        '      "word_count": <number>,\n'
        '      "percent_of_sermon": <number>,\n'
        '      "summary": "one sentence",\n'
        '      "explicitly_marked_digression": false\n'
        "    }\n"
        "  ],\n"
        '  "digressions": [\n'
        '    {\n'
        '      "label": "short description",\n'
        '      "opening_phrase": "exact or near-exact quote",\n'
        '      "closing_phrase": "exact or near-exact quote",\n'
        '      "word_count": <number>,\n'
        '      "percent_of_sermon": <number>\n'
        "    }\n"
        "  ],\n"
        '  "component_totals": {\n'
        '    "introduction": {"word_count": <n>, "percent": <n>},\n'
        '    "exegesis":     {"word_count": <n>, "percent": <n>},\n'
        '    "application":  {"word_count": <n>, "percent": <n>},\n'
        '    "illustration": {"word_count": <n>, "percent": <n>},\n'
        '    "transition":   {"word_count": <n>, "percent": <n>},\n'
        '    "conclusion":   {"word_count": <n>, "percent": <n>}\n'
        "  },\n"
        '  "notes": "any brief structural observations"\n'
        "}\n"
        "All percents should sum to 100. Digression list may be empty."
    )
    result = _call_json(client, system, transcript)
    time.sleep(SLEEP_BETWEEN_CALLS)

    duration = srt_duration_seconds(srt_path)

    if not result or "component_percentages" not in result:
        return {
            "component_percentages": {t: None for t in COMPONENT_TYPES},
            "major_movements": [],
            "notes": "Segmentation failed — raw LLM output could not be parsed.",
            "total_duration_seconds": duration,
        }

    result["total_duration_seconds"] = duration
    return result


# ── Task 2: Application authenticity assessment ───────────────────────────────

def assess_application(client, transcript: str, scripture_hint: str = None) -> dict:
    """
    Assess whether the sermon's application flows naturally from the passage
    or whether the application appears to precede and drive the interpretation.
    Uses a 4-level textual correspondence scale.
    """
    scripture_line = f"The primary Scripture passage for this sermon is: {scripture_hint}\n\n" if scripture_hint else ""

    system = (
        "You are a homiletics analyst evaluating the relationship between biblical exegesis "
        "and pastoral application in a sermon. This analysis is intended for a pastor's own "
        "reflection — be fair, specific, and analytically rigorous.\n\n"

        "STEP 1 — WHAT THE TEXT ACTUALLY SAYS:\n"
        "List 4-8 bullet points: what does the biblical passage explicitly teach, narrate, or "
        "command? What theological inferences are reasonable from the passage? Stay close to "
        "what the text itself establishes.\n\n"

        "STEP 2 — TEXTUAL CORRESPONDENCE SCALE:\n"
        "For each major application in the sermon, assign one of these four levels:\n"
        "  Level 1 — Direct exposition: the application states or restates what the text "
        "explicitly teaches\n"
        "  Level 2 — Reasonable inference: the application follows naturally from the text's "
        "meaning, even if not stated explicitly\n"
        "  Level 3 — Canonical/theological development: the application draws on broader "
        "biblical theology prompted by the passage, but goes beyond the passage itself\n"
        "  Level 4 — Topical/analogical: the application is connected to the passage mainly "
        "by a word, image, or analogy; its content comes primarily from outside the passage\n\n"

        "STEP 3 — LOGICAL STRUCTURE OF ANALOGIES:\n"
        "If any application rests on an analogy (e.g., 'just as X in the text, so we should Y'), "
        "examine whether the analogy holds. Are the two situations morally and structurally "
        "comparable? Identify any logical gap or weakness in the transfer.\n\n"

        "STEP 4 — INTENDED VS. EXPERIENCED MESSAGE:\n"
        "State the pastor's apparent intended message (what he wanted hearers to take away). "
        "Then state how a resistant, wounded, or skeptical listener might experience the same "
        "content. Note the gap between these if it exists.\n\n"

        "STEP 5 — OVERALL VERDICT:\n"
        "  Exegetically grounded  — dominant applications are Level 1-2\n"
        "  Mixed                  — mix of Level 1-3 applications\n"
        "  Text-occasioned        — dominant applications are Level 3-4; the text prompts but "
        "does not ground the application\n"
        "  Application-led        — the application clearly preceded the exegesis; the text "
        "is used as authority for a concern arising elsewhere\n\n"

        "Return ONLY valid JSON:\n"
        "{\n"
        '  "what_text_establishes": ["bullet 1", "bullet 2", ...],\n'
        '  "applications": [\n'
        '    {\n'
        '      "application": "brief description",\n'
        '      "correspondence_level": 1,\n'
        '      "level_label": "Direct exposition|Reasonable inference|Canonical development|Topical/analogical",\n'
        '      "analogy_weakness": "describe flaw if Level 3-4, or null",\n'
        '      "evidence": "one sentence"\n'
        '    }\n'
        "  ],\n"
        '  "intended_message": "one sentence — what the pastor wanted hearers to receive",\n'
        '  "experienced_message": "one sentence — how a resistant or wounded listener might hear it",\n'
        '  "verdict": "Exegetically grounded|Mixed|Text-occasioned|Application-led",\n'
        '  "confidence": "High|Medium|Low",\n'
        '  "strengths": ["..."],\n'
        '  "concerns": ["..."],\n'
        '  "overall_assessment": "2-4 sentence summary"\n'
        "}"
    )

    user = scripture_line + transcript
    result = _call_json(client, system, user)
    time.sleep(SLEEP_BETWEEN_CALLS)

    if not result or "verdict" not in result:
        return {
            "verdict": "Unable to assess",
            "confidence": "Low",
            "what_text_establishes": [],
            "applications": [],
            "intended_message": None,
            "experienced_message": None,
            "overall_assessment": "Assessment failed — output could not be parsed.",
            "strengths": [],
            "concerns": [],
        }
    return result


# ── Task 3: Congregation critique detection ───────────────────────────────────

def detect_critique(client, transcript: str) -> dict:
    """
    Detect whether the sermon contains direct or implied critique of the
    congregation or groups within it. If present, analyze tone and suggest
    more winsome alternative framings.
    """
    system = (
        "You are analyzing a sermon for pastoral tone — specifically whether the preacher "
        "expresses direct or implied criticism directed at the congregation or specific groups.\n\n"

        "WHAT TO LOOK FOR:\n"
        "  - Direct statements criticizing congregation behavior\n"
        "  - Recurring negative characterizations of how members think or act\n"
        "  - Second-person warnings that could feel targeted ('Some of you...', 'You are...')\n"
        "  - A tone of disappointment, frustration, or confrontation directed at hearers\n"
        "  - The pastor's own contested relationship with the congregation introduced into the sermon\n"
        "  - Escalating language (preference → sin, nonparticipation → idolatry)\n\n"

        "WHAT IS NOT CRITIQUE:\n"
        "  - General calls to repentance grounded directly in the Scripture passage\n"
        "  - Self-inclusive pastoral exhortation ('We all struggle with...')\n"
        "  - Naming sin as sin within a context of grace and gospel\n\n"

        "IF CRITIQUE IS PRESENT, ASSESS TONE:\n"
        "Estimate the rhetorical composition of the critical section(s) as percentages:\n"
        "  - warning/admonitory content\n"
        "  - pastoral qualification, solidarity, or support\n"
        "  - bridging/explanatory/humorous content\n\n"

        "Also note: does the application acknowledge legitimate exceptions or reasons why "
        "someone might behave as criticized? (e.g., if criticizing leaving the church, does "
        "it acknowledge legitimate reasons — abuse, doctrinal error, family obligations?)\n\n"

        "For each notable instance, suggest a more winsome alternative — how the same "
        "pastoral concern could be expressed with equal honesty but greater pastoral care.\n\n"

        "Return ONLY valid JSON:\n"
        "{\n"
        '  "critique_present": true|false,\n'
        '  "severity": "None|Mild|Moderate|Prominent",\n'
        '  "tone_breakdown": {\n'
        '    "warning_admonitory_percent": <number or null>,\n'
        '    "pastoral_supportive_percent": <number or null>,\n'
        '    "bridging_explanatory_percent": <number or null>\n'
        "  },\n"
        '  "legitimate_exceptions_acknowledged": true|false|null,\n'
        '  "instances": [\n'
        '    {\n'
        '      "quote_or_paraphrase": "specific language used",\n'
        '      "concern_being_expressed": "what the preacher seems worried about",\n'
        '      "rhetorical_risk": "why this language could be heard as accusatory",\n'
        '      "winsome_alternative": "a suggested reframing"\n'
        '    }\n'
        "  ],\n"
        '  "overall_tone": "one sentence characterizing the overall pastoral tone",\n'
        '  "pastoral_purpose": "one sentence: what the pastor was trying to accomplish",\n'
        '  "rhetorical_effect": "one sentence: how a resistant listener would likely experience it"\n'
        "}"
    )

    result = _call_json(client, system, transcript)
    time.sleep(SLEEP_BETWEEN_CALLS)

    if not result or "critique_present" not in result:
        return {
            "critique_present": False,
            "severity": "Unable to assess",
            "tone_breakdown": {},
            "instances": [],
            "overall_tone": "Assessment failed — output could not be parsed.",
            "pastoral_purpose": None,
            "rhetorical_effect": None,
        }
    return result


# ── Task 4: Application theme extraction ─────────────────────────────────────

def extract_application_themes(client, transcript: str) -> dict:
    """
    Extract the core application claim(s) as short phrases for cross-sermon tracking.
    Themes like "endure suffering by trusting God's providence" are comparable across sermons.
    """
    system = (
        "You are extracting the core application themes from a sermon for cross-sermon analysis.\n\n"
        "For each distinct application the preacher makes, distill it to a short phrase "
        "(5-12 words) that captures the essence of what the listener is being called to believe "
        "or do. These phrases will be compared across many sermons to identify recurring emphases.\n\n"
        "Also note whether each theme is:\n"
        "  - behavioral (what to do)\n"
        "  - attitudinal (what to believe or how to feel)\n"
        "  - relational (how to treat others in the church or world)\n\n"
        "Return ONLY valid JSON:\n"
        "{\n"
        '  "themes": [\n'
        '    {"theme": "short phrase", "type": "behavioral|attitudinal|relational", '
        '"prominence": "primary|secondary"}\n'
        "  ],\n"
        '  "dominant_theme": "the single most prominent application in 10 words or fewer"\n'
        "}"
    )

    result = _call_json(client, system, transcript)
    time.sleep(SLEEP_BETWEEN_CALLS)

    if not result or "themes" not in result:
        return {"themes": [], "dominant_theme": None}
    return result


# ── Orchestrator ──────────────────────────────────────────────────────────────

# Add new task functions here to extend the analysis
ANALYSIS_TASKS = [
    ("component_breakdown", segment_components),
    ("application_assessment", assess_application),
    ("congregation_critique", detect_critique),
    ("application_themes", extract_application_themes),
]


def analyze_sermon(
    client,
    transcript: str,
    srt_path: Path = None,
    scripture_hint: str = None,
    metadata: dict = None,
) -> dict:
    """
    Run all analysis tasks on a sermon transcript.
    Returns combined dict suitable for JSON serialization.

    metadata: optional dict with keys speaker, event, date, title
    """
    result = {
        "metadata": metadata or {},
        "scripture_hint": scripture_hint,
    }

    print("  Segmenting components...")
    result["component_breakdown"] = segment_components(client, transcript, srt_path)

    print("  Assessing application authenticity...")
    result["application_assessment"] = assess_application(client, transcript, scripture_hint)

    print("  Detecting congregation critique...")
    result["congregation_critique"] = detect_critique(client, transcript)

    print("  Extracting application themes...")
    result["application_themes"] = extract_application_themes(client, transcript)

    return result


# ── Report generation ─────────────────────────────────────────────────────────

def build_report_markdown(analysis: dict) -> str:
    """Convert analysis dict to a markdown string for write_docx()."""
    meta = analysis.get("metadata", {})
    lines = []

    # Header
    lines.append("# Preaching Analysis")
    if meta.get("speaker"):
        lines.append(f"**Speaker:** {meta['speaker']}")
    if meta.get("event"):
        lines.append(f"**Event:** {meta['event']}")
    if meta.get("date"):
        lines.append(f"**Date:** {meta['date']}")
    if analysis.get("scripture_hint"):
        lines.append(f"**Scripture:** {analysis['scripture_hint']}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ── Component breakdown ──
    lines.append("## Sermon Component Breakdown")
    cb = analysis.get("component_breakdown", {})
    dur = cb.get("total_duration_seconds")
    wc  = cb.get("total_word_count")
    if dur:
        lines.append(f"**Total duration:** {fmt_duration(dur)}")
    if wc:
        lines.append(f"**Estimated word count:** {wc:,}")
    if dur or wc:
        lines.append("")

    totals = cb.get("component_totals", {})
    if totals:
        lines.append("| Component | Words | % of Sermon |")
        lines.append("|-----------|------:|------------:|")
        for comp in COMPONENT_TYPES:
            t = totals.get(comp, {})
            w = t.get("word_count", "—")
            p = t.get("percent", "—")
            w_str = f"{w:,}" if isinstance(w, (int, float)) else str(w)
            p_str = f"{p:.0f}%" if isinstance(p, (int, float)) else str(p)
            lines.append(f"| {comp.capitalize()} | {w_str} | {p_str} |")
        lines.append("")

    digressions = cb.get("digressions", [])
    if digressions:
        lines.append("### Explicitly Marked Digressions")
        for d in digressions:
            label = d.get("label", "Digression")
            opening = d.get("opening_phrase", "")
            closing = d.get("closing_phrase", "")
            dw = d.get("word_count")
            dp = d.get("percent_of_sermon")
            size = f" — {dw:,} words ({dp:.0f}%)" if dw and dp else ""
            lines.append(f"**{label}**{size}")
            if opening:
                lines.append(f"> Opens: \"{opening}\"")
            if closing:
                lines.append(f"> Closes: \"{closing}\"")
            lines.append("")

    segments = cb.get("segment_map", [])
    if segments:
        lines.append("### Sermon Map")
        lines.append("| Segment | Words | % | Type | Summary |")
        lines.append("|---------|------:|--:|------|---------|")
        for seg in segments:
            label   = seg.get("label", "")
            sw      = seg.get("word_count", "")
            sp      = seg.get("percent_of_sermon", "")
            stype   = seg.get("type", "")
            summary = seg.get("summary", "")
            sw_str  = f"{sw:,}" if isinstance(sw, (int, float)) else str(sw)
            sp_str  = f"{sp:.0f}%" if isinstance(sp, (int, float)) else str(sp)
            lines.append(f"| {label} | {sw_str} | {sp_str} | {stype} | {summary} |")
        lines.append("")

    if cb.get("notes"):
        lines.append(f"*{cb['notes']}*")
        lines.append("")

    # ── Application assessment ──
    lines.append("---")
    lines.append("")
    lines.append("## Application Assessment")
    aa = analysis.get("application_assessment", {})
    verdict    = aa.get("verdict", "—")
    confidence = aa.get("confidence", "—")
    lines.append(f"**Verdict:** {verdict}   **Confidence:** {confidence}")
    lines.append("")

    overall = aa.get("overall_assessment")
    if overall:
        lines.append(overall)
        lines.append("")

    intended  = aa.get("intended_message")
    experienced = aa.get("experienced_message")
    if intended or experienced:
        lines.append("### Intended vs. Experienced Message")
        if intended:
            lines.append(f"**Intended:** {intended}")
        if experienced:
            lines.append(f"**Experienced (resistant listener):** {experienced}")
        lines.append("")

    established = aa.get("what_text_establishes", [])
    if established:
        lines.append("### What the Text Establishes")
        for e in established:
            lines.append(f"- {e}")
        lines.append("")

    apps = aa.get("applications", [])
    if apps:
        lines.append("### Applications and Textual Correspondence")
        lines.append("| Application | Level | Assessment |")
        lines.append("|-------------|-------|------------|")
        for a in apps:
            app   = a.get("application", "")
            lvl   = a.get("correspondence_level", "")
            label = a.get("level_label", "")
            evid  = a.get("evidence", "")
            lines.append(f"| {app} | {lvl} — {label} | {evid} |")
        lines.append("")
        # Flag any analogy weaknesses
        weaknesses = [(a.get("application",""), a.get("analogy_weakness","")) for a in apps if a.get("analogy_weakness")]
        if weaknesses:
            lines.append("### Analogy Weaknesses")
            for app, weakness in weaknesses:
                lines.append(f"**{app}:** {weakness}")
            lines.append("")

    strengths = aa.get("strengths", [])
    if strengths:
        lines.append("### Strengths")
        for s in strengths:
            lines.append(f"- {s}")
        lines.append("")

    concerns = aa.get("concerns", [])
    if concerns:
        lines.append("### Concerns")
        for c in concerns:
            lines.append(f"- {c}")
        lines.append("")

    # ── Congregation critique ──
    lines.append("---")
    lines.append("")
    lines.append("## Congregation Critique")
    cc = analysis.get("congregation_critique", {})
    present  = cc.get("critique_present", False)
    severity = cc.get("severity", "—")
    tone     = cc.get("overall_tone", "")
    purpose  = cc.get("pastoral_purpose", "")
    effect   = cc.get("rhetorical_effect", "")

    lines.append(f"**Critique present:** {'Yes' if present else 'No'}   **Severity:** {severity}")
    if tone:
        lines.append(f"**Overall tone:** {tone}")
    lines.append("")

    if purpose or effect:
        if purpose:
            lines.append(f"**Pastoral purpose:** {purpose}")
        if effect:
            lines.append(f"**Rhetorical effect (resistant listener):** {effect}")
        lines.append("")

    tb = cc.get("tone_breakdown", {})
    if tb and any(v is not None for v in tb.values()):
        lines.append("### Tone Breakdown of Critical Section(s)")
        if tb.get("warning_admonitory_percent") is not None:
            lines.append(f"- Warning / admonitory: {tb['warning_admonitory_percent']:.0f}%")
        if tb.get("pastoral_supportive_percent") is not None:
            lines.append(f"- Pastoral / supportive: {tb['pastoral_supportive_percent']:.0f}%")
        if tb.get("bridging_explanatory_percent") is not None:
            lines.append(f"- Bridging / explanatory: {tb['bridging_explanatory_percent']:.0f}%")
        exc = cc.get("legitimate_exceptions_acknowledged")
        if exc is not None:
            lines.append(f"- Legitimate exceptions acknowledged: {'Yes' if exc else 'No'}")
        lines.append("")

    instances = cc.get("instances", [])
    if instances:
        lines.append("### Instances and Suggested Alternatives")
        for inst in instances:
            quote   = inst.get("quote_or_paraphrase", "")
            concern = inst.get("concern_being_expressed", "")
            risk    = inst.get("rhetorical_risk", "")
            alt     = inst.get("winsome_alternative", "")
            lines.append(f"**Language used:** {quote}")
            lines.append(f"**Concern:** {concern}")
            if risk:
                lines.append(f"**Rhetorical risk:** {risk}")
            if alt:
                lines.append(f"**More winsome framing:** {alt}")
            lines.append("")

    # ── Application themes ──
    lines.append("---")
    lines.append("")
    lines.append("## Application Themes")
    at = analysis.get("application_themes", {})
    dominant = at.get("dominant_theme")
    if dominant:
        lines.append(f"**Dominant theme:** {dominant}")
        lines.append("")

    themes = at.get("themes", [])
    if themes:
        for t in themes:
            theme = t.get("theme", "")
            ttype = t.get("type", "")
            prominence = t.get("prominence", "")
            lines.append(f"- {theme} *({ttype}, {prominence})*")
        lines.append("")

    return "\n".join(lines)
