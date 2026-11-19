# Mitra

Type `mitra-marketplace` in any terminal. A welcome screen opens; behind it are your apps as icons. Each app is its own program: it starts when you click its icon, runs in its own window, and is gone a few seconds after you close it. Everything runs on the device.

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
mitra-marketplace register [--desktop]  Windows: add the apps to the Start menu, "Open with" and Default apps
mitra-marketplace unregister            undo that

mitra-marketplace push                  pack this install into a zip in the shared folder
mitra-marketplace update [--check]      install the newest zip from the shared folder
mitra-marketplace install [APP|ZIP]     search this system for Mitra zips and install them
mitra-marketplace releases [prune N]    list releases; prune keeps the newest N
mitra-marketplace pack APP              zip one app for another system
mitra-marketplace test [--quick]        run the test suite (see TEST_PLAN.md)
```

## How it is put together

Separate apps on a shared base (option C in `docs/APPROACH-NOTE-apps-architecture.md`).

| Part | Language | Job | In memory |
|---|---|---|---|
| Launcher (`mitra-marketplace`) | Go | Welcome screen, icons, Create, Memory and System pages. It has no capabilities of its own: it cannot convert a file or ask a model | About 12 MB while its window is open; ends when the window closes |
| An app (`mitra-marketplace app ID`) | Go, same binary | One process per app, on its own port, serving that app's screen and routes and nothing else | About 12 MB each, only while that app is open |
| `governor/` | Rust | Starts every model process inside a RAM budget, one at a time across all apps; stops it if it goes over | Only while a model runs |
| `workers/` | Python | Logic: conversion, memory reports, app builder, pipelines. One process per request | No |
| `web/`, `apps/*/ui` | JavaScript | The launcher page, the shared SDK, each app's interface | Only in the open window |

What the apps share: the runtimes, the model store, the governor and the memory log. What they do not share: a process, a port, a window, or each other's routes.

- **Starting.** Clicking an icon starts the app's process (measured 110 ms) and opens it as a bare window in Chrome or Edge, with no tabs or address bar. Where neither is installed, or with `"app_window": "tab"` in the config, it opens as a browser tab. On a phone it is always a tab.
- **Ending.** The window tells its process when it closes; the process ends five seconds later. A reload is not a close. If the window vanishes without a word, the process ends after `app_idle_exit_s` (150 seconds).
- **Separation.** The launcher answers 409 to `/api/convert`, `/api/ask`, `/api/upload` and to any app's own routes. An app's process answers 403 or 404 to anything meant for another app, and only serves the shared services its manifest lists under `uses`.
- **One model at a time.** An app declares the capabilities it needs; the governor's lock is shared, so if TwinMind is summarising, Ask Mitra waits in a line for its turn instead of loading a second model. A question goes ahead of a long job at its next piece; nothing in the line times out.
- **Logs.** Every process writes to one memory log, `~/.mitra/memory/events/`, including each app's start (`app.spawn`), how it was opened (`app.launch`) and why and after how long it ended (`app.exit`). Each process's own output goes to `~/.mitra/logs/<app>.log`.

`catalog.json` maps capabilities to candidate models. `APP_SPEC.md` explains how to write an app. `docs/ARCHITECTURE.md` describes the whole system, every app and every feature, with the model search of 2026-11-13; `docs/architecture.html` is the same as an interactive page (open it in a browser).

## Opening files

Each app's manifest lists the file types it opens (`"opens"`). That one list drives all three ways in.

| Way in | What happens |
|---|---|
| Drop a file on the launcher | The app that opens that type starts on the file. Dropped on one app's icon, it opens in that app if the app reads the type |
| Drop a file anywhere in an app's window | It opens there. A type that app does not read goes to the app that does |
| Double-click, or "Open with", in Explorer | After `mitra-marketplace register`: the app starts on the file, with no console window |

| App | Types |
|---|---|
| Mitra PDF | .pdf |
| Markdown Reader | .md .markdown .txt |
| Anything to MD | .docx .pptx .xlsx .html .htm .csv .tsv .json .ipynb .epub .rtf .odt, and anything no other app claims |
| TwinMind | .wav .mp3 .m4a .ogg .flac .vtt .srt |

- **Registering.** `register` writes only to your own user settings. It creates a Start menu folder (Mitra) with one entry per app, and lists each app under "Open with" and in Settings > Apps > Default apps. `--desktop` also puts shortcuts on the Desktop; a file dropped on a shortcut opens in that app.
- **Making an app the default.** Windows lets only the person do this. Right-click a file > Open with > Choose another app > pick the Mitra app > Always. Registering never changes a default by itself.
- **Dropped files.** A browser gives a page the file's contents, never its location. The app works on a temporary copy (cleared after a day), so a dropped file shows its own name but "Save .md" writes to Downloads, not beside the original. Opening from Explorer or the file list has no such limit.

## What converted documents look like

Anything to MD, and the text view in Mitra PDF, keep the source document's own structure.

| Source | Kept |
|---|---|
| Word | Title and heading levels (by style name, so other-language Word works), bold, italic, links, nested bullets, numbered lists, tables with merged cells. With no styles at all, headings are read from larger or bold type |
| PDF | Headings from type size, then short bold lines; wrapped lines joined into paragraphs, across page breaks; hyphenated words rejoined; lists; short lines such as addresses keep their breaks; running headers, footers and page numbers removed |
| PowerPoint | One section per slide, titled from the title placeholder; bullet levels; tables; speaker notes |
| HTML, EPUB | Headings, real tables, nested and numbered lists, quotes, rules; EPUB chapters in reading order |
| RTF, ODT | Headings, bold, italic, links, lists, tables |

A PDF with no detectable headings falls back to one section per page. Tables inside PDFs are not reconstructed.

## The apps

| App | Models | Notes |
|---|---|---|
| Mitra PDF | None | The browser's page view, or extracted text; send to Anything to MD |
| Anything to MD | None | PDF, DOCX, PPTX, XLSX, HTML, CSV, EPUB, RTF, ODT, notebooks, subtitles, code |
| Markdown Reader | None | Rendered view, outline, source toggle, links between files |
| Ask Mitra | assistant | The one general question-and-answer model |
| TwinMind | transcription, diarization, meeting-notes, one after another | Recording or transcript to a memo in Dropbox, in your MeetingNoter layout; search across all meetings |

TwinMind's memo follows the layout of your archived notes (taken from the earlier MeetingNoter app): Meeting Core Focus, Key Discussion Points by topic with the decisions made under each, Action Items with owners, Follow-up Needed, and the transcript as an appendix. The focus is quoted word for word, commitments are always quoted as spoken, and a stage that could not run is named in the memo. RTF and ODT input also came from MeetingNoter.

### How TwinMind handles a recording (0.8.0)

Version 0.7.0 failed on the first real recording it was given, a 4-minute phone call. Both audio models were stopped by memory caps that had been sized on 40-second synthetic clips, and the tiny English speech model could not follow a call that moves between Hindi and English. What it does now:

| Stage | How | Measured on real calls, 2026-11-12 |
|---|---|---|
| Who speaks when | NVIDIA Sortformer in streaming mode, on windows of 5 minutes that overlap by 45 seconds. A voice keeps its number across windows by who was talking in the overlap; a voice that cannot be matched gets a new number, never someone else's | 170 to 187 MB per window on a 16-minute call, the same for any length. About 12 s per minute of audio |
| What was said | Whisper medium (99 languages, 5-bit, 514 MB, greedy decoding) on pieces of 5 minutes cut in pauses. Each piece is heard whole, with word timings; each sentence goes to the speaker talking for most of it. Whatever is spoken is written in English. Whisper small takes over if this device cannot give medium the memory, and the memo says so | 964 to 980 MB. About 25 s per minute of audio |
| Gist | Plain code, quoted word for word | No model |
| Notes | Gemma 3 1B, section by section, then the grounding check. If this device cannot give it the memory, Qwen3 0.6B writes the notes and the memo says so | 915 to 945 MB |
| Who is who | After the memo, the page shows each voice with a line it said and asks for a name; the memo is rewritten with names | No model |

A 4-minute call takes 3 minutes 18 seconds; a 16-minute call took 12 minutes 17 seconds (with Whisper small they took 1 minute 45 and 7 minutes; the larger speech model was chosen on 2026-11-13 for accuracy). Each model is held to its own measured need; if one is stopped at that cap and the 1 GB ceiling still has room, it is run once more held to the ceiling and the event is logged (`model.cap_raised`), so a wrong estimate costs time, not the memo.

### Long calls and several apps at once (0.9.0)

A call can run to two hours and you may be using other apps while it is written up. Still one model at a time, still under 1 GB.

| What | How |
|---|---|
| **A line for the model** | Whoever wants the model takes a ticket (`~/.mitra/run/line`). The model goes to the head of the line when it is free: a question in Ask Mitra goes ahead of a long job, long jobs go first come first served. Nobody is turned away for waiting; the two-minute give-up is gone. A cancelled question, or a job whose app was closed, leaves the line |
| **Pieces are saved** | Every finished speaker window, 5-minute piece of speech and section of notes is written to `~/.mitra/run/work/<job>` before the next begins. A job that stops (Pause, Stop, the app closed, a restart, memory refused) is shown first on TwinMind's page with what was kept, and Resume does only what is left. The pieces belong to one recording at one speed; an edited file starts afresh |
| **Stepping aside** | The notes model is let go between sections when another app is in line, and loaded again after. With nobody waiting it stays loaded |
| **A line of recordings** | A recording added while another is being written up waits in "Next up", can be moved or removed, and is written by itself afterwards as its own job |
| **Speed** | Accurate (Whisper medium) or Fast (the next speech model down) per recording, each with a time for that file. Times start from figures measured on the development laptop and are replaced by this device's own after its first finished job |
| **Pause and Stop** | Pause ends after the piece in hand and frees the model. Stop ends now; the piece in hand is lost. Stopping the model on the System page, or closing TwinMind from the launcher, stops the job the same way, with its pieces kept. Closing only the window does not stop it |
| **Seen from outside** | The launcher's Your apps page says who has the model, what for, and who is waiting; the System page lists the line; Ask Mitra shows "Waiting for a turn" with a Cancel |

`"transcribe_language"` in the config: `"english"` (default), `"original"` (keep each language as spoken) or a language code such as `"hi"`.

The interface carries the Mitra logo (colour on light, tint on dark) and its navy and saffron. Ctrl+K opens a go-to menu in every window; `/` jumps to search in the launcher.

## Package size

`mitra-marketplace size`, measured 2026-11-12:

| Part | MB |
|---|---|
| Launcher, governor and the 0.3 MB file handler | 8.8 |
| Apps, pages, workers | 0.4 |
| llama runtime (CPU files only) | 41.3 |
| whisper.cpp | 22.1 |
| audio.cpp (only the program Mitra runs) | 32.9 |
| Models: Gemma 3 1B 769, Whisper medium 514, Qwen3 0.6B 378, diarization 102, Whisper base 57 | 1820.0 |
| **In the package** | **1925.5** |
| ffmpeg (installed separately) | 98.1 |
| **Everything Mitra uses** | **2023.6** |

`mitra-marketplace models sync` copied the models and the llama runtime into the package (`models/`, `runtimes/llama/`), where they are looked for first. Every app now works with the E: drive unplugged. The library on E: is unchanged.

## Resource rules

- With nothing open, nothing of Mitra is in memory.
- The launcher and each open app hold about 12 MB each. A request starts a worker of about 28 to 38 MB that exits when it has answered; its peak RAM is logged with the request.
- No model is in memory unless a request is using it. It loads, answers, and is stopped.
- One model at a time across every app, and none above `model_budget_mb` (default 1024, that is 1 GB; it was 800 until 2026-11-13). Each model is also held to its own measured need plus about 10%: the speaker model is stopped at about 230 MB, not at 1024. A model stopped at its own cap is run once more held to the ceiling; the ceiling is never exceeded.
- Models run on CPU, below normal priority, so the footprint is the same on every device.

## Moving between systems

The shared folder is `Dropbox/Mitra/releases` unless `release_dir` is set in `~/.mitra/config.json`. Nothing listens on the network.

1. On the machine with the changes: `mitra-marketplace test`, then `mitra-marketplace push`.
2. On a machine that already has Mitra: `mitra-marketplace update`. It verifies the checksum, installs, and removes files the new release no longer ships. Apps you created travel with it.
3. On a new machine: run `install.ps1` (Windows) or `sh install.sh` (macOS, Linux, Termux) from the shared folder.

A release zip carries code and binaries (about 10 MB), not the runtimes or the models. On the other machine, run `mitra-marketplace models sync` with the model library attached, or copy the `models/` and `runtimes/` folders across once.

## Per-device settings: `~/.mitra/config.json`

```json
{
  "models_dir": "E:\\Local AI Models",
  "finetuned_dir": "E:\\Local AI Models\\08 Customized Models\\mitra-marketplace-finetunes",
  "model_budget_mb": 1024,
  "reserve_mb": 800,
  "app_window": "window",
  "app_idle_exit_s": 150,
  "idle_exit_min": 10,
  "assistant_ctx": 1536,
  "connectors": {"dropbox": ""}
}
```

`app_window`: `window` (a bare Chrome or Edge window per app), `tab`, or `none`. `browser` can name a specific Chrome-family program.

## Build

Windows: `./build.ps1`. macOS, Linux, Termux: `./build.sh` (Termux: `pkg install golang rust python` first). Needs Go, Rust and Python 3.10+.

## Measured on the development machine (CPU only)

| What | RAM |
|---|---|
| Launcher, window open | 11 to 13 MB |
| One app's process | 11 to 12 MB |
| One request's worker (gone when it answers) | 28 to 38 MB |
| qwen3-0.6b-q4_k_m while answering (Ask Mitra) | 564 MB |
| gemma-3-1b-it-q4_k_m while writing meeting notes | 915 to 945 MB |
| whisper-medium-q5_0-cpp while transcribing a real call | 964 to 980 MB |
| whisper-small-q5_1-cpp, the step-down | 605 to 637 MB |
| nemotron-3-diarization-audiocpp while finding speakers, per 5-minute window | 170 to 187 MB (and about 3.2 GB of virtual memory reserved, not used) |
| Everything, with no window open | 0 |

How the assistant's 881 MB was brought to about 750 MB is recorded in `logs/scripts/bench_llama_flags.py`: an 8-bit context cache and a 1,536-token context. A 4-bit cache saved more and produced garbage. On 2026-11-13 turning off load-time weight repacking (`--no-repack`) took it from 762 MB to 564 MB, and Gemma 3 1B from 987 to about 915 MB, with the same answers and no loss of speed measured (`logs/scripts/apply_no_repack.py`).

## Not done yet

- **Notes quality is better, not solved.** On 2026-11-13 you raised the ceiling to 1 GB and the notes model became Gemma 3 1B. On your two calls it writes concrete points and real action items ("Share the proposal with the client by Wednesday", "Schedule a discovery session with the client") and no longer repeats transcript lines, where Qwen3 0.6B produced mostly noise. It still gets things wrong: it sometimes gives a statement or a task to the wrong speaker, it writes vague tasks ("Give example"), and it repeats any mistake in the translated transcript as fact (a mistranslated word became "the donkey's video"). The check removes an owner, date or number the transcript does not support. Read the notes against the quoted commitments before acting on them. On a call that is mostly advice or discussion, with few real tasks, the action list fills with descriptions of what was said ("Recommend relaxing", "Ask for a different perspective") instead of tasks.
- **Speaker boundaries are per sentence.** Word timings from the speech model are approximate, so a sentence is given whole to whoever was talking for most of it. Two people talking over each other come out as one of them.
- **A voice that is silent where two windows join** (every 4 minutes 15 seconds on long recordings) is matched by elimination if only one voice is unaccounted for; with two or more, each gets a new speaker number rather than a guess. This was tested on a 16-minute two-person call and a synthesized two-voice recording, not on a meeting of four or more.
- **The speaker model reserves about 3.2 GB of virtual memory at start** and uses about 180 MB of it. Its runtime ignores the settings that should shrink this (`logs/scripts/measure_diar_options.ps1`). On a machine that cannot promise that much, the stage is skipped with the reason and the memo is written without speakers.
- **Translation.** Hindi is written in English by the speech model. It is good on the calls tried, but it is a translation: an idiom or a name can come out wrong, and the original Hindi words are not kept unless `transcribe_language` is `original`.
- **TwinMind's own meeting page** (notes beside the transcript, play the recording) is not built; a memo opens in Markdown Reader, as its own process. Speaker naming is built (after a memo is written).
- **From the September TwinMind plan, not built:** calendar tagging, voice enrolment, chat that cites the conversation and timestamp, audio kept for 30 days, tap a line to play it.
- **Mitra PDF** has no search, outline or read-aloud yet (see `docs/INTERFACE-REVIEW.md`).
- Transcription and diarization have been run on two real phone calls of yours (4 and 16 minutes, two people, Hindi and English) and on synthesized speech. Not tried: a room recording, more than two people, another language pair.
- **A call of over an hour has not been run to the end.** A 2 hour 25 minute call was started on 2026-11-14 (estimate: 117 minutes) and was stopped by hand 34 minutes in, with 29 of 34 speaker windows saved; pause, resume, the line and a question in Ask Mitra worked on it up to there. The speech and notes stages of a long call, and its memo, have not been seen. TwinMind shows that job as unfinished with Resume.
- **Your earlier PDF app.** MPDF (`AppData\Local\Programs\MPDF`, 229 MB) is installed and is the current default for .pdf. It was found on 2026-11-12 through its file association; it has not been read or merged into Mitra PDF, and its default was left alone.
- **Windows integration not seen by me.** `register` was run on this PC and its registry entries and shortcuts were checked, and the handler was run on a file. The "Open with" menu, Default apps page and a real drag from Explorer have not been looked at by me; drops were checked with simulated drop events in a browser pane.
- **Taskbar.** An app's window is a Chrome or Edge window, so it groups under that browser's taskbar icon, not a Mitra one.
- `register` is Windows only. On macOS and Linux use `mitra-marketplace open APP FILE`.
- The bare app window was checked through the launcher's logic and in a browser pane; the actual Chrome `--app` window on your desktop has not been looked at by me.
- Only built and run on Windows. macOS and Termux builds are untested; on a phone each app is a browser tab.
- If an app is open in two windows and one closes, the app can end while the other window is hidden for a long time; reopening it from the launcher restores it.
