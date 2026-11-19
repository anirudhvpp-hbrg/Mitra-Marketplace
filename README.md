# Mitra Marketplace

A suite of small, private apps that run entirely on your own computer. Type `mitra-marketplace` in any terminal: a welcome screen opens, and behind it are your apps as icons. Each app is its own program, started when you click its icon and gone a few seconds after you close its window. Nothing leaves the device. Local AI models are loaded only for the request that needs them, one at a time, inside a 1 GB memory ceiling.

Version 0.10.0. Built and tested on Windows 11; macOS, Linux and Android Termux are design targets that have not been run yet.

- [What works and what does not](#what-works-and-what-does-not)
- [The apps](#the-apps)
- [Architecture](#architecture)
- [The rules the system keeps](#the-rules-the-system-keeps)
- [Models and runtimes](#models-and-runtimes)
- [TwinMind in detail](#twinmind-in-detail)
- [Install, build, run](#install-build-run)
- [Commands](#commands)
- [Settings](#settings)
- [The memory log](#the-memory-log)
- [Tests](#tests)
- [Repository layout](#repository-layout)
- [Roadmap](#roadmap)

Deeper documents: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (every part, flow and measurement), [`docs/architecture.html`](docs/architecture.html) (the same as an interactive page), [`docs/wireframes.html`](docs/wireframes.html) (every screen and state), [`TEST_PLAN.md`](TEST_PLAN.md), [`APP_SPEC.md`](APP_SPEC.md) (how to write an app), [`docs/BUILD-NOTES-through-0.9.md`](docs/BUILD-NOTES-through-0.9.md) (the build history with every measurement).

## What works and what does not

This table is the honest state on 2026-11-20. "Tested" means run by the automated suite; "on real data" means run on the owner's own files and the output read.

| Area | State |
|---|---|
| Launcher, one process per app, file opening, Windows registration | Works. Tested |
| Mitra PDF, Markdown Reader, Anything to MD | Work. Tested. No search, outline or read-aloud in Mitra PDF; scanned pages have no text |
| Ask Mitra (one small question-and-answer model) | Works. Small models are quick and private and make mistakes |
| Memory governor: one model at a time, a waiting line, per-model caps | Works. Tested, and held on a real 2 h 25 min recording (peak 975 MB under a 1,024 MB ceiling) |
| TwinMind: a recording or transcript in, a memo out | Works end to end, including a 2 h 25 min call with pause, hard stop and resume. **The memo of a long meeting is not good enough**: it is a list of short section notes, not a summary of the meeting |
| TwinMind: meeting library (old and new meetings, tags, projects, search inside, across-meetings view, people list) | Built 2026-11-14. Its own tests pass and the page was checked against a real archive of 2,597 transcripts. The full suite has not been rerun since |
| TwinMind: names spelt right | A people list is given to the speech model and wrong spellings are replaced. Tested on text; not yet proven on real audio |
| TwinMind: notice a meeting and offer to record it | Built 2026-11-20, Windows only, and only while TwinMind is open. Tested with a stand-in call app; not yet seen with a real Teams or Zoom call |
| TwinMind: record a meeting and show the transcript as it runs | Built 2026-11-20. Checked end to end with two minutes of synthesized speech; **not yet run on a real meeting or for hours**. The live model is provisional and misspells names |
| **TwinMind: a true whole-meeting summary; questions across meetings; your own notes merged in; templates; calendar preparation** | **Not built** |
| macOS, Linux, Android Termux | Not built or run |

The target for TwinMind is to match what Granola and TwinMind (the commercial apps) offer, on device, inside the limits below. It is not there yet; see [Roadmap](#roadmap).

## The apps

| App | Opens | Model | What it does |
|---|---|---|---|
| **Mitra PDF** | `.pdf` | none | Page view (the browser's own viewer) and a text view with headings, paragraphs and lists. Sends the file to Anything to MD |
| **Markdown Reader** | `.md` `.markdown` `.txt` | none | Rendered Markdown with an outline, a source toggle, links between files, and "open at this line" |
| **Anything to MD** | Word, PowerPoint, Excel, PDF, HTML, EPUB, RTF, ODT, CSV, TSV, JSON, notebooks, code, subtitles | none | Converts a document to Markdown and keeps its structure: heading levels, lists, tables with merged cells, links, slide sections, speaker notes |
| **TwinMind** | audio (`.wav .mp3 .m4a .ogg .flac`), subtitles, transcripts as text, Word, PDF | three, one after another | A recording or transcript becomes a memo; a library of every meeting; see [TwinMind in detail](#twinmind-in-detail) |
| **Ask Mitra** | – | one | Ask a question; the answer shows the model, seconds and memory used. Keeps the thread of a conversation |
| **Apps you create** | whatever you say | whatever you say | `mitra-marketplace new "a tracker for supplier quotes kept in my Dropbox"` writes an app with a manifest, an icon, a connector and a workspace screen. It runs as its own process and travels between machines |

Shared by every app: a top bar with the logo, a memory pill showing the model in use, and a per-app Manager; a go-to menu on Ctrl+K; a file browser with recent files; drop a file anywhere to open it in the app that reads it.

## Architecture

```
 you ── terminal: mitra-marketplace ──┐          Explorer: double-click / Open with ──┐
                                      ▼                                               ▼
                        ┌──────────────────────────┐                     bin/mitra-open (Rust, no window)
                        │ LAUNCHER  (Go, :7421)     │◄────────────────────────────────┘
                        │ welcome · icons · Create  │
                        │ Memory · System           │        has no abilities of its own:
                        └────────────┬─────────────┘        cannot convert a file or ask a model
                 click an icon       │  starts a process per app
        ┌───────────────┬────────────┼────────────────┬─────────────────┐
        ▼               ▼            ▼                ▼                 ▼
   Mitra PDF     Markdown Reader  Anything to MD   TwinMind         Ask Mitra       one Go process each,
        └───────────────┴────────────┼────────────────┴─────────────────┘         own port, own window, ~12 MB
                                     ▼   one Python process per request, gone when it answers
                          ┌─────────────────────────┐
                          │ WORKERS (Python)         │  convert · meeting pipeline · library · memory reports · app builder
                          └────────────┬────────────┘
                                       ▼   only when a model is needed
                          ┌─────────────────────────┐
                          │ GOVERNOR (Rust)          │  one model at a time across every app, a line for
                          │ lock · line · cap · stop │  those waiting, each model held to its measured need
                          └────────────┬────────────┘
             ┌──────────────┬──────────┴───────┐
             ▼              ▼                  ▼
       llama-server     whisper.cpp        audio.cpp
       question/notes   speech to text     who speaks when
```

Four languages, each where it fits:

| Part | Language | Why | Where |
|---|---|---|---|
| Launcher, each app's process, the command-line tool | Go | One small static binary that starts in about 110 ms and holds about 12 MB | `gateway/` |
| Memory governor, the windowless file handler | Rust | Must be tiny, exact about memory, and present only while a model runs | `governor/` |
| The recorder (microphone and system audio, two tracks) | Rust | Must run for hours in about 12 MB and never lose what it has heard | `ear/` |
| The work itself: conversion, the meeting pipeline, the library, reports, the app builder | Python | Runs as a fresh process per request (28 to 38 MB) and exits, so nothing stays in memory | `workers/mitra_workers/` |
| Screens | JavaScript, HTML, CSS | No framework and no build step; a screen is one HTML file | `web/`, `apps/*/ui/` |

**Launcher.** `bin/mitra-marketplace` is the launcher, each app's process and the command-line tool in one binary. As launcher it listens on `127.0.0.1:7421`, serves the welcome screen, the icons and the Create, Memory and System pages, and refuses work: it answers 409 to convert, ask and upload. It exits when its window closes.

**An app's process.** `mitra-marketplace app <id>` runs one app on a random local port in a bare browser window. It serves that app's screen and routes only; a request meant for another app is refused. A second click on a running app reuses its process. Closing the window ends the process five seconds later; a job at work keeps it alive until the job is done.

**Workers.** The Go process starts `python -m mitra_workers.dispatch` with the request on standard input and reads the answer from standard output. A long job runs detached and reports each stage to a file the page polls. Modules: `dispatch` (routing), `registry` (finding apps), `convert` (documents to Markdown), `models` (choosing and running models), `meeting`, `grounding` and `gist` (notes and their checks), `library` (the meeting index), `work` (saved pieces of a long job), `memory` (the log and its reports), `manager`, `builder`, `paths`.

**Governor.** Every model process is started by `bin/mitra-governor`, never directly:

- One model at a time, with a line. Whoever wants the model takes a ticket in `~/.mitra/run/line`. A question from a person goes ahead of a long job; long jobs go first come, first served. Nothing in the line times out.
- A model whose estimate is above the ceiling, or which would leave less than `reserve_mb` free, is refused before it starts.
- Each model is held to its own measured need plus about 10 percent, sampled twice a second, and stopped if it goes over. If it was stopped at its own cap and the ceiling still has room, it is run once more held to the ceiling, and that is logged.
- A waiter whose caller has gone leaves the line; a running model whose caller has gone is stopped. A model stopped by hand ends with its own code, which a job treats as a stop and not as a failure.
- Models run on CPU, below normal priority, so the footprint is the same on every device and screens stay responsive.

**Catalog.** `catalog.json` maps capabilities to candidate models. An app declares what it needs (`assistant`, `meeting-notes`, `transcription`, `diarization`); Mitra picks the first candidate that is on the device and fits the ceiling, and steps down to the next one if memory is refused.

## The rules the system keeps

| Rule | How it is kept |
|---|---|
| Nothing in memory when nothing is open | The launcher and apps exit on close; workers exit on answer; models are stopped after each use |
| One model at a time | The governor's lock and line, shared by every app |
| No model above 1,024 MB | Admission check, per-model cap, sampling twice a second |
| The whole package about 2 GB | A test fails the build above 2,048 MB (2,027 MB measured, with models and ffmpeg) |
| Apps are separate products | Separate processes and ports; routes refused across apps |
| Only this device | Listens on `127.0.0.1`; requests with a foreign host or origin are refused; no path may escape the folders it is given |
| Every use is logged, on the device | One log for all processes, reviewable by week, two weeks or month, and prunable |
| The same on every device | CPU only; capabilities resolved per device; nothing sized to the development machine. Target: 8 GB RAM, a plain i5, no GPU |
| Deleting is recoverable | Discarded work goes to the Recycle Bin |

## Models and runtimes

**Neither is in this repository.** Model files are large and belong to their publishers; the runtimes are other projects' binaries. Mitra looks for a model first in `models/<name>/` inside the project and then anywhere under `models_dir` from the settings.

| Capability | First choice | Memory while running | Runtime | Steps down to |
|---|---|---|---|---|
| Question and answer (`assistant`) | Qwen3 0.6B, 4-bit | 564 MB | llama.cpp `llama-server` | LFM2.5 350M, Gemma 3 270M |
| Meeting notes (`meeting-notes`) | Gemma 3 1B, 4-bit | 915 to 950 MB | `llama-server` | Gemma 3 1B Q4_0, Qwen3 0.6B |
| Speech to text (`transcription`) | Whisper medium, 5-bit, greedy decoding | 964 to 980 MB | whisper.cpp `whisper-cli` | Whisper small, Whisper base |
| Who speaks when (`diarization`) | NVIDIA Sortformer (Nemotron 3 diarization) | 170 to 187 MB | audio.cpp `audiocpp_cli` | – |

To set up: put the GGUF or `ggml-*.bin` file for each model in a folder of the name used in `catalog.json` (for example `models/qwen3-0.6b-q4_k_m/`), put the runtimes under `runtimes/llama/`, `runtimes/whisper.cpp/` and `runtimes/audio.cpp/` (or on the PATH, or name them in the settings), and install ffmpeg for audio that is not WAV. `mitra-marketplace models` lists what each capability resolves to and whether it is ready; `mitra-marketplace models sync` copies the chosen models from your library into the project.

Settings that matter for memory: a 1,536-token context, an 8-bit context cache, and weight repacking off (`--no-repack`), which alone took Qwen from 762 to 564 MB and Gemma from 987 to about 915 MB. How each model was chosen and measured is in `docs/ARCHITECTURE.md`, section 7.

## TwinMind in detail

### A recording becomes a memo

| # | Stage | How | Measured on a real 2 h 25 min call |
|---|---|---|---|
| 1 | Who speaks when | Sortformer on windows of 5 minutes that overlap by 45 seconds. A voice keeps its number across windows by who was talking in the overlap, or by elimination; otherwise it gets a new number, never someone else's | 34 windows, about 75 s each, 168 to 178 MB |
| 2 | What was said | Whisper medium on pieces of 5 minutes cut in pauses, each heard whole with word timings; each sentence goes to the speaker talking for most of it. Any language is written in English by default | 29 pieces, about 2 min 20 s each, 975 MB |
| 3 | Gist | Plain code quotes two or three sentences word for word | no model |
| 4 | Notes | Gemma 3 1B, section by section (about 420 words): topic, points, decisions, open questions, action items as constrained JSON | 47 sections, about 22 s each, 950 MB |
| 5 | Check | Every note and action is tested against the transcript: a number, owner or date never said is removed; pasted lines and pleasantries are dropped; the memo lists what was removed | no model |
| 6 | Memo | Markdown in your TwinMind folder: core focus, discussion by topic with decisions, action items, commitments quoted as spoken, follow-up, the full transcript | |

That call took about 2 hours of work on the development laptop for 2 hours 25 minutes of audio, with memory flat throughout. On an 8 GB i5 with no GPU expect several times longer.

### Long meetings and other apps at the same time

- **Pieces are saved.** Every finished window, piece and section is written to `~/.mitra/run/work/<job>` before the next begins. A job that stops (Pause, Stop, the app closed, a restart, memory refused) is shown first on the page with what was kept; Resume does only what is left.
- **A line of recordings.** A recording added while another is being written waits in "Next up", can be moved or removed, and is written by itself afterwards.
- **Speed.** Accurate (Whisper medium) or Fast (the next model down) per recording, with a time estimate for that file that is replaced by this device's own figures after its first finished job.
- **Stepping aside.** The notes model is released between sections when another app is waiting. On the real call a question in Ask Mitra waited 54 s during the speaker stage, 189 s during speech and 22 s during notes, and was answered each time.

### A meeting as it happens (0.10.0)

| Step | How |
|---|---|
| **Noticing a meeting** | While TwinMind's window is open it asks its own process every five seconds which programs are recording from a microphone. The answer comes from Windows' audio sessions, read by `mitra-ear who`; nothing is listened to. If one of them is a call app (Teams, Zoom, Webex, Slack, WhatsApp, a browser and so on) a banner asks "Do you want me to record it?", with "Not this one". Someone talking near the laptop is not a meeting, and neither is a dictation tool. Nothing watches when Mitra is closed |
| **Recording** | `mitra-ear` (Rust, about 12 MB, no model) records two tracks at 16 kHz: your microphone, and whatever the computer plays, which in a call is everyone else. Nothing joins the call. Each track is written in half-minute pieces under a temporary name and renamed when complete, so a crash loses at most the half minute in hand, and both tracks follow the wall clock so piece N covers the same half minute on each |
| **The transcript as it grows** | Each finished piece goes through the smallest multilingual speech model (Whisper base, about 2 s per piece, 356 MB while it runs, nothing between pieces). A silent piece runs no model. A line that runs into the end of a piece is held back and heard whole with the next one. Lines are marked with your name or "Others" by track |
| **Your notes** | A box beside the transcript; what you type is saved as you go and put in the memo as written |
| **When you stop** | The pieces are put together into one recording per track and a mix, and the full pipeline writes the memo: speakers, the accurate speech model, notes, the check. The speaker heard on the microphone track is named as you. Recordings are kept 30 days (`keep_recordings_days`), then go to the Recycle Bin |
| **If the app is closed mid-meeting** | The recorder ends cleanly and the Live tab offers "Write its memo" next time |

Memory is flat for any length: one piece is handled at a time and everything so far is on disk. Checked on 2026-11-20 with a two-minute recording of synthesized speech played through the speakers: both tracks recorded, every sentence in the live transcript after two faults were fixed (an invented "Thank you" from the silent microphone track, and a sentence lost at a piece boundary), and a correct memo with the typed note in it. **Not yet run on a real meeting, on a real voice at the microphone, or for hours**; the live speech model is a provisional choice that gets names wrong (the memo's model does not).

### The meeting library

- **Meetings.** Every meeting in one list: the memos TwinMind wrote and a read-only archive of transcripts named by `meeting_archive` in the settings (Markdown files with front matter giving date, title, client and speakers). Filter by project, year, or whether a summary exists; search titles and people, or search inside every transcript.
- **One meeting** opens in the page as Summary, Transcript (exactly as recorded) and "Promised or asked" (quoted sentences, no model), with a project and tags you can set. A meeting with no summary has "Write the summary", which saves the result in TwinMind's own folder.
- **Across meetings.** One project over time: meetings per month, who was in them, and the action items, decisions and open points gathered from every summary, each linked to its meeting.
- **People.** Names that must come out right. The list is given to the speech model before it listens, and every wrong spelling listed beside a name is replaced in the transcript before notes are written.

The archive is only ever read. Tags, projects and summaries live in `~/.mitra/twinmind/` and in TwinMind's own memo folder.

### Known weaknesses

- The memo of a long meeting is a run of section notes, many with generic titles; there is no single summary of the whole meeting yet.
- Notes sometimes give a statement to the wrong speaker and repeat any translation error as fact. On a call with few real tasks the action list fills with descriptions of what was said.
- Speaker boundaries are per sentence, so overlapping speech goes to one person.
- The speaker model reserves about 3.2 GB of virtual memory at start though it uses about 180 MB.
- Tried on two-person phone calls in Hindi and English. Not tried on a room recording or on four or more people.

## Install, build, run

Needs Go, Rust (cargo) and Python 3.10 or later.

```
# Windows
.\build.ps1

# macOS, Linux, Termux (untested)
sh build.sh
```

This builds `bin/mitra-marketplace`, `bin/mitra-governor`, `bin/mitra-open` and `bin/mitra-ear`. Add `bin` to your PATH, set up the models and runtimes as above, then:

```
mitra-marketplace
```

On Windows, `mitra-marketplace register` adds the apps to the Start menu, "Open with" and Default apps; it writes only to your own user settings and never sets a default itself.

## Commands

```
mitra-marketplace                       open the welcome screen and your apps
mitra-marketplace open APP [FILE]       start one app in its own window, optionally on a file
mitra-marketplace apps                  apps running now, each with its port and memory
mitra-marketplace close APP             stop one app
mitra-marketplace stop                  stop every app, the launcher and any running model
mitra-marketplace list                  installed apps
mitra-marketplace new "PROMPT"          create an app from a description
mitra-marketplace memory report [weekly|biweekly|monthly]
mitra-marketplace memory prune [DAYS]   roll up and archive logs older than DAYS (default 90)
mitra-marketplace status                RAM, the model running now, the apps running, limits
mitra-marketplace models [sync]         the model each app uses; sync copies them into this folder
mitra-marketplace size                  what the whole package takes on disk
mitra-marketplace optimize              housekeeping now (also runs at start and every six hours)
mitra-marketplace register [--desktop]  Windows: Start menu, "Open with" and Default apps
mitra-marketplace unregister            undo that
mitra-marketplace push                  pack this install into a zip in the shared folder
mitra-marketplace update [--check]      install the newest zip from the shared folder
mitra-marketplace install [APP|ZIP]     search this system for Mitra zips and install them
mitra-marketplace releases [prune N]    list releases; prune keeps the newest N
mitra-marketplace pack APP              zip one app for another system
mitra-marketplace test [--quick]        run the test suite
```

Moving between machines: `push` packs code and binaries (about 10 MB) into a shared folder with a checksum; `update` on another machine verifies and installs it, and your created apps travel with it. Models and runtimes are copied once, separately.

## Settings

`~/.mitra/config.json`, per device. Everything has a default.

| Key | Default | Meaning |
|---|---|---|
| `models_dir` | `~/.mitra/models` | Your model library; the project's own `models/` is looked in first |
| `finetuned_dir` | `<models_dir>/finetuned` | Where fine-tuned models go, each with a model card |
| `model_budget_mb` | 1024 | The ceiling for any model |
| `reserve_mb` | 800 | Free memory that must remain after a model loads |
| `threads` | half the cores | CPU threads for a model |
| `assistant_ctx` | 1536 | Context length for the language models |
| `transcribe_language` | `english` | `english` (write everything in English), `original`, or a code such as `hi` |
| `meeting_archive` | none | A folder of old transcripts for TwinMind's library, read only |
| `keep_recordings_days` | 30 | How long live recordings are kept before they go to the Recycle Bin |
| `app_window` | `window` | `window`, `tab` or `none` |
| `app_idle_exit_s` | 150 | An app with no window ends after this long |
| `idle_exit_min` | 10 | The launcher's idle exit |
| `connectors.dropbox` | found automatically | Where the synced Dropbox folder is |
| `llama_server`, `whisper_cli`, `audiocpp_cli`, `ffmpeg` | found automatically | Paths to the runtimes |

## The memory log

Every process appends one line per event to `~/.mitra/memory/events/<date>.jsonl`: an app starting and ending, a file opened, an action taken, each request with its milliseconds and peak memory, each model's load, run, peak, cap and how it ended, every refusal, stop, wait in line and step aside, and every job queued, paused, stopped or resumed. `mitra-marketplace memory report weekly` (or the Memory page) turns it into a report with suggestions; `memory prune` rolls up and archives what is old. The log never leaves the device.

## Tests

`mitra-marketplace test` runs the suite in `logs/tests/run_tests.py` against a private launcher on its own port with a temporary home folder, so your own log, apps and files are untouched and no window opens. `--quick` skips the cases that load real models.

| Area | What it covers |
|---|---|
| A to D | Launcher and commands; one process per app; products kept separate; each app's screen |
| E, M | Conversion of every format, and that structure is kept; which app opens what; drop to open; Windows registration |
| F, O | The governor: budget, caps, one model at a time, the line, callers that go away, stops by hand |
| G, N | The meeting pipeline, grounding checks, speakers across windows, long recordings |
| H, I, J, K | The memory log; moving between systems; security; resources and the 2 GB package limit |
| L | Real models: answers, notes, three models in sequence |
| O | Saved pieces, pause, stop and resume, the line of recordings, stepping aside |
| P | The meeting library: an archive listed and filtered, tags kept outside it, search inside, names put right |
| Q | Live meetings: who is using the microphone, a call app noticed and un-noticed, two tracks in equal pieces, a line carried across a piece boundary, invented phrases dropped, tracks put together, the Live tab |

Last full run: 343 of 343 on 2026-11-14 (version 0.9.0). Nine library cases were added afterwards and pass; the full suite has not been rerun with them. A passing suite has let a broken product through before (the automated recordings are synthesized speech), so audio changes are also run on a real recording and the memo read. `TEST_PLAN.md` records every run, every failure and what each one turned out to be.

## Repository layout

```
gateway/             Go: launcher, app process, commands, file types, releases
governor/            Rust: the memory governor and the windowless file handler
ear/                 Rust: the recorder (two tracks in saved pieces) and "who is using the microphone"
workers/             Python: mitra_workers/ (the work each request does)
web/                 the launcher page, sdk.js (shared by every app), mitra.css, the logo
apps/                pdf-reader · markdown-reader · to-markdown · twinmind · assistant
catalog.json         capability → candidate models, each with its measured memory and why it is there
docs/                architecture (Markdown and interactive), wireframes, research, interface review, build notes
logs/scripts/        every script written while building, measuring and patching, kept as the record
logs/tests/          run_tests.py and a report for every run
reference/           what was absorbed from an earlier meeting tool
build.ps1 · build.sh · install.ps1 · install.sh
README.md · APP_SPEC.md · TEST_PLAN.md · FINETUNE_PLAN.md

not in the repository:  models/  runtimes/  bin/  (see "Models and runtimes" and "Install, build, run")
on your device:         ~/.mitra/  config.json · apps/ (yours) · memory/ · run/ · twinmind/ · logs/
```

## Roadmap

In this order:

1. **Live meetings, proven.** Built in 0.10.0. Still to do: a real meeting of two to three hours recorded and read; a survey of every candidate for the live speech model on at least a hundred held-out cases, so names come out right in the running transcript too; a notification when TwinMind's window is not in front.
2. **A real summary.** One summary of the whole meeting above the section notes, built from them, with decisions, owners and dates.
3. **Ask your meetings.** A question answered from one meeting or across all of them, with the meeting and the line cited.
4. **Parity with the commercial meeting apps.** Your own notes taken during the meeting merged into the summary; templates and saved prompts; people and company views; preparation from the calendar.
5. **Other platforms.** macOS, Linux and Android Termux builds, run and tested.
6. **The rest.** Search, outline and read-aloud in Mitra PDF; reading scanned pages.

Model choices for new roles are made by surveying every candidate, testing on at least a hundred held-out cases, and recording whether the model can be fine-tuned.
