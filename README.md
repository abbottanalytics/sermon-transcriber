# Transcription & Summarization Pipeline

Converts audio recordings into structured documents using
[Whisper](https://github.com/openai/whisper) (speech-to-text) and GPT-4 (summarization).

Supports four content types — each produces a different set of outputs:

| Type | Outputs |
|------|---------|
| `sermon` | Cleaned transcript, outline, summary, scripture inference, podcast and YouTube descriptions |
| `meeting` | Cleaned transcript, minutes, summary, action items, motions |
| `talk` | Cleaned transcript, outline, summary, podcast and YouTube descriptions |
| `class` | Higher Ed (adult Sunday School): cleaned transcript, class summary, lesson outline, discussion guide, podcast description |

---

## Install (any Mac, Intel or Apple Silicon)

Paste into Terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/abbottanalytics/sermon-transcriber/main/install.sh | bash
```

This puts the code in `~/Applications/SermonTranscriber` and gives it its own Python 3.12, packages and ffmpeg via [uv](https://docs.astral.sh/uv/) — nothing system-wide, no Homebrew, no python.org download. It also creates the [settings folder](#settings-folder) and pre-downloads the Whisper model (about 1.5 GB). The only prerequisite is git: if Apple's Command Line Tools aren't installed, the installer opens Apple's install window and asks you to run it again afterwards.

The one thing left to do by hand is add the **OpenAI API key** (see below).

### Updating

Double-click `update.command` in the install folder, or run `./update.sh`. An installed copy follows the newest **release tag** (`v1.0.0`, `v1.1.0`, …), so day-to-day commits to `main` never reach the church computers until a release is tagged. Running it again when nothing changed does nothing. To hold a machine at one version: `SERMON_TRANSCRIBER_REF=v1.0.0 ./update.sh`.

### Releasing (maintainer)

```bash
uv lock                       # after changing dependencies in pyproject.toml
git tag v1.1.0 && git push origin main --tags
```

Dependencies and the Python version are pinned in `pyproject.toml` + `uv.lock`. Both Mac types are locked; Intel Macs are held at PyTorch 2.2.2 (the last Intel build), NumPy 1.x and numba 0.62 — see the comments in `pyproject.toml`.

### Development checkout

In your own git checkout, `./update.sh` only syncs the environment (`.venv/`) and never moves your code. The launchers use `.venv/` when it exists and fall back to `python3` on your PATH otherwise.

---

## ⚠️ OpenAI API Key — Required

This pipeline uses OpenAI's services for transcription cleanup and summarization. **It will not run without an API key.** Each person or organization running this pipeline needs their own key.

**To get a key:**
1. Go to [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
2. Sign in or create a free account
3. Click **Create new secret key**
4. Copy the key — it starts with `sk-`

**Cost:** Keys are pay-as-you-go. A typical sermon (~45 min) costs roughly **$0.02–$0.05** to process. There is no monthly fee — you only pay for what you use.

**To set your key — two options:**

1. **`config.txt` (recommended for most users):** add `api_key=sk-...` to your `config.txt` file. The pipeline reads it automatically on every run.

2. **Shell environment variable (for developers):** set `OPENAI_API_KEY` in your `~/.zshrc`. If this is already set, the pipeline uses it and ignores any `api_key=` value in `config.txt`. This is how the pipeline author typically runs it.

The lookup order is: shell environment first, then `config.txt`. This means developers can manage their key the usual way, while non-developers just fill in `config.txt` and never touch the shell.

> **Keep your key private.** Anyone with your key can charge usage to your account. Do not share `config.txt`, email it, or post it anywhere.

---

## Settings folder

Everything specific to one computer lives **outside the code folder**, in:

```
~/Library/Application Support/SermonTranscriber/
    config.txt              # API key, default folders, enabled content types
    preachers.txt           # Speaker menu with counts (auto-updated)
    events.txt              # Selectable service and event names
    speaker_initials.csv    # Preaching schedule initials → full speaker names
    schedule_overrides.csv  # Speaker fixes for blank schedule cells
    schedules/              # Preaching schedule CSVs
```

The folder and its files are created automatically the first time you run the pipeline, from the starter copies in `templates/`. Updating the code never overwrites them, so each computer keeps its own key, folders and speaker list. (If an older install kept `config.txt`, `preachers.txt`, `events.txt` or `schedules/` in the code folder, those are copied over on first run.)

To use a different settings folder — for testing, say — set `SERMON_TRANSCRIBER_HOME=/path/to/folder` before running.

To open the folder in Finder:
```bash
open ~/Library/Application\ Support/SermonTranscriber
```

## First-time setup

1. Run the pipeline once (any option below) — it creates the settings folder and stops if no API key is set
2. Open `config.txt` in the settings folder and fill in your API key and directory paths:
   ```
   api_key=sk-paste-your-key-here
   input_dir=/Users/yourname/Documents/Church/Sermons/Audio
   output_dir=/Users/yourname/Documents/Church/Sermons/Output
   ```
3. Save the file — setup is complete

> `config.txt` is readable only by your user account and never lives in the code folder, so your key can't be committed or shared by accident. `templates/config.txt.example` — no key, placeholder paths — is what ships with the code.

---

## Running the pipeline

### Option 1: Interactive menu (recommended for regular use)
```bash
./run_interactive.sh
```
Asks you questions step by step, then runs the pipeline. No flags to remember.

### Option 2: Double-click (for handing off to others)
Double-click `run_pipeline.command` in Finder. Terminal opens and walks you through the steps — native macOS file/folder picker dialogs open automatically for selecting input files, output folder, and agenda, so no typing or dragging of paths is needed.

> **First-time only:** macOS will block the file the very first time. Right-click → Open instead of double-clicking, then confirm in the dialog. After that, double-clicking works normally.

### Option 3: Direct command line

#### Single file
```bash
# Audio input — Whisper transcribes first, then processes
python3 run_pipeline.py sermon.mp3 --type sermon
python3 run_pipeline.py meeting.mp3 --type meeting
python3 run_pipeline.py talk.mp3 --type talk
python3 run_pipeline.py talk.mp4 --type talk      # video works too (Whisper reads the audio track)
python3 run_pipeline.py 110126HE.mp3 --type class --speaker "Elder Smith"   # Higher Ed class; --speaker is the teacher

# Existing transcript — skip Whisper
python3 run_pipeline.py sermon.txt --type sermon
```

#### Batch directory
```bash
# Process all mp3/m4a/wav and mp4/mov/m4v/mkv/webm files in a folder (and subfolders;
# a video is skipped if an audio file with the same name sits next to it)
# .txt-only files are included when no matching audio file exists
python3 run_pipeline.py ./sermons/ --type sermon
python3 run_pipeline.py ./sermons/ ./more_sermons/ --type sermon
```

#### Meeting-specific options
```bash
# Include an agenda (aligns minutes to agenda items)
python3 run_pipeline.py meeting.mp3 --type meeting --agenda agenda.docx

# Control minutes verbosity: minimal, normal (default), verbose
python3 run_pipeline.py meeting.mp3 --type meeting --style verbose
```

#### Other options
```bash
# Write outputs to a specific folder instead of next to the input files
python3 run_pipeline.py sermon.mp3 --type sermon --output-dir ./outputs/

# Overwrite existing output files (default: skip if outputs exist)
python3 run_pipeline.py sermon.mp3 --type sermon --overwrite

# Skip Whisper (audio file already has a matching .txt transcript)
python3 run_pipeline.py sermon.mp3 --type sermon --skip-whisper
```

### Option 4: Automatic (church AV computer)

A background agent checks the recordings folder on **Sundays at 1 pm, 7 pm and 11 pm**, after the morning service, Higher Ed and the evening service. It processes anything new on its own: no one has to start it. To check right away, for example after a special event on another day, double-click **`Check for Recordings.command`**.

> **For the AV team:** [SERMON_TRANSCRIPTION_PROCESSING.md](SERMON_TRANSCRIPTION_PROCESSING.md) explains what happens each Sunday, how to name recordings, and what to do with each notification. This section covers setting it up.

**What it picks up:** files named `MMDDYY` + a service code, upper or lower case, with anything after the code ignored:

| Name | Treated as |
|------|-----------|
| `110126AM.mp3`, `110126PM.mp3` | Sermon: transcript plus all sermon documents, with the speaker, title and Scripture from the [preaching schedule](#connecting-the-google-sheet) |
| `110126HE.mp3`, `110126SS.mp3` | Higher Ed class: transcript, plus a class summary, lesson outline and discussion guide in which class members aren't named. The teacher is `higher_ed_teacher` from `config.txt` if set, or whoever is entered in Sermon Helper |
| `110726RC2.mp3` and other [special event](#special-events-conferences) codes | A conference session listed in `special_events.csv`: processed like a sermon, published under Special Events |
| anything else | Not processed. A notification says it was skipped |

**Set it up**, in the install folder:

1. In `config.txt` in the settings folder, set `watch_dir` (e.g. `/Users/AVdept/Documents/Sermons`), `output_dir` and `api_key`, and [connect the Google Sheet](#connecting-the-google-sheet). To share the results, also set up [publishing to Google Drive](#publishing-to-google-drive).
2. Check what it would do. Nothing is processed:
   ```bash
   .venv/bin/python3 auto_transcribe.py --dry-run
   ```
3. Start the agent:
   ```bash
   ./agent.sh install
   ```
   On its first run it sets `process_from` to that day, so older recordings in the folder are left alone. To process some older ones, set `process_from` to an earlier date.

**Full Disk Access.** macOS doesn't let background programs read the Documents folder until someone allows it. If `watch_dir` is under Documents, `agent.sh install` notices that access is blocked, opens **System Settings → Privacy & Security → Full Disk Access**, and shows the `SermonTranscriberAgent` program in Finder. Click **+**, add it, then run `./agent.sh run-now`. This is needed once: the permission belongs to that one small program, which updates never rebuild.

**Keeping it running unattended:**
- **Automatic login** (System Settings → Users & Groups) for the AV account. The agent only runs while someone is logged in, so after a restart it waits at the login screen without this. macOS doesn't allow automatic login while FileVault is on.
- **`./agent.sh power-schedule`** (needs an admin password) wakes the Mac every Sunday at 12:55 pm, or powers it on if someone shut it down. macOS allows only one repeating wake time, so each Sunday check keeps the Mac awake until the next one; choosing Sleep or shutting down still works.
- **Check times** are the `run_times` setting in `config.txt` (default `Sun 13:00, Sun 19:00, Sun 23:00`). After changing it, run `./agent.sh install` and `./agent.sh power-schedule` again.
- **Missed checks catch up.** A check missed while the Mac slept runs as soon as it wakes, and the agent also checks when someone logs in, so a Mac that was off on Sunday catches up when it's next turned on.
- **Shutdowns mid-run are safe.** A recording counts as done only when every output is written. If the transcript already exists, a re-run skips straight to the summaries.

**When something needs a person, use Sermon Helper.** The agent's notification says when a sermon needs review, for example "preacher initials 'SE' aren't in speaker_initials.csv". To fix it, double-click **`Sermon Helper.command`** in the install folder. Plain Mac dialogs walk you through it:

1. **Pick the recording.** Recent recordings are listed, with ⚠ ones (needing a person) first. *Choose a different file…* handles any recording, including one with an unusual name that the agent skips.
2. **Type:** Sermon (the default) or Higher Ed class. A class asks for the teacher, topic and passage instead of steps 3–4. All three are optional and start filled in from the previous class, since a series usually keeps the same teacher.
3. **Speaker:** the preaching schedule's preacher is pre-selected when there is one. Otherwise pick from the speaker list, or choose *Other* to type a name.
4. **Title** and **Scripture:** pre-filled from the schedule, and editable.
5. **Make documents.** The existing transcript is reused, so this takes about a minute. If [Drive publishing](#publishing-to-google-drive) is set up, the corrected documents are published, replacing any earlier copy.

What you confirm is saved, and it's used again if the agent ever redoes that recording, for example after the file is replaced. The speaker you pick counts toward the speaker menu, the same as in the Terminal menus. To stop a whole name from being flagged again, add the initials to `speaker_initials.csv`.

**Day to day:**
```bash
./agent.sh status      # running? last result, recent activity
./agent.sh run-now     # check right now (same as Check for Recordings.command)
./agent.sh uninstall   # stop it (settings and outputs are kept)
```
- What happened to each recording is in `processed.json` in the settings folder. `logs/auto.log` has a summary; `logs/agent.log` has full output.
- A recording that fails is retried up to 3 times, 2 hours apart, then left for a person, with a notification each time.
- Replacing a recording with a corrected file (different size or date) processes it again.
- Installed copies update themselves once a day, as part of the agent's run.

---

## Configuration

Edit `config.txt` in the settings folder (plain text, any text editor) to configure the pipeline:

```
api_key=sk-...                # Your OpenAI API key
input_dir=/Users/yourname/... # Default input folder
output_dir=/Users/yourname/.. # Default output folder
schedule_file=                # Default preaching schedule CSV (optional)

enable_sermons=true           # Show/hide Sermon option in the menu
enable_classes=true           # Show/hide Higher Ed class option in the menu
enable_talks=true             # Show/hide Talk option in the menu
enable_meetings=true          # Show/hide Meeting option in the menu
```

**Content type toggles:** set any of the `enable_*` values to `false` to remove that option from the menu entirely. A church AV team that only processes sermons would set `enable_talks=false` and `enable_meetings=false` — the menu then shows only "Sermon" with no other choices to confuse things.

**API key:** the value in `config.txt` is used unless `OPENAI_API_KEY` is already set in your shell environment (in which case the shell value takes precedence).

**Directories:** used as defaults each run. Leave blank to be prompted each time.

---

## Speaker list

`preachers.txt` (in the settings folder) tracks every speaker who has been entered. Speakers with **2 or more entries** appear as a two-column numbered menu at the start of each sermon or talk run — select by number instead of typing. New names are always available as a typed entry and are added to the file automatically.

Titles are stored as part of the name (e.g. `Pastor Joel Wood`, `Dr. Jane Smith`, `Rev. John Doe`, `Intern Aaron Phillip`).

**How the count works:**
- The count increments **once per pipeline run**, not once per file — so processing a directory of 10 sermons by the same speaker adds only 1 to their count. The speaker is entered once for the whole batch.
- Once the count reaches **5+** it is capped and never incremented again, so reruns and large batches won't inflate it.
- To **remove someone from the menu**, delete their count in `preachers.txt` (leave the name with no `|`) or remove the line entirely.
- To **add someone manually**, add a line in the format `Full Name With Title|count`.

A new computer starts from `templates/preachers.txt.example`: the regular preachers at `|2` so they appear in the menu right away, and no one else.

---

## Preaching schedule lookup

The pulpit schedule supplies each sermon's **speaker, title and Scripture**. They're matched by date and service from the recording's `MMDDYY` + `AM`/`PM` filename, then shown at the top of every sermon document and used in the podcast description. The automatic job reads the schedule straight from its Google Sheet (`schedule_sheet`, see the next section). The menus and `--schedule` use a CSV exported from it (`schedule_file`).

**Reading the sheet:** columns are found by their header names (`AM Title`, `AM Preacher`, `PM Text`, …), so columns can be added or moved from year to year. Columns the reader doesn't use, such as Leader and Supper, are ignored. If the first three header cells have been typed over (the 2026 tab reads `cvv`, `cv`, `ynn b`), the reader falls back to columns A, B and C for Date, Event and AM Text. A cell holding two passages on separate lines is joined with "; ".

The schedule's Preacher columns usually hold initials, so two files in the settings folder translate them:

- **`speaker_initials.csv`**: one row per spelling the schedule uses, e.g. `jw,Pastor Joel E. Wood`. Matching ignores case, spaces and punctuation, so `JW`, `J W` and `JW?` all match. Add a row when a new preacher's initials start appearing. **Initials not in the file are never guessed into a name.** The speaker is left blank, and the automatic job flags the sermon for review, naming the initials. A written-out name, such as a guest's, is used as written.
- **`schedule_overrides.csv`**: for a date whose Preacher cell is blank but you know who preached, e.g. `122924,AM,Pastor Joel E. Wood`.

Test a lookup from the command line:
```bash
python3 schedule_lookup.py ~/Library/Application\ Support/SermonTranscriber/schedules/pulpit_schedule.csv 010724AM
```

---

## Connecting the Google Sheet

The pulpit sheet stays private. It's shared, as **Viewer**, with a Google *service account*: a robot Google identity with its own email address. A key file for that account on the computer lets the pipeline read the sheet unattended, without anyone signing in, and without a sign-in that expires. This is a one-time setup of about 10 minutes, in a web browser, signed in as `newlifeavdept@gmail.com` (or any Google account; the robot just needs to belong to one).

1. **Create a project.** Go to [console.cloud.google.com](https://console.cloud.google.com). Use the project picker at the top → **New project**, name it e.g. `Sermon Transcriber` → **Create**. Make sure it's the selected project afterwards.
2. **Turn on the Sheets API.** Search for **Google Sheets API** → **Enable**.
3. **Create the service account.** Go to **IAM & Admin → Service Accounts → Create service account**. Name it e.g. `sermon-reader`, then click **Done**. It needs no roles. Copy its email address, which looks like `sermon-reader@<project>.iam.gserviceaccount.com`.
4. **Create its key.** Click the service account → **Keys** tab → **Add key → Create new key → JSON**. A `.json` file downloads.
5. **Put the key on the computer.** Move that file into the settings folder and rename it `google_service_account.json`:
   ```bash
   open ~/Library/Application\ Support/SermonTranscriber
   ```
   Treat it like a password: anyone holding it can read whatever is shared with that robot account, which here is only the pulpit sheet.
6. **Share the sheet with the robot.** In the pulpit sheet, click **Share**, paste the service account's email, choose **Viewer**, untick **Notify people** → **Share**. This needs someone with sharing rights on the sheet.
7. **Tell the pipeline where the sheet is.** In `config.txt`, set `schedule_sheet=` to the sheet's URL, copied from the browser's address bar.
8. **Check it**, from the install folder:
   ```bash
   .venv/bin/python3 google_sheet.py check        # "Connected as …", then the tab names
   .venv/bin/python3 google_sheet.py show 2026    # the 2026 schedule as the pipeline reads it
   ```

Notes:
- **Tabs:** one per year. A 2026 recording uses the tab named `2026`, or failing that one whose name contains 2026. Start each new year's tab before its first Sunday.
- **Freshness:** the sheet is read every time sermons are processed, so a correction made Sunday afternoon is picked up that evening. Each read is saved as `schedules/sheet_<year>.csv`, and that copy is used if Google can't be reached.
- **Errors:** if `check` says the sheet *isn't shared with …*, repeat step 6 with the address it shows. Google accounts that belong to an organization sometimes block creating keys (step 4). A personal Gmail account like `newlifeavdept@gmail.com` doesn't.

## Publishing to Google Drive

Finished sermon documents can be copied to a shared Google Drive folder automatically, so anyone given the link can read them. The pipeline doesn't talk to Google for this. **Google Drive for Desktop**, signed in as the AV account, keeps a folder on the Mac in sync with Drive. The pipeline copies files into that folder, and Drive uploads them.

What appears in Drive, one folder per recording:

```
Sermon Transcripts/
  Sermons/2026/2026-11-01 AM - Praising God's Justice (Derek Rishmawy)/
      2026-11-01 AM Summary.docx
      2026-11-01 AM Outline.docx
      2026-11-01 AM Scripture.docx
      2026-11-01 AM Transcript.docx          (the cleaned transcript)
      2026-11-01 AM Podcast description.txt
  Higher Ed/2026/2026-11-01 Higher Ed - Romans (Elder Smith)/   (only with publish_classes=true)
      2026-11-01 Higher Ed Summary.docx
      2026-11-01 Higher Ed Outline.docx
      2026-11-01 Higher Ed Discussion guide.docx
      2026-11-01 Higher Ed Podcast description.txt
```

Whisper's raw working files (`.txt`, `.json`, `.tsv`) and the logs stay on the Mac.

**Set it up**, once, on the AV computer:

1. **Install Google Drive for Desktop** from [google.com/drive/download](https://www.google.com/drive/download/) and sign in as `newlifeavdept@gmail.com`. If macOS asks to allow its system extension, allow it. Drive then appears in Finder's sidebar under **Locations**.
2. **Make the folder.** In Finder, open **Google Drive → My Drive** and create a folder, e.g. `Sermon Transcripts`. You can make it at [drive.google.com](https://drive.google.com) instead; it shows up on the Mac within a minute.
3. **Tell the pipeline.** In Finder, select that folder and press **⌥⌘C** (Copy as Pathname). In `config.txt`, paste the path after `publish_dir=`. It looks like
   `publish_dir=/Users/AVdept/Library/CloudStorage/GoogleDrive-newlifeavdept@gmail.com/My Drive/Sermon Transcripts`
4. **Check it**, from the install folder:
   ```bash
   .venv/bin/python3 drive_publish.py check
   ```
5. **Optionally publish what's already finished.** Until then only new recordings are published:
   ```bash
   .venv/bin/python3 drive_publish.py backfill
   ```
6. **Share the folder.** At drive.google.com, right-click `Sermon Transcripts` → **Share**. Add people as **Viewer**, or set **General access** to *Anyone with the link*. Everything inside, including future sermons, is shared the same way.

**How it behaves:**
- **Only checked documents are published.** A sermon whose speaker is missing or guessed (the ⚠ ones) stays off Drive until someone confirms it in Sermon Helper, which then publishes it.
- **Corrections replace the old copy.** Redoing a recording updates its Drive folder. If the title or speaker changed, the folder gets the new name and the old one goes to Drive's trash. Files someone else added to a folder are left alone.
- **If Drive isn't running** (signed out, or the Mac started offline), the documents are still made, and they're copied on a later run. A daily notification says what's waiting.
- **Settings:** `publish_classes=true` also publishes the Higher Ed class documents. Those documents never name class members and leave out personal things people shared, but read a few before turning this on: it's off by default because the recording includes the whole room. A class's full transcript keeps everything that was said, so it's published only with `publish_class_transcripts=true` as well. `publish_captions=true` adds `.srt`/`.vtt` caption files with timestamps (for a class, only together with its transcript).
- The agent's Full Disk Access permission covers the Drive folder too.
- Leave `publish_dir` blank to turn publishing off.

---

## Special events (conferences)

Conferences and other events the church hosts aren't in the pulpit sheet. Their sessions are listed in **`special_events.csv`** in the settings folder, one line per session:

```
date,code,speaker,title,scripture,event
11/6/26,RC1,Dr. First Speaker,Title of the Friday Session,2 Timothy 3:14-17,Reformation Conference
11/7/26,RC1,Dr. Second Speaker,"Title, With a Comma",,Reformation Conference
11/7/26,RC2,Dr. First Speaker,Title of the Third Session,,Reformation Conference
```

- **Codes:** two letters per event plus a session number for the day: RC1, RC2, MC1… AM, PM, HE and SS are reserved for Sundays.
- **File names:** a recording named with the date and code, e.g. `110726RC2.mp3`, is processed as a sermon with that row's speaker, title, passage and event.
- **Unlisted codes:** a code is recognized only on the dates it's listed, so a typo is still skipped as a bad name. Add the rows before the event's recordings are processed.
- **Blank fields:** a blank speaker flags the recording for review in Sermon Helper and holds it back from Drive. A blank title or passage is just left out.
- **Drive:** published sessions go under `Special Events/<year>/` in the Drive folder.
- **YouTube description:** optional extra columns `conference`, `session` and `notes` (add them to the header line) fill in the conference title, a label like `Session One`, and a closing note in the session's `.youtube.txt`.
- **Checking the file:** `.venv/bin/python3 special_events.py` lists the sessions as the pipeline reads them, or names the line with a mistake. While the file has a mistake, special events are off and the agent sends a notification.

---

## Sermons from YouTube

The services are livestreamed to YouTube, which makes the livestream the last fallback when a sermon wasn't recorded on the AV Mac.

**`Sermon from YouTube.command`** (for the AV team, see the AV guide's section 5):

- Asks for Morning or Evening Worship and the Sunday, and finds the video by the date in its title (`Morning Worship Service: 25-October-2026; …`) in that service's playlist: New Life's, or `youtube_morning` / `youtube_evening` in config.txt.
- Downloads the audio, and suggests the sermon's start and end from YouTube's captions (`sermon_trim.py`: free, so the whole service isn't transcribed first). A person accepts or changes the times.
- Saves the cut as `MMDDYYAM.mp3` / `MMDDYYPM.mp3` in the watch folder's year folder (or Downloads, with no `watch_dir`). From there it's an ordinary recording: documents are made now through Sermon Helper's questions, or at the next automatic check.
- A special event's session, or any other video, from Terminal:
  ```bash
  .venv/bin/python3 youtube_sermon.py --url "<video link>" --name 110726RC2
  ```
  The name must be one the automatic job knows (for an event, listed in `special_events.csv`).

**`Download from YouTube.command`** (for the Senior Pastor, or anyone): paste a video, playlist or channel link and choose audio (`.m4a`) or video (`.mp4`, up to 720p). For a playlist: its newest video, or the last 7 or 30 days. Files go in `youtube_dir` (default `~/Downloads/YouTube`); one already there is skipped. From Terminal: `.venv/bin/python3 youtube_download.py get "<link>" [--video] [--newest 1 | --days 7]`.

**Installing just for downloads** (e.g. the Senior Pastor's Mac): the same install, without pre-downloading the Whisper model:

```bash
curl -fsSL https://raw.githubusercontent.com/abbottanalytics/sermon-transcriber/main/install.sh | SKIP_MODEL_DOWNLOAD=1 bash
```

No API key, schedule or agent is needed for downloading. (The install still includes the transcription packages, about 1 GB, so the same Mac can transcribe later.)

**yt-dlp** isn't pinned with the other packages: YouTube changes often enough that a copy a few weeks old can stop working. Each run uses the newest yt-dlp through `uv tool run` (with Deno, which yt-dlp needs for YouTube, and the bundled ffmpeg); `update.sh` fetches it ahead of time.

---

## Events list

`events.txt` (in the settings folder) contains the selectable service and event names, organized into two sections:

- `[sermon]` — worship services and church events (pre-populated)
- `[talk]` — conference and presentation events (add your own)

To add a new recurring event, open `events.txt` in any text editor and add a line under the appropriate section. One-off events can always be typed in at runtime.

---

## YouTube description

Sermons and talks also get `<name>.youtube.txt`, ready to paste into a YouTube video's description:

```
RefCon 2026
Host: New Life Presbyterian Church of La Mesa — https://www.newlifelamesa.org
Reforming Holiness: The Fire of Glory
Dr. Derek Rishmawy
Session One: Reforming Our View of Spirituality

<one-sentence summary>

Chapters
0:00 Welcome
0:23 <first main point>
12:41 <second main point>

<notes, if any>
```

The lines are `--event`, the host, `--conference`, `--speaker`, `--session`: `--title`; any that aren't given are left out. Each main outline point (I, II, III…) starts at the Whisper segment where the speaker begins it, so chapters need the `.srt` Whisper writes (an outline with more than 12 main points is grouped into at most 12 chapters, each starting at its first point); Whisper's "Thank you." in silence and applause is ignored. YouTube makes chapters only when the first is `0:00`, there are at least 3, they go up and each lasts 10 s or more: points closer together than that are merged, and if the rules still aren't met the description is written without chapters and a warning is printed.

When the video has an intro (title slides) before the talk:

```bash
# Transcribing the finished video: the talk starts 23 s in
python3 run_pipeline.py "RefCon 2026 - Session 1.mp4" --type talk --intro-length 23 \
    --event "RefCon 2026" --conference "Reforming Holiness: The Fire of Glory" \
    --speaker "Dr. Derek Rishmawy" --session "Session One" \
    --title "Reforming Our View of Spirituality" --notes-file audio_note.txt

# Transcript of the talk alone, video with a 23 s intro: shift every time by 23 s
python3 run_pipeline.py lecture1.mp3 --type talk --timestamp-offset 23 ...
```

`0:00 Welcome` covers the intro and the first point starts at the talk. `--notes` (or `--notes-file`) adds a closing paragraph, e.g. an apology for audio problems.

---


## Output files

Outputs are written next to the input transcript (or to `--output-dir` if specified). For a file named `081912AM-Genesis.txt`:

**Sermon:**
- `081912AM-Genesis.cleaned.docx` — corrected, structured transcript
- `081912AM-Genesis.outline.docx` — Roman-numeral outline
- `081912AM-Genesis.summary.docx` — 1–2 page summary
- `081912AM-Genesis.scripture.docx` — inferred Scripture passage(s) with confidence
- `081912AM-Genesis.podcast.txt` — 2–3 sentence podcast episode description
- `081912AM-Genesis.youtube.txt` — YouTube description with chapters (see [YouTube description](#youtube-description))

All sermon documents include a **Speaker** and **Event** header at the top when those values are provided.

**Meeting:**
- `meeting.cleaned.docx` — corrected transcript
- `meeting.minutes.docx` — formal minutes (aligned to agenda if provided)
- `meeting.meeting_summary.docx` — key decisions and discussion topics
- `meeting.actions.docx` — action items checklist
- `meeting.motions.docx` — formal motions with mover/seconder/result
- `meeting.motions_and_actions.txt` — combined plain text version

**Talk:**
- `talk.cleaned.docx` — corrected transcript
- `talk.outline.docx` — structured outline
- `talk.summary.docx` — summary with key arguments and takeaways
- `talk.podcast.txt` — 2–3 sentence podcast episode description
- `talk.youtube.txt` — YouTube description with chapters (see [YouTube description](#youtube-description))

All talk documents include a **Speaker**, **Title**, and **Event** header when provided.

**Class** (Higher Ed / adult Sunday School):
- `110126HE.cleaned.docx` — corrected transcript (everything said in the room)
- `110126HE.summary.docx` — topic and text, the teaching, the discussion, Scripture referenced, takeaways
- `110126HE.outline.docx` — the lesson as the teacher led it, with discussion points marked
- `110126HE.discussion.docx` — questions raised in class, questions left open, and new questions for reflection
- `110126HE.podcast.txt` — 2–3 sentence description starting "*Teacher* teaching on *topic* in Higher Ed (Adult Sunday School)."

The summary, outline and discussion guide don't name class members ("a participant") and leave out personal details people shared, such as prayer requests. They carry a **Teacher**, **Topic** and **Scripture** header when provided, and an **Event** header that always says Higher Ed (Adult Sunday School) unless `--event` gives another. The file name doesn't matter: any recording run as a class gets all of this, whether it comes from the automatic job, Sermon Helper, the `run_pipeline.command` menu (*Higher Ed class*) or `run_pipeline.py --type class`.

---

## Code structure

```
run_pipeline.py                # Main entry point — handles all content types
pipeline_helpers.sh            # Shared bash functions (config, speaker list, event list)
app_home.py                    # Locates / creates the per-machine settings folder
schedule_lookup.py             # Preaching schedule rows → speaker, title, scripture
google_sheet.py                # Reads the schedule from its Google Sheet (service account)
transcription_summary_core.py  # Shared utilities: LLM calls, chunking, file I/O, transcript cleaning
sermon_summary.py              # Sermon-specific processing
class_summary.py               # Higher Ed class processing (participants kept anonymous)
meeting_summary.py             # Meeting-specific processing
talk_summary.py                # Talk/conference-specific processing
templates/                     # Starter settings files copied to a new computer's settings folder
install.sh / update.sh         # Install on a new Mac / bring a copy up to date (uv)
auto_transcribe.py             # Automatic job: scan watch_dir, process new recordings, ledger
recording_names.py             # MMDDYY + AM/PM/HE/SS filename rules
auto_run.sh                    # What the agent runs: daily update, then auto_transcribe.py
agent.sh                       # Install / remove / check the launchd agent
agent_launcher.c               # Small program the agent runs (holds the Full Disk Access permission)
Sermon Helper.command          # Double-click: fix or finish one recording in Mac dialogs
Check for Recordings.command   # Double-click: run a check now instead of waiting for the next one
agent_schedule.py              # run_times → the agent's schedule and Sunday stay-awake timer
SERMON_TRANSCRIPTION_PROCESSING.md  # Week-to-week guide for the AV team
sermon_helper.py / mac_dialogs.py  # Sermon Helper itself / the native dialog helpers
drive_publish.py               # Copies finished documents into the Google Drive folder
special_events.py              # Conference / special event sessions (special_events.csv)
youtube_description.py         # <name>.youtube.txt: description + chapters from the outline and .srt
test_youtube_description.py    # python3 -m unittest test_youtube_description
youtube_download.py            # yt-dlp: find a service in its playlist; Download from YouTube.command
sermon_trim.py                 # Sermon start/end from YouTube captions; cut the audio to the sermon
youtube_sermon.py              # Sermon from YouTube.command: service + Sunday → MMDDYYAM.mp3
```

The older runner scripts (`run_sermon_summary.py`, `run_meeting_summary.py`,
`run_full_pipeline.py`) still work but `run_pipeline.py` replaces them all.

---

## Whisper models

The pipeline uses the `turbo` Whisper model — fast and accurate for clear
recordings. To change it, edit the `--model` line in `run_pipeline.py`
(inside `run_whisper`), e.g. `small`, `medium`, or `large`.

---

## Cost notes

Processing uses `gpt-4.1-mini`. A typical sermon (~45 min, ~6 000 words)
costs roughly $0.02–$0.05 to process all four outputs. Meeting processing
is similar.
