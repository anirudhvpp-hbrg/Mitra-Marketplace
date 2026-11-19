# Approach note: one marketplace or individual applications

Written 2026-11-11 as the analysis before the work. **Decision: you chose option C the same day, and it is built (version 0.6.0).** The other four decisions in section 7 were not answered, so the build uses these defaults, each changeable: a bare window per app (decision 2), one model at a time across apps with TwinMind's three in turn (3), Qwen3 0.6B kept (4), and no earlier Mitra PDF or Anything-to-MD work assumed (5). Measured after building: the package is 657 MB with the models inside it, 755 MB counting ffmpeg; an app's process starts in about 110 ms and holds about 12 MB. The text below is the note as written.

## The question

You want a welcome screen, then a list of apps as icons, and each app (Mitra PDF, Anything to MD, TwinMind, and so on) to be its own product that is only started when its icon is clicked. Today Mitra is one program that hosts every app's screen. This note compares the options, using numbers measured on this laptop, and recommends one.

## 1. What I found on the E: drive

I searched the whole drive by folder name for earlier work on the three apps and read what I found.

| App | What exists on E: | State | Reusable |
|---|---|---|---|
| **TwinMind** | `Conversations & Meeting Transcripts\04 Projects and Tools\twinmind-local`: a ten-document development plan (requirements, architecture, contracts, Android app, Mac mini server, roadmap, risks, decisions, backlog), dated 2026-09-29 | Design only. Every backlog item is unticked; no server code is in the folder | The requirements and decisions, as the specification |
| | `...\04 Projects and Tools\MeetingNoter`: a desktop app (Electron shell, Python backend, 36 files), June 2026. Upload a batch, transcribe with Whisper, write notes with a local model through Ollama, keep a searchable library, export | Working code by the look of it; I did not run it | The notes format, the document extractors, the library and batch ideas |
| | `Old LLM Data\TwinMind`: 354 meeting notes; `Code Files\06_TwinMind_Intelligence`: summaries | Data, not code | As test material, with the client-content caution from before |
| | `Old LLM Data\DSH\twinmind-mcp`: a connector to the TwinMind service | Code | Only if Mitra should read the TwinMind service; not needed for your own |
| | APTM (Mitra Ear) | Already absorbed on 2026-11-11 | Done |
| **Anything to MD** | `Skills, Capapbilities and Repos\markitdown-main-extract`: Microsoft's markitdown source; a `markitdown` skill file | Third-party source, not your own app | As a reference for formats Mitra lacks |
| | `MeetingNoter\backend\services\document_processor.py`: extractors for TXT, PDF, DOCX, RTF, Markdown, HTML, ODT, CSV, XLSX | Your code | RTF and ODT, which Mitra's converter does not read |
| **Mitra PDF** | No app. Only skill files (`nano-pdf`, `pdf-text-extract`, `pdf`) and a PDF library inside another vendor's app | Nothing to consolidate | Nothing found |

**Two things I could not find.** There is no folder on E: that looks like a Mitra PDF app or a dedicated Anything-to-MD app. If that work exists under another name or on another drive, tell me the folder and I will read it. I searched folder names, not file contents, so work kept inside a differently named folder could have been missed.

### What the earlier TwinMind work says that Mitra should take

- **Your notes format.** MeetingNoter's prompt defines the format your 854 archived notes use: a dated title, meta-information with a participant power map, "Meeting Core Focus", "Key Discussion Points" by topic with a "Decisions made" paragraph each, "Action Items" as dated bullets with owners, "Follow-up Needed", then the transcript. Mitra's memo uses a different, shorter layout. Your format should become TwinMind's main template.
- **A caution with that.** The prompt was written for a 9-billion-parameter model (`gemma2:9b`) reading the whole transcript at once. Qwen3 0.6B with a 1,536-token window cannot follow it as written. It would have to be produced section by section, and the power map and "blast radius" analysis are beyond a model this small. This is the main tension between your 1 to 2 GB package limit and the notes quality your own format expects.
- **Requirements from the plan that Mitra does not meet yet:** search across all transcripts in under two seconds, chat that cites the conversation and timestamp, calendar tagging, delete that removes audio and transcript together, audio kept for 30 days, voice enrolment so your own voice is labelled automatically, and tap a transcript line to play it.
- **Requirements Mitra already meets:** speaker labels, summary with decisions and action items, staged jobs that survive a failure, audio never leaving the machine.
- **A decision that differs.** The September plan chose cloud models for summaries, with only transcripts leaving the machine, because local models were not good enough. Mitra is fully local. That earlier judgement about quality still holds: it is the reason the notes need checking.
- **From MeetingNoter:** batch upload, a library with tags and counts of decisions and actions, export as a zip, a choice of Whisper size, and settings on screen.

## 2. The three options

**A. Marketplace (what exists today).** One small program serves every app's screen. Clicking an app opens a page. Conversion and models start on demand.

**B. Fully individual applications.** Each app is a separate product with its own installer, its own copy of the runtimes it needs, and its own model.

**C. Individual applications on a shared base.** A launcher shows the welcome screen and the icons. Clicking an icon starts that app as its own process in its own window; closing the window ends it. The apps share one set of runtimes, one model store, one governor and one log.

## 3. Trade-offs, with measured numbers

Package sizes are measured from the files on this laptop. Python is estimated at 30 MB.

| | A. Marketplace | B. Fully individual | C. Individual on a shared base |
|---|---|---|---|
| **What you see** | One site with pages | Separate programs, each installed on its own | Welcome screen, icons, each app in its own window |
| **Matches "spawn on click"** | Partly: only the heavy work is spawned | Yes | Yes |
| **Total package** | About 790 MB | About 1,340 MB: PDF 43, Anything to MD 43, Ask 460, TwinMind 790 | About 800 MB |
| **Inside your 1 to 2 GB** | Yes | Yes, but it grows by about 460 MB for every further app that needs the assistant model | Yes, with room for a larger model |
| **Copies of the 378 MB model** | One | One per app that uses it (two today) | One |
| **RAM with nothing open** | 0 (the server exits when idle) | 0 | 0 |
| **RAM per open app, no model** | About 20 MB in total for all apps | About 20 MB each | About 20 MB each |
| **RAM while a model runs** | 150 to 760 MB, one at a time | Same per app; one at a time only if every app honours the same lock | Same; one at a time, enforced by the shared governor |
| **Start time** | App list 0.2 s; a page opens at once | Each app starts cold | Launcher at once; an app's process in well under a second (estimate, not yet measured) |
| **Logs** | One log for everything | One per app unless they share a folder | One log for everything |
| **Updating** | One push updates all | One release per app | One push updates all |
| **If one app crashes** | The others are pages of the same server; the server is small and has not crashed in testing | Others unaffected | Others unaffected |
| **Adding an app** | A folder with a manifest | A new product with its own packaging | A folder with a manifest |
| **Phone (Termux)** | Works: a browser tab | Each app installed separately | Works, but as browser tabs; a phone has no separate windows |
| **Work to get there** | Done | Large: packaging, updating and testing multiplied by the number of apps | Moderate: a launcher, a process per app, window handling, tests |

## 4. Considerations beyond the table

- **"One app, one model."** I read this as: each app declares the one model it uses, and only one model runs at any moment across all apps. TwinMind is the exception worth deciding: it needs three small models in turn (speakers, transcription, notes), never two at once. If you meant something else, this note's sizing changes.
- **A separate window.** Chrome and Edge can open a page as a bare window with no tabs or address bar, which makes each app look like a desktop program without shipping a browser. Shipping a real desktop shell per app would add roughly 100 MB or more to each and push option B well past 2 GB.
- **The external drive.** All models live on E:. Whatever the option, an app that needs a model cannot run with the drive unplugged. The package limit suggests copying the three models Mitra uses (about 510 MB) onto the laptop.
- **Light spawning and model quality pull in opposite directions.** The package fits in 800 MB because the model is 378 MB. Your own notes format wants a much larger one. A 1 to 2 GB limit leaves room for a model of about 1 GB, which is the next real step up in quality, at around 1.5 to 2 GB of RAM while it runs.
- **Saving all logs.** One shared log is what makes the weekly review possible. Option B splits it unless every app is told to write to the same folder, at which point it is option C.

## 5. Cost and benefit

| | Cost | Benefit |
|---|---|---|
| **Stay with A** | None | Lightest and already tested; but it does not give you separate apps |
| **Move to B** | The most work, repeated for every app and every update; duplicated models; logs and the one-model rule must be re-joined by hand | Each app can be handed to someone else on its own; total independence |
| **Move to C** | One moderate piece of work; the 38 existing tests mostly carry over | Separate apps you spawn from icons, at the same size and with the same single log, governor and update path |

## 6. Recommendation

**Option C.** It gives you what you described (welcome screen, icons, each app its own process started only on click) without paying option B's costs. Option B is only worth it if you intend to give individual apps to other people as standalone products; if that is the plan, C can still produce a standalone bundle of one app later, because each app is already a self-contained folder.

What C would involve:

1. A welcome screen, then an icon grid, replacing today's home page.
2. Clicking an icon starts that app's own process on its own port and opens it in its own window; closing the window stops the process.
3. Each app keeps its manifest and declares its one model; the shared governor keeps to one model at a time.
4. TwinMind gains your MeetingNoter notes format as a template, the meeting page from the interface review, RTF and ODT input, and the requirements listed in section 1.
5. The models Mitra uses are copied from E: into the package so it runs with the drive unplugged.
6. The test suite grows from 38 to between 150 and 200 cases.

### How the larger test suite would be made up

| Area | Cases |
|---|---|
| Launcher: welcome screen, icons, start and stop of each app, two apps at once, crash of one | 20 |
| Each app's screen and features, five apps | 60 |
| Conversion, one case per format plus damaged and empty files | 25 |
| Governor: limits, one model at a time across apps, stop, crash recovery | 20 |
| TwinMind pipeline: each stage, each skipped stage, the notes template, grounding | 25 |
| Memory log, reports, pruning | 12 |
| Install, push, update, prune across systems | 12 |
| Security: requests from outside, file paths, unsafe zips | 12 |
| Resource use: nothing left running, RAM caps, idle exit | 10 |
| **Total** | **196** |

## 7. Decisions needed from you

1. **Option C, or B?** C unless the apps are to be given away individually.
2. **The window:** each app in its own bare window, or in a browser tab?
3. **"One app, one model":** is my reading in section 4 right, and is TwinMind's three-models-in-turn acceptable?
4. **Notes quality against size:** keep Qwen3 0.6B (800 MB package, notes need checking), or allow a model of about 1 GB (about 1.4 GB package, better notes, more RAM while it runs)?
5. **Mitra PDF and Anything to MD:** is there earlier work under another name or location that I should read?
