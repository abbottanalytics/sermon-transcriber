#!/usr/bin/env python3
"""
Native macOS dialogs (via osascript) for Sermon Helper.

Every function returns None when the person clicks Cancel.

For testing, set SERMON_HELPER_ANSWERS to a JSON file holding a list of
answers; each dialog then takes the next answer instead of appearing (and
prints what it would have asked). An answer of null means Cancel.
"""

import json
import os
import subprocess
from pathlib import Path

TITLE = "Sermon Helper"
_CANCEL = "__CANCEL__"

_scripted = None
if os.getenv("SERMON_HELPER_ANSWERS"):
    _scripted = json.loads(Path(os.environ["SERMON_HELPER_ANSWERS"]).read_text())


def _replay(kind: str, prompt: str, options=None, default=None):
    if not _scripted:
        raise RuntimeError(f"Ran out of scripted answers at: {prompt!r}")
    answer = _scripted.pop(0)
    # A scripted choice may be just part of an option's text
    if options and answer is not None and answer not in options:
        answer = next((o for o in options if answer in o), answer)
    shown = f" options={options}" if options else ""
    print(f"[dialog:{kind}] {prompt!r}{shown} default={default!r} → {answer!r}")
    return answer


def _osascript(script: str, *args: str) -> str | None:
    """Run an AppleScript `on run argv` script; None if cancelled."""
    result = subprocess.run(["/usr/bin/osascript", "-e", script, *args],
                            capture_output=True, text=True)
    if result.returncode != 0:
        if "-128" in result.stderr:           # user cancelled
            return None
        raise RuntimeError(f"Dialog failed: {result.stderr.strip()}")
    out = result.stdout.rstrip("\n")
    return None if out == _CANCEL else out


def choose(prompt: str, options: list[str], default: str | None = None) -> str | None:
    """Pick one item from a list."""
    if _scripted is not None:
        return _replay("choose", prompt, options, default)
    script = f'''
    on run argv
        set opts to items 3 thru -1 of argv
        if item 2 of argv is "" then
            set picked to choose from list opts with title "{TITLE}" with prompt (item 1 of argv)
        else
            set picked to choose from list opts with title "{TITLE}" with prompt (item 1 of argv) default items {{item 2 of argv}}
        end if
        if picked is false then return "{_CANCEL}"
        return item 1 of picked
    end run'''
    return _osascript(script, prompt, default if default in options else "", *options)


def ask(prompt: str, default: str = "") -> str | None:
    """Type a line of text (pre-filled with default)."""
    if _scripted is not None:
        return _replay("ask", prompt, default=default)
    script = f'''
    on run argv
        set reply to display dialog (item 1 of argv) default answer (item 2 of argv) ¬
            with title "{TITLE}" buttons {{"Cancel", "OK"}} default button "OK" cancel button "Cancel"
        return text returned of reply
    end run'''
    value = _osascript(script, prompt, default or "")
    return None if value is None else value.strip()


def buttons(message: str, labels: list[str], default: str) -> str | None:
    """A message with up to three buttons; returns the label clicked.
    A label named "Cancel" acts as cancel (returns None)."""
    if _scripted is not None:
        answer = _replay("buttons", message, labels, default)
        return None if answer == "Cancel" else answer
    quoted = ", ".join(f'"{label}"' for label in labels)
    cancel = ' cancel button "Cancel"' if "Cancel" in labels else ""
    script = f'''
    on run argv
        set reply to display dialog (item 1 of argv) with title "{TITLE}" ¬
            buttons {{{quoted}}} default button "{default}"{cancel}
        return button returned of reply
    end run'''
    return _osascript(script, message)


def info(message: str):
    buttons(message, ["OK"], "OK")


def choose_file(prompt: str, start_dir: Path | None = None) -> Path | None:
    """Pick an audio file."""
    if _scripted is not None:
        answer = _replay("choose_file", prompt, default=str(start_dir) if start_dir else None)
        return Path(answer) if answer else None
    script = f'''
    on run argv
        if item 2 of argv is "" then
            set picked to choose file with prompt (item 1 of argv) of type {{"public.audio"}}
        else
            set picked to choose file with prompt (item 1 of argv) of type {{"public.audio"}} ¬
                default location (POSIX file (item 2 of argv))
        end if
        return POSIX path of picked
    end run'''
    start = str(start_dir) if start_dir and start_dir.is_dir() else ""
    value = _osascript(script, prompt, start)
    return Path(value) if value else None
