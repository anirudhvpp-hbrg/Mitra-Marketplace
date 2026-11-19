# Mitra: architecture, applications and features

Version 0.9.0, written 2026-11-13, updated 2026-11-14 (section 5.4, "Long calls and several apps at once"). The interactive version of this document is `docs/architecture.html` (open it in any browser).

Everything here describes what is built and measured unless a line says "not built" or "candidate". Numbers are from this development machine (Windows 11, CPU only) on the dates given.

## 1. What Mitra is

One command, `mitra-marketplace`, opens a welcome screen and a set of local apps as icons. Each app is its own small program that starts when its icon is clicked and ends a few seconds after its window closes. Nothing leaves the device. Models are loaded only for the request that needs them, one at a time, inside a memory ceiling of 1 GB.

| | |
|---|---|
| Apps | Mitra PDF, Markdown Reader, Anything to MD, TwinMind, Ask Mitra, plus apps you create from a sentence |
| Languages | Go (launcher and app processes), Rust (memory governor, file handler), Python (work done per request), JavaScript (screens) |
| On disk | 1,926 MB in the package, 2,024 MB with ffmpeg, inside the 2 GB limit |
| In memory with nothing open | 0 |
| In memory with an app open | About 12 MB for the launcher and 12 MB per open app |
| Largest thing ever in memory | One model, at most 1,024 MB |
| Targets | 8 GB RAM, a plain i5 with no GPU; Windows built and tested, macOS and Android Termux not yet tried |

## 2. The shape

```
 you ── terminal: mitra-marketplace ──┐          Explorer: double-click / Open with ──┐
                                      ▼                                               ▼
                        ┌──────────────────────────┐                     bin/mitra-open.exe (Rust, no window)
                        │ LAUNCHER  (Go, :7421)     │◄────────────────────────────────┘
                        │ welcome · icons · Create  │
                        │ Memory · System           │        has no abilities of its own:
                        └────────────┬─────────────┘        cannot convert a file or ask a model
                 click an icon       │  starts a process per app
        ┌───────────────┬────────────┼────────────────┬─────────────────┐
        ▼               ▼            ▼                ▼                 ▼
  ┌──────────┐   ┌────────────┐ ┌──────────────┐ ┌──────────┐   ┌────────────┐
  │ Mitra PDF│   │ Markdown   │ │ Anything     │ │ TwinMind │   │ Ask Mitra  │    one Go process each,
  │          │   │ Reader     │ │ to MD        │ │          │   │            │    own port, own window,
  └────┬─────┘   └─────┬──────┘ └──────┬───────┘ └────┬─────┘   └─────┬──────┘    about 12 MB
       └───────────────┴───────────────┼──────────────┴───────────────┘
                                       ▼   one Python process per request, gone when it answers
                          ┌─────────────────────────┐
                          │ WORKERS (Python)         │  convert · meeting pipeline · memory reports · app builder
                          └────────────┬────────────┘
                                       ▼   only when a model is needed
                          ┌─────────────────────────┐
                          │ GOVERNOR (Rust)          │  one model at a time across every app,
                          │ lock · budget · stop     │  each held to its own measured need
                          └────────────┬────────────┘
             ┌──────────────┬──────────┴───────┬──────────────────┐
             ▼              ▼                  ▼                  ▼
       llama-server     whisper.cpp        audio.cpp          (nothing else)
       Qwen3 0.6B       Whisper medium     Sortformer
       Gemma 3 1B       speech to text     who speaks when

  shared by all:  models/   runtimes/   catalog.json   ~/.mitra/memory (the log)   ~/.mitra/config.json
```

What apps share: the runtimes, the model files, the governor and the memory log. What they never share: a process, a port, a window, or each other's routes.

## 3. The parts

### 3.1 Launcher (`gateway/`, Go)

- The same binary, `bin/mitra-marketplace.exe`, is the launcher, each app's process, and the command-line tool.
- As launcher it listens on `127.0.0.1:7421` and serves the welcome screen, the icon grid, and three pages: **Create** (make an app from a sentence), **Memory** (what you did, by week or month), **System** (RAM, apps running, the model running, limits).
- It refuses work: `/api/convert`, `/api/ask`, `/api/upload` and any app's own routes answer 409. Its job is to start apps and show state.
- It exits when its window closes and nothing is open (`idle_exit_min`, default 10).
- Files: `main.go` (commands, routing), `assoc.go` (file types, drop to open, Windows registration).

### 3.2 An app's process (`mitra-marketplace app <id>`)

- One per open app, on a random port, opened as a bare Chrome or Edge window with no tabs or address bar (`app_window`: `window`, `tab` or `none`).
- Serves that app's screen and routes only. A request meant for another app gets 403 or 404. Shared services are allowed only if the manifest lists them under `uses`; the assistant route only if `needs` contains `assistant`.
- Starts in about 110 ms. The window tells the process when it closes and the process ends five seconds later. A reload is not a close. If the window vanishes silently, it ends after `app_idle_exit_s` (150 seconds).
- A second click on a running app's icon reuses the same process.

### 3.3 Workers (`workers/mitra_workers/`, Python)

A fresh Python process per request, 28 to 38 MB, which exits when it has answered. Nothing is kept in memory between requests; state lives in files.

| Module | Job |
|---|---|
| `dispatch.py` | Turns a request into a function call; runs long work as a detached job with steps you can poll |
| `registry.py` | Finds apps (built-in `apps/`, yours in `~/.mitra/apps/`) and their manifests |
| `convert.py` | Any document to Markdown, keeping its structure |
| `models.py` | Picks a model for a capability, starts it under the governor, speech to text, speakers |
| `meeting.py` | Notes prompts, parsing, section merge |
| `grounding.py` | Checks every note and action item against the transcript |
| `gist.py` | Picks the two or three most informative sentences, quoted word for word; no model |
| `memory.py` | The log: append, report, prune |
| `manager.py` | Per-app review: what the app's models cost and whether anything came close to its limit |
| `builder.py` | Makes an app from a description |
| `paths.py` | Where things are; per-device config and its defaults |

### 3.4 Governor (`governor/`, Rust)

Every model process is started by `bin/mitra-governor.exe`, never directly.

- **One at a time, in a line.** A lock shared by every app, and a ticket for each one waiting (`~/.mitra/run/line`). The model goes to the head of the line: a question (`--priority interactive`) ahead of long jobs, then first come first served. Nothing in the line times out unless the caller sets a limit. `mitra-governor status` lists the line and what the running model is doing.
- **Callers that go away.** A waiter whose caller has gone (a cancelled question) leaves the line; a running model whose caller has gone is stopped. A model stopped by hand ends with its own code (143), which the job treats as a stop, not a failure.
- **Admission.** A model whose estimate is above the ceiling, or which would leave less than `reserve_mb` (800) free, is refused before it starts (`governor.denied`).
- **Its own cap.** Each model is held to its measured need plus about 10%, not to the ceiling. It is sampled twice a second and stopped if it goes over (`governor.evict`).
- **Second chance.** An audio model stopped at its own cap is run once more held only to the ceiling, and the event is logged (`model.cap_raised`). The ceiling itself is never exceeded.
- **Priority.** Models run below normal priority, on CPU, so the footprint is the same on every device.
- **Housekeeping.** Clears a lock left by a crash; `mitra-marketplace optimize` runs at start and every six hours.

`bin/mitra-ear.exe` (`ear/`, Rust, about 12 MB) records the microphone and the system's audio as two tracks in half-minute pieces, and reports which programs are recording from a microphone. `bin/mitra-open.exe` is another small Rust program (316 KB): Windows starts it when you open a file from Explorer, and it starts the right app with no console window flashing.

### 3.5 Screens (`web/`, `apps/*/ui/`, JavaScript)

- `web/index.html`: welcome screen and launcher pages.
- `web/static/sdk.js`: shared by every app. Top bar with the logo, RAM pill and Manager button; Ctrl+K go-to menu; the file browser with recent files; Markdown rendering; drop to open; `mitra.launch` to start another app; open and close logging.
- `web/static/mitra.css`: the look. Navy carries structure and text; saffron and amber mark the one primary action and "live" state. Light and dark.
- No framework and no build step. A page is one HTML file.

### 3.6 Catalog, config, log

- **`catalog.json`**: capabilities, not models. An app says what it needs (`assistant`, `meeting-notes`, `transcription`, `diarization`); Mitra picks the first candidate that is on the device and fits the ceiling. Each candidate carries its measured memory and the reason it is there.
- **`~/.mitra/config.json`**: per device. See section 9.
- **`~/.mitra/memory/events/`**: one line per event, from every process. See section 8.

## 4. What happens when

### 4.1 You click an icon

1. The page asks the launcher to start the app (`POST /api/launch/<id>`).
2. The launcher starts `mitra-marketplace app <id>` on a free port and logs `app.spawn`.
3. A bare browser window opens on that port. The SDK draws the top bar and logs `app.open`.
4. You close the window. The page tells the process; five seconds later it ends and logs `app.exit` with how long it lived.

### 4.2 You open a file

Each app's manifest lists the types it opens (`opens`). That one list drives three ways in.

| Way in | Path |
|---|---|
| Drop on the launcher or an icon | Page sends the file to `POST /api/drop/<app>`; it is kept as a temporary copy; the app starts on it |
| Drop anywhere in an app's window | Opens there if the app reads the type; otherwise goes to the app that does |
| Double-click or "Open with" in Explorer | After `mitra-marketplace register`: Windows runs `mitra-open.exe`, which runs `mitra-marketplace open <app> <file>` |

`register` writes only to your own user settings, adds a Start menu folder, and never sets a default itself; Windows lets only the person do that.

### 4.3 An app asks for work that needs no model

Page → app process → one Python worker → answer. Example: Anything to MD converts a Word file. Cost: about 30 MB for under a second. Logged as `api.call` with the worker's peak memory.

### 4.4 An app asks for a model

1. The worker asks `models.pick(capability)`: first candidate in `catalog.json` that exists and fits.
2. It starts the runtime through the governor with that model's own cap.
3. The governor takes the lock, checks free memory, starts the process, samples it.
4. The answer comes back; the model process is stopped; the lock is released. `model.run` records name, peak MB, cap, seconds and how it ended.

### 4.5 A long job (TwinMind)

`POST .../job/run` returns an id at once. The worker runs detached and reports each stage with `job.step`; the page polls `/api/jobs/<id>` and shows all five stages from the start, with seconds so far.

## 5. The applications

### 5.1 Mitra PDF (`apps/pdf-reader`)

| | |
|---|---|
| Opens | `.pdf` |
| Models | None |
| Uses | The shared converter |

- **Page view**: the browser's own PDF viewer, embedded.
- **Text view**: the document as structured text (headings, paragraphs, lists), from the converter.
- **Send to Anything to MD**: opens the same file there for saving as Markdown.
- **File browser** with recent files; **drop a PDF** anywhere, including over the page view.
- Not built: search inside the document, an outline panel, read aloud. Scanned pages have no text (see section 7.3 for the model that could read them).

### 5.2 Markdown Reader (`apps/markdown-reader`)

| | |
|---|---|
| Opens | `.md` `.markdown` `.txt` |
| Models | None |

- **Rendered view** of any Markdown file, with tables, code, quotes, links.
- **Outline** built from the headings; click to jump.
- **Source toggle**: the raw text.
- **Links between files** open in the reader; **Copy path**.
- **Find on open**: TwinMind's search opens a memo scrolled to the matching line.

### 5.3 Anything to MD (`apps/to-markdown`)

| | |
|---|---|
| Opens | `.docx` `.pptx` `.xlsx` `.html` `.htm` `.csv` `.tsv` `.json` `.ipynb` `.epub` `.rtf` `.odt`, and anything no other app claims |
| Models | None |

Converts a document to Markdown and keeps the document's own structure.

| Source | Kept |
|---|---|
| Word | Title and heading levels (read by style name, so Word in other languages works), bold, italic, links, nested and numbered lists, tables with merged cells. With no styles, headings are read from larger or bold type |
| PDF | Headings from type size, then short bold lines; wrapped lines joined into paragraphs across page breaks; hyphenated words rejoined; lists; addresses keep their line breaks; running headers, footers and page numbers removed |
| PowerPoint | A section per slide titled from its title box; bullet levels; tables; speaker notes |
| Excel, CSV, TSV | Tables |
| HTML, EPUB | Headings, real tables, nested lists, quotes; EPUB in reading order |
| RTF, ODT | Headings, bold, italic, links, lists, tables |
| Notebooks, JSON, code, subtitles | Cells, structure, fenced code, timed lines |

- **Preview** beside the source; **Save .md** beside the original (or to Downloads for a dropped file, because a browser never reveals where a dropped file lives).
- Not handled: tables inside PDFs, two-column PDF layouts, scanned pages.

### 5.4 TwinMind (`apps/twinmind`)

| | |
|---|---|
| Opens | `.wav` `.mp3` `.m4a` `.ogg` `.flac` `.vtt` `.srt`, and transcripts in text, Word, RTF, ODT, PDF, HTML |
| Models | Speakers, speech, notes: three, one after another |
| Writes to | `Dropbox/Mitra/TwinMind` |

A recording or a transcript in; a memo out, in your MeetingNoter layout.

**The pipeline**

| # | Stage | What does it | Measured on your calls |
|---|---|---|---|
| 1 | Who speaks when | NVIDIA Sortformer (audio.cpp, streaming mode) on windows of 5 minutes that overlap by 45 seconds. A voice keeps its number across windows by who was talking in the overlap, or by elimination when exactly one voice is unaccounted for. Otherwise it gets a new number, never someone else's | 170 to 187 MB per window, flat for any length. About 12 s per minute of audio |
| 2 | What was said | Whisper medium, 99 languages, greedy decoding, on pieces of 5 minutes cut in pauses. Each piece is heard whole with word timings. Each sentence goes to the speaker talking for most of it. Hindi and English come out as one English transcript. Whisper small takes over if this device cannot give medium the memory, and the memo says so | 964 to 980 MB. About 25 s per minute |
| 3 | Gist | Plain code picks two or three sentences and quotes them word for word | No model |
| 4 | Notes | Gemma 3 1B, section by section (about 420 words each): topic, points, decisions, open questions, action items as constrained JSON. Qwen3 0.6B takes over if this device cannot give Gemma the memory, and the memo says so | 915 to 945 MB |
| 5 | Check | Every note and action is tested against the transcript (below) | No model |
| 6 | Memo | Markdown, written to the Dropbox folder | |

A 4-minute call takes 3 minutes 18 seconds; a 16-minute call took 12 minutes 17 seconds.

**The check (grounding)**

- A number, owner or date that the transcript never says is removed, or the item is.
- An owner or date is kept only if it was said in a line about that task.
- A transcript line pasted in as a "note" or "task" is dropped. So are "Correct" and "Thank you".
- A title is kept only if most of its words were said; otherwise the first topic is used.
- The memo lists what was removed for being wrong and counts what was dropped as echo.

**The memo**

Meeting Core Focus (quoted) · Key Discussion Points by topic with decisions under each · Action Items with owners · Commitments heard (every promise or request, quoted one sentence each with time and speaker) · Follow-up Needed · the full transcript. The header records every stage, including any that did not run and why.

**Long calls and several apps at once (0.9.0)**

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

**A meeting as it happens (0.10.0)**

| Step | How |
|---|---|
| **Noticing a meeting** | While TwinMind's window is open it asks its own process every five seconds which programs are recording from a microphone. The answer comes from Windows' audio sessions, read by `mitra-ear who`; nothing is listened to. If one of them is a call app (Teams, Zoom, Webex, Slack, WhatsApp, a browser and so on) a banner asks "Do you want me to record it?", with "Not this one". Someone talking near the laptop is not a meeting, and neither is a dictation tool. Nothing watches when Mitra is closed |
| **Recording** | `mitra-ear` (Rust, about 12 MB, no model) records two tracks at 16 kHz: your microphone, and whatever the computer plays, which in a call is everyone else. Nothing joins the call. Each track is written in half-minute pieces under a temporary name and renamed when complete, so a crash loses at most the half minute in hand, and both tracks follow the wall clock so piece N covers the same half minute on each |
| **The transcript as it grows** | Each finished piece goes through the smallest multilingual speech model (Whisper base, about 2 s per piece, 356 MB while it runs, nothing between pieces). A silent piece runs no model. A line that runs into the end of a piece is held back and heard whole with the next one. Lines are marked with your name or "Others" by track |
| **Your notes** | A box beside the transcript; what you type is saved as you go and put in the memo as written |
| **When you stop** | The pieces are put together into one recording per track and a mix, and the full pipeline writes the memo: speakers, the accurate speech model, notes, the check. The speaker heard on the microphone track is named as you. Recordings are kept 30 days (`keep_recordings_days`), then go to the Recycle Bin |
| **If the app is closed mid-meeting** | The recorder ends cleanly and the Live tab offers "Write its memo" next time |

Memory is flat for any length: one piece is handled at a time and everything so far is on disk. Checked on 2026-11-20 with a two-minute recording of synthesized speech played through the speakers: both tracks recorded, every sentence in the live transcript after two faults were fixed (an invented "Thank you" from the silent microphone track, and a sentence lost at a piece boundary), and a correct memo with the typed note in it. **Not yet run on a real meeting, on a real voice at the microphone, or for hours**; the live speech model is a provisional choice that gets names wrong (the memo's model does not).

**Other features**

- **Who is who?** After a memo is written the page shows each voice with a line it said. Type a name and the memo is rewritten with names throughout.
- **Find what was said**: search across every memo; passages are quoted exactly; a hit opens the memo at that line.
- **Meetings list** with gist and action count.
- **`transcribe_language`**: `english` (default), `original`, or a language code.

**Honest limits**: the notes still give some statements to the wrong speaker and repeat any translation error as fact. On a call that is mostly advice or discussion, with few real tasks, the action list fills with descriptions of what was said ("Recommend relaxing", "Ask for a different perspective") instead of tasks. Speaker boundaries are per sentence, so overlapping speech goes to one person. Tried on two real two-person phone calls (4 and 16 minutes); not on a room, on four or more people, or on over an hour.

### 5.5 Ask Mitra (`apps/assistant`)

| | |
|---|---|
| Opens | Nothing |
| Models | The one general question-and-answer model: Qwen3 0.6B, 564 MB |

- Ask a question; the answer shows the model, seconds and MB.
- Keeps the thread of a conversation (the last few turns are sent as real turns).
- The RAM pill returns to "no model loaded" after each answer.

### 5.6 Apps you create

`mitra-marketplace new "a tracker for supplier quotes kept in my Dropbox"` or the Create page. The builder writes a folder in `~/.mitra/apps/` with a manifest (name, icon, connector, the capabilities it needs) and a generic workspace screen. It appears as an icon, runs as its own process, travels with `push` and `update`, and can be zipped alone with `pack`. `APP_SPEC.md` describes how to give it its own screen and logic.

### 5.7 Launcher pages

- **Welcome**, then the **icon grid**: a green dot and memory figure on each running app.
- **Create**: describe an app.
- **Memory**: weekly, biweekly or monthly report of what you opened, converted, asked and recorded; most-used first; saved reports; prune.
- **System**: RAM, apps running now, the model running now, limits, package size.
- **Ctrl+K** in every window: go to any app or page.

## 6. Rules the system keeps

| Rule | How it is kept |
|---|---|
| Nothing in memory when nothing is open | Launcher and apps exit on close; workers exit on answer; models are stopped after each use |
| One model at a time | The governor's lock, shared by all apps |
| No model above 1,024 MB | Admission check, per-model cap, sampling twice a second |
| Apps are separate products | Separate processes and ports; routes refused across apps |
| Only this device | Listens on 127.0.0.1; requests with a foreign host or origin are refused; no path may escape the folders it is given |
| Every use is logged | One log for all processes, including refusals and stops |
| The same on every device | CPU only, capabilities resolved per device, no size taken from this machine's hardware |

## 7. Models

### 7.1 What runs today

| Job | Model | File | Peak RAM | Runtime |
|---|---|---|---|---|
| Ask Mitra | Qwen3 0.6B Q4_K_M | 378 MB | 564 MB | llama-server |
| Meeting notes | Gemma 3 1B Q4_K_M | 769 MB | 915 to 945 MB | llama-server |
| Meeting notes, fallback | Qwen3 0.6B Q4_K_M | 378 MB | 564 MB | llama-server |
| Speech to text | Whisper medium Q5_0, greedy | 514 MB | 964 to 980 MB | whisper.cpp |
| Speech to text, step-down | Whisper small Q5_1 from the library when it is attached; otherwise Whisper base Q5_1 from the package (57 MB) | 181 MB | 605 to 637 MB (base: 356 MB) | whisper.cpp |
| Who speaks when | Sortformer (Nemotron 3 diarization) Q8 | 102 MB | 170 to 187 MB | audio.cpp |

Settings that matter: 1,536-token context, 8-bit context cache, and weight repacking off (`--no-repack`), which alone took Qwen from 762 to 564 MB and Gemma from 987 to about 915 MB.

### 7.2 Search of the model library, 2026-11-13

`E:\Local AI Models` holds 157 models. A model can be used only if it runs on CPU in one of the three runtimes in the package (or a small added one), and peaks under 1,024 MB. That rules out everything in safetensors or PyTorch format (it needs a 2 GB+ framework) and everything above about 1B parameters at 4 bits.

**Measured on your real 4-minute call**

| Candidate | For | Peak RAM | Result | Verdict |
|---|---|---|---|---|
| **Whisper medium, 5-bit, greedy decoding** (made from the library's `ggml-medium.bin`) | Speech | 934 to 949 MB | Clearly better than small: correct names of what was pitched, who tells whom, clean short sentences. 108 s against 41 s for the same call | **Switched on, 2026-11-13.** In the app it peaks at 964 to 980 MB |
| Whisper medium, 5-bit, default decoding | Speech | 1,234 to 1,268 MB | Same quality | Over the ceiling |
| Whisper large-v3-turbo, 5-bit | Speech | 861 MB | Dropped whole stretches and looped; it was not trained to translate | Rejected |
| Gemma 3 1B Q4_K_M | Notes | 915 to 945 MB | Concrete points and real tasks | In use |
| Gemma 3 1B Q4_0 | Notes | 830 MB | Thinner notes than Q4_K_M | Kept as a candidate for ceilings between 860 and 940 MB |
| SmolLM2 1.7B Q3_K_S | Notes | 998 MB | Garbled title, one task | Rejected |
| Qwen3 0.6B | Notes | 564 MB | Mostly echoed transcript lines | Fallback only |

**Measured on 12 general questions (Ask Mitra)**

| Model | Right | Peak RAM | Time |
|---|---|---|---|
| Qwen3 0.6B | 8 of 12 | 531 MB | 18 s |
| Gemma 3 1B | 7 to 8 of 12 | 856 MB | 35 s |

Gemma knew the capital of Australia where Qwen did not; Qwen did the arithmetic Gemma got wrong, and answered briefly where Gemma ran past the length limit. Neither translated a Hindi sentence. No reason to change Ask Mitra.

**Checked for feasibility**

| Model in the library | Would add | Finding |
|---|---|---|
| SmolVLM 256M (GGUF with its image projector, 266 MB) | Reading scanned pages and images in Anything to MD and Mitra PDF | Runs in the llama-server already in the package. Read five lines of a test page correctly in 3 seconds at 404 MB, then kept writing an invented table, so its output needs to be cut off and checked. Not tried on a real scan |
| Piper TTS, amy (ONNX, 60 MB) | Read aloud | The audio runtime in the package wants this voice in a different packaging and refused the file. Needs the Piper runtime or a converted voice |
| all-MiniLM-L6-v2 (22 MB) with the TinyBERT reranker (8 MB) | Search meetings by meaning, not only by word | Both are ONNX. Needs `onnxruntime` and `tokenizers` installed (about 20 MB); not installed, not tried |
| bge-m3 int8 (542 MB), multilingual-e5-base (529 MB) | The same, across Hindi and English | As above; larger |
| Silero VAD (ONNX, 2 MB) | Skipping silence before speech to text | whisper.cpp needs its own build of this model, which is not in the library |
| DeepSeek-R1 distill 1.5B, Qwen2.5 1.5B Q2, StableLM Zephyr 1.6B, larger | Notes | Too large at a usable precision, or 2-bit and poor |
| granite-docling, Florence-2, TrOCR, layout and table models | Documents | Need PyTorch; outside the package's limits |

### 7.3 Combinations worth building

| Combination | What it gives | Cost |
|---|---|---|
| **Whisper medium (greedy) → Gemma 3 1B** | The notes model inherits every transcript error, so a better transcript is the largest single gain to notes as well. On the test call it removed the mistakes that later became wrong notes | **Done.** 980 MB then 945 MB, one after the other. A 16-minute call takes 12 minutes 17 seconds instead of 7 minutes. To stay inside 2 GB, two unused runtime programs were removed and the packaged step-down is Whisper base, not small |
| **Quoted commitments → Gemma** | Action items built from the sentences the pattern finder already quotes, with Gemma only naming owner, task and date for each. Every task would then trace to a spoken line | No new model |
| **MiniLM + reranker + Gemma** | "Ask your meetings": find passages by meaning, answer with the meeting and timestamp cited | 30 MB of models, one added Python package |
| **SmolVLM for scans** | Scanned PDFs and photos become text | 266 MB in the package, 404 MB while reading |

The first is switched on (2026-11-13). The other three are not built.

## 8. The memory log

Every process appends to `~/.mitra/memory/events/<date>.jsonl`.

| Event | Written when |
|---|---|
| `app.spawn`, `app.launch`, `app.exit` | An app's process starts, how it was opened, why and after how long it ended |
| `app.open`, `app.close` | A window opens or closes, with active time |
| `file.open`, `file.drop` | A file is opened or dropped |
| `action.*` | Something you did: converted, asked, processed a meeting, named speakers, searched |
| `api.call` | A request, with milliseconds and the worker's peak memory |
| `model.load`, `model.run`, `model.call` | A model starts, ends (peak, cap, seconds, how), answers |
| `governor.denied`, `governor.evict`, `model.cap_raised`, `model.fallback` | A refusal, a stop, a retry at the ceiling, a switch to a smaller model |
| `model.wait`, `model.wait_left`, `model.yield` | Someone waited in line for the model, left the line, or a long job stepped aside for a question |
| `job.queued`, `job.paused`, `job.stopped`, `job.resumed` | A recording joined the line; a job was paused, stopped, or picked up from its saved pieces |
| `error` | Anything that failed, with a trace |

`mitra-marketplace memory report weekly|biweekly|monthly` turns the log into a report; `memory prune [DAYS]` rolls up and archives what is older. Each process's own console output is in `~/.mitra/logs/<app>.log`.

## 9. Settings (`~/.mitra/config.json`)

| Key | Default | Meaning |
|---|---|---|
| `models_dir` | `E:\Local AI Models` | The model library; the package's own `models/` is looked in first |
| `model_budget_mb` | 1024 | The ceiling for any model |
| `reserve_mb` | 800 | Free memory that must remain after a model loads |
| `app_window` | `window` | `window`, `tab` or `none` |
| `app_idle_exit_s` | 150 | An app with no window ends after this long |
| `idle_exit_min` | 10 | The launcher's idle exit |
| `assistant_ctx` | 1536 | Context length for the language models |
| `transcribe_language` | `english` | `english`, `original`, or a code such as `hi` |
| `connectors.dropbox` | found automatically | Where the synced Dropbox folder is |

## 10. Moving between systems

1. `mitra-marketplace test`, then `push`: packs code and binaries (about 10 MB) into `Dropbox/Mitra/releases` with a checksum.
2. On another machine with Mitra: `update` verifies the checksum, installs, removes files the release no longer ships. Your created apps travel.
3. On a new machine: `install.ps1` (Windows) or `sh install.sh`.

Models and runtimes are not in the release zip. Run `mitra-marketplace models sync` with the library attached, or copy `models/` and `runtimes/` once.

## 11. Tests

`mitra-marketplace test` runs 343 cases in about 26 minutes; `--quick` skips the ones that load real models. The suite uses its own port and temporary home, so your log, apps and Dropbox are untouched. Last full run: 343 of 343 on 2026-11-14. A real call of over two hours was started on 2026-11-14 and stopped by hand at 34 minutes; it has not been run to the end (see `TEST_PLAN.md`).

The automated recordings are synthesized speech, which is what let TwinMind ship broken in 0.7.0. The real check is manual and required before any push that touches audio: `python logs/scripts/twinmind_real_run.py "<recording>"`. See `TEST_PLAN.md`.

## 12. Where things are

```
mitra-marketplace/
  bin/                 mitra-marketplace.exe · mitra-governor.exe · mitra-open.exe
  gateway/             Go: launcher, app process, commands, file types
  governor/            Rust: governor and the file handler
  workers/             Python: mitra_workers/
  web/                 launcher page, sdk.js, mitra.css, brand/
  apps/                pdf-reader · markdown-reader · to-markdown · twinmind · assistant
  models/              the models the apps use, copied in by `models sync`
  runtimes/            llama/ · whisper.cpp/ · audio.cpp/
  catalog.json         capability → candidate models, with measurements
  docs/                this file, architecture.html, interface review, research
  logs/scripts/        every script written while building and measuring
  logs/tests/          run_tests.py and results/
  docs/wireframes.html every screen and state, with notes
  README.md · APP_SPEC.md · TEST_PLAN.md · FINETUNE_PLAN.md

~/.mitra/              config.json · apps/ (yours) · memory/ · logs/ · handlers/ · tmp/
~/.mitra/run/          model.lock · line/ (tickets) · work/<job>/ (saved pieces) · jobs/ · twinmind-line.json (recordings waiting)
```

## 13. Not built, and known limits

- TwinMind: a meeting page with notes beside the transcript and playback; calendar tagging; voice enrolment; chat over meetings with citations.
- Mitra PDF: search, outline, read aloud. Scanned pages.
- The speaker model reserves about 3.2 GB of virtual memory at start and uses about 180 MB; where that cannot be promised the memo is written without speakers and says why.
- The Windows "Open with" menu, Default apps page, a real drag from Explorer and the Start menu entries were registered and checked on disk and in the registry, not seen in use.
- An app's window groups under the browser's taskbar icon.
- macOS, Linux and Termux: not built or run.
