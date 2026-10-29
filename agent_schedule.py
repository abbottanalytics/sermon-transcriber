#!/usr/bin/env python3
"""
When the background agent runs: the run_times setting in config.txt.

    run_times=Sun 13:00, Sun 19:00, Sun 23:00     (the default)

Each entry is a day and a 24-hour time. The agent also runs at login, so a
Mac that was shut down catches up when it's next turned on, and macOS runs a
time that was missed while the Mac slept as soon as it wakes.

agent.sh reads this to write the launchd schedule (re-run ./agent.sh install
after changing run_times), and auto_run.sh uses it to keep the Mac awake from
one run to the next on the same day, so the evening runs aren't left waiting
for someone to wake the Mac.

USAGE:
    python3 agent_schedule.py show                # the schedule, in words
    python3 agent_schedule.py launchd             # launchd StartCalendarInterval, as JSON
    python3 agent_schedule.py stay-awake-seconds  # until the next run today (0 if none)
    python3 agent_schedule.py wake-time           # pmset "<day> HH:MM:SS" for the first run
"""

import json
import re
import sys
from datetime import datetime, timedelta

DEFAULT_RUN_TIMES = "Sun 13:00, Sun 19:00, Sun 23:00"
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]      # Python's weekday() order
PMSET_DAYS = "MTWRFSU"                                       # same order, pmset's letters
WAKE_EARLY_MINUTES = 5          # pmset wakes the Mac this long before the first run
STAY_AWAKE_EXTRA_MINUTES = 15   # and the Mac is kept awake this long past the next run


class ScheduleError(ValueError):
    pass


def parse_run_times(value: str | None) -> list[tuple[int, int, int]]:
    """'Sun 13:00, Sun 19:00' → [(weekday, hour, minute), ...], Monday = 0."""
    runs = []
    for item in (value or DEFAULT_RUN_TIMES).split(","):
        m = re.fullmatch(r"\s*([A-Za-z]{3})[a-z]*\s+(\d{1,2}):(\d{2})\s*", item)
        if not m or m.group(1).lower() not in DAYS:
            raise ScheduleError(f"run_times entry {item.strip()!r} isn't like 'Sun 13:00'")
        hour, minute = int(m.group(2)), int(m.group(3))
        if hour > 23 or minute > 59:
            raise ScheduleError(f"run_times entry {item.strip()!r} isn't a valid time")
        runs.append((DAYS.index(m.group(1).lower()), hour, minute))
    return sorted(set(runs))


def describe(runs) -> str:
    return ", ".join(f"{DAYS[d].title()} {h:d}:{m:02d}" for d, h, m in runs)


def launchd_intervals(runs) -> list[dict]:
    # launchd counts weekdays from Sunday = 0
    return [{"Weekday": (d + 1) % 7, "Hour": h, "Minute": m} for d, h, m in runs]


def stay_awake_seconds(runs, now: datetime | None = None) -> int:
    """Seconds to keep the Mac awake: until shortly after the next run later
    today, or 0 if there's no other run today."""
    now = now or datetime.now()
    later = [now.replace(hour=h, minute=m, second=0, microsecond=0)
             for d, h, m in runs if d == now.weekday()]
    later = [t for t in later if t > now]
    if not later:
        return 0
    until = min(later) + timedelta(minutes=STAY_AWAKE_EXTRA_MINUTES)
    return int((until - now).total_seconds())


def wake_time(runs) -> str:
    """pmset repeat allows one wake time: shortly before the week's first run."""
    d, h, m = runs[0]
    wake = datetime(2000, 1, 3 + d, h, m) - timedelta(minutes=WAKE_EARLY_MINUTES)  # 2000-01-03 is a Monday
    return f"{PMSET_DAYS[wake.weekday()]} {wake:%H:%M:%S}"


def main():
    from app_home import read_config
    command = sys.argv[1] if len(sys.argv) > 1 else "show"
    try:
        runs = parse_run_times(read_config().get("run_times"))
    except ScheduleError as e:
        sys.exit(f"ERROR: {e} (in config.txt)")
    if command == "show":
        print(describe(runs))
    elif command == "launchd":
        print(json.dumps(launchd_intervals(runs)))
    elif command == "stay-awake-seconds":
        print(stay_awake_seconds(runs))
    elif command == "wake-time":
        print(wake_time(runs))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
