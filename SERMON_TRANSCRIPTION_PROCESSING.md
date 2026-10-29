# Sunday Sermon Transcription: How It Works Week to Week

This guide is for the AV team. It covers what happens on its own each Sunday, the one thing you need to do, and what to do when the Mac asks for help. Setting up a new computer is covered in [README.md](README.md).

---

## The short version

1. **Save each recording in the Sermons folder with the right name** (below).
2. **That's it.** The Mac checks for new recordings at **1 pm, 7 pm and 11 pm on Sundays**. It transcribes them, writes the documents, and puts them in the shared Google Drive folder.
3. **If a notification says "Review in Sermon Helper,"** double-click `Sermon Helper.command` and answer its questions. That usually takes two minutes.

Nobody has to start anything, and there's nothing to run first.

---

## 1. Saving the recording

Export from Audacity as MP3 into **Documents → Sermons → this year's folder**, e.g. `/Users/AVdept/Documents/Sermons/2026/`.

Name it with the date (**month, day, two-digit year**) and the service code:

| Service | Name for Sunday, November 1, 2026 |
|---|---|
| Morning sermon | `110126AM.mp3` |
| Evening sermon | `110126PM.mp3` |
| Higher Ed (adult Sunday School) | `110126HE.mp3` |
| A conference or special event | see [section 5](#5-conferences-and-other-special-events) |

- Upper or lower case both work, and anything after the code is ignored: `110126AM-final.mp3` is fine.
- `SS` instead of `HE` is accepted too, from when Higher Ed was called Sunday School.
- **Any other name is skipped.** A notification says so. Rename the file and it's picked up at the next check.

**Finish editing before the check if you can.** The Mac leaves a file alone until it hasn't changed for 10 minutes, so a file that's still being written isn't touched. If you replace a recording after it was processed, for example with a better export, it's redone at the next check, and the new documents replace the old ones in Google Drive.

---

## 2. What happens on its own

| Check | Usually picks up |
|---|---|
| **1 pm** | The morning sermon (service ends about 11:10) and Higher Ed |
| **7 pm** | Anything saved during the afternoon, or a Higher Ed class saved late |
| **11 pm** | The evening sermon (service ends about 6:15) |

At each check, for every new recording:

1. **Transcribes** the recording, word for word with timestamps. On this Mac that takes up to an hour per recording, so documents appear one to three hours after the check.
2. **Looks up the preaching schedule** (the pulpit Google Sheet) for the speaker, title and Scripture.
3. **Writes the documents:**
   - **Sermon:** summary, outline, Scripture notes, a cleaned-up transcript, and a short podcast description.
   - **Higher Ed:** class summary, lesson outline, a discussion guide and a short podcast description, all labeled Higher Ed (Adult Sunday School). These never name class members.
4. **Copies them to the shared Google Drive folder**, one folder per Sunday service, e.g. `Sermons/2026/2026-11-01 AM - Praising God's Justice (Pastor Joel E. Wood)`.
5. **Shows a notification** in the top-right corner of the screen, e.g. *"Transcribed 1: 110126AM.mp3"*.

**Don't want to wait for the next check?** Double-click **`Check for Recordings.command`** in the SermonTranscriber folder. It starts a check right away.

---

## 3. When a notification asks for help

| The notification says | What it means | What to do |
|---|---|---|
| *Transcribed 1: 110126AM.mp3* | All done | Nothing |
| *…Review in Sermon Helper: preacher initials 'SE' aren't in speaker_initials.csv* | The schedule's preacher wasn't recognized | Run Sermon Helper and pick the speaker (below) |
| *…Review in Sermon Helper: 11/1/26 AM isn't in the preaching schedule* | That Sunday's row is missing from the pulpit sheet | Run Sermon Helper and enter the speaker, title and passage |
| *Skipped sermon.mp3: name isn't MMDDYY + AM/PM/HE/SS, or a special event…* | The file name wasn't recognized | Rename it, e.g. `110126AM.mp3`. For an event session, check the code is in `special_events.csv` for that date |
| *Special events are off: special_events.csv line 29: …* | A mistake in the special events file | Tell Dean; that line needs fixing |
| *Problem processing 110126AM.mp3 — see logs/auto.log* | Something went wrong, usually the internet | Nothing at first: it tries again at the next check (at least two hours later), up to 3 times. If it keeps failing, tell Dean |
| *Couldn't copy … to Google Drive* | Google Drive isn't running or is signed out | Open **Google Drive** (in Applications) and make sure it's signed in as newlifeavdept@gmail.com. The files are copied at the next check |
| *Can't read the Sermons folder. It needs Full Disk Access* | A Mac permission was removed | Tell Dean |
| *Can't make sermon documents: no OpenAI API key* | The key is missing or expired | Tell Dean |

A sermon flagged "Review" **is not put in Google Drive** until someone confirms it in Sermon Helper, so a guessed or missing speaker never gets shared.

---

## 4. Sermon Helper: fixing or finishing a recording

Double-click **`Sermon Helper.command`** in the SermonTranscriber folder. Use it **after** the automatic check, never before:
- when a notification says "Review in Sermon Helper"
- to correct a finished sermon, e.g. a wrong title
- to process a recording the Mac skipped

It walks you through it with ordinary Mac dialog boxes:

1. **Pick the recording.** ⚠ marks the ones needing attention, and they're listed first. *Choose a different file…* opens any recording.
2. **Sermon or Higher Ed class?** It guesses from the name.
3. **Sermon:** pick the speaker. The schedule's preacher is pre-selected when there is one. *Other* lets you type a name, with title, e.g. *Pastor Joel E. Wood*. Then check the title and Scripture passage, which come pre-filled from the schedule.
   **Higher Ed:** enter the teacher, topic and passage. All three are optional and start filled in from last week's class.
4. **Make documents.** This takes about a minute, because the transcript is reused. A Terminal window shows progress; leave it open until it's done.
5. The last message says when the documents are ready and copied to Google Drive. *Show in Finder* opens the folder on this Mac.

What you enter is remembered, so if that recording is ever redone, your answers are used again.

---

## 5. Conferences and other special events

Conferences and other events the church hosts work the same way, with one step beforehand.

**Before the event,** Dean (or whoever looks after this Mac) adds one line per session to `special_events.csv` in the settings folder:

```
date,code,speaker,title,scripture,event
11/6/26,RC1,Dr. First Speaker,Title of the Friday Session,2 Timothy 3:14-17,Reformation Conference
11/7/26,RC1,Dr. Second Speaker,Title of the First Saturday Session,,Reformation Conference
11/7/26,RC2,Dr. First Speaker,Title of the Second Saturday Session,,Reformation Conference
```

The code is two letters for the event (RC = Reformation Conference) plus the session number for that day.

**During the event, save each session** in the Sermons folder as the date plus its code:

| Session | File name |
|---|---|
| Friday 11/6/26, evening | `110626RC1.mp3` |
| Saturday 11/7/26, first session | `110726RC1.mp3` |
| Saturday 11/7/26, second session | `110726RC2.mp3` |

- They're processed at the **Sunday 1 pm check**, or right away with **`Check for Recordings.command`**.
- The documents go in Google Drive under **Special Events**, e.g. `Special Events/2026/2026-11-07 Reformation Conference RC2 - <title> (<speaker>)`.
- If a session's speaker isn't in the file yet, it's flagged "Review in Sermon Helper" and held back from Drive, like a Sunday sermon.
- **Not recorded locally?** Dean can download the audio from the YouTube livestream, name it the same way, and put it in the Sermons folder.
- A file name with a code that isn't in `special_events.csv` for that date is skipped as a bad name. That catches typos like `RX1`.

---

## 6. Keeping the Mac ready

- **Putting it to sleep is fine.** The Mac wakes itself at 12:55 pm on Sundays, stays awake through the evening checks, and a check missed while it slept runs as soon as it wakes.
- **Please don't shut it down on Sundays.** If it is shut down, it turns itself on at 12:55 pm Sunday. Any other time, the recordings are processed when someone next turns it on and logs in.
- **Leave the AV account logged in.** The checks only run while someone is logged in. Switching users is fine.
- **Leave Google Drive running.** It's the cloud icon in the top menu bar.

---

## 7. Where everything is

| What | Where |
|---|---|
| Recordings | Documents → Sermons → year folder |
| Shared documents | Google Drive → My Drive → Sermon Transcripts (shared with the congregation) |
| All outputs on this Mac, including the full word-for-word transcript and caption files (`.vtt`, `.srt`) | The `output_dir` folder set in the settings, in a subfolder per year |
| The app | Home → Applications → SermonTranscriber |
| Settings, the speaker list and the logs | Home → Library → Application Support → SermonTranscriber |

The app updates itself when a new version is released. There's nothing to download.

---

## 8. Common questions

**The preacher was a guest who isn't in the list.** Choose *Other* in Sermon Helper and type their name with title. If they'll preach again, ask Dean to add their initials to the speaker list, so the schedule lookup recognizes them next time.

**The pulpit sheet had the wrong title.** Correct it in Sermon Helper. If the sheet itself is fixed before the 1 pm check, the right title is used automatically.

**A recording was saved with the wrong date.** Rename the file to the right date. It's processed under the new name at the next check. If documents were already made under the wrong date, ask Dean to remove that folder from Google Drive.

**Can I process an old recording?** Yes. Use Sermon Helper → *Choose a different file…*. The automatic checks only pick up recordings dated on or after the day the app was set up.

**Something's wrong and none of this helps.** Tell Dean, and if you can, send the file `logs/auto.log` from the settings folder (Home → Library → Application Support → SermonTranscriber → logs).
