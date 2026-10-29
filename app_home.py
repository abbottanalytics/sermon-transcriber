#!/usr/bin/env python3
"""
Per-machine settings folder.

Everything that differs from one computer to the next lives outside the
code folder, so updating the code (git pull) never touches it:

    ~/Library/Application Support/SermonTranscriber/
        config.txt              API key, default folders, enabled content types
        preachers.txt           Speaker menu with counts (auto-updated)
        events.txt              Selectable service / event names
        speaker_initials.csv    Schedule initials → full speaker names
        schedule_overrides.csv  Speaker fixes for blank schedule cells
        special_events.csv      Conference / special event sessions
        schedules/              Preaching schedule CSVs

Set SERMON_TRANSCRIBER_HOME to use a different folder (e.g. for testing).

On first use each missing file is created from templates/<name>.example,
or copied from the code folder if an older install kept it there.

USAGE (from bash — prints the folder path):
    APP_HOME="$(python3 app_home.py)"

USAGE (as a module):
    from app_home import data_file
    path = data_file("speaker_initials.csv")
"""

import os
import shutil
import sys
from pathlib import Path

CODE_DIR      = Path(__file__).resolve().parent
TEMPLATES_DIR = CODE_DIR / "templates"
DEFAULT_HOME  = Path.home() / "Library" / "Application Support" / "SermonTranscriber"

# Files created on first use. Older installs kept the first three
# in the code folder; those copies are carried over when present.
DATA_FILES  = ["config.txt", "preachers.txt", "events.txt",
               "speaker_initials.csv", "schedule_overrides.csv", "special_events.csv"]
LEGACY_FILES = {"config.txt", "preachers.txt", "events.txt"}

# Holds the API key — readable by this user only.
PRIVATE_FILES = {"config.txt"}


def app_home() -> Path:
    """Return the settings folder path (without creating it)."""
    override = os.getenv("SERMON_TRANSCRIBER_HOME", "").strip()
    return Path(override).expanduser() if override else DEFAULT_HOME


def ensure() -> Path:
    """Create the settings folder and any missing files. Returns its path."""
    home = app_home()
    home.mkdir(parents=True, exist_ok=True)

    for name in DATA_FILES:
        target = home / name
        if target.exists():
            continue
        legacy = CODE_DIR / name
        source = legacy if name in LEGACY_FILES and legacy.is_file() \
            else TEMPLATES_DIR / f"{name}.example"
        shutil.copyfile(source, target)
        if name in PRIVATE_FILES:
            target.chmod(0o600)

    schedules = home / "schedules"
    if not schedules.exists():
        legacy_schedules = CODE_DIR / "schedules"
        if legacy_schedules.is_dir():
            shutil.copytree(legacy_schedules, schedules)
        else:
            schedules.mkdir()

    return home


def data_file(name: str) -> Path:
    """Path to a file in the settings folder, creating defaults if needed."""
    return ensure() / name


# The template's api_key value — never a real key.
PLACEHOLDER_API_KEY = "sk-paste-your-key-here"


def read_config() -> dict:
    """
    Parse config.txt (key=value lines, # comments) the same way
    pipeline_helpers.sh does: whitespace and surrounding quotes stripped.
    """
    config = {}
    for line in data_file("config.txt").read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        for quote in ('"', "'"):
            if len(value) >= 2 and value[0] == value[-1] == quote:
                value = value[1:-1]
        config[key.strip()] = value
    if config.get("api_key") == PLACEHOLDER_API_KEY:
        config["api_key"] = ""
    return config


def set_config_value(key: str, value: str):
    """Set key=value in config.txt, replacing an existing line or appending one."""
    path = data_file("config.txt")
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if not line.lstrip().startswith("#") and line.split("=", 1)[0].strip() == key:
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    try:
        print(ensure())
    except OSError as e:
        print(f"ERROR: could not set up settings folder {app_home()}: {e}",
              file=sys.stderr)
        sys.exit(1)
