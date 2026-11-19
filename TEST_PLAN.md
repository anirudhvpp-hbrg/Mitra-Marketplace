# Mitra test plan

## How to run

```
mitra-marketplace test             all 361 automated cases, about 25 minutes (most of it two long recordings and the real-model cases)
mitra-marketplace test --quick     skips the cases that load real models; about four minutes
mitra-marketplace test T040 T227   only the named cases
python logs/tests/run_tests.py --list    print every case with its number
```

The suite (`logs/tests/run_tests.py`) starts a private launcher on port 7499 with its own temporary home folder and with window opening switched off, so your real memory log, apps, config and Dropbox are not touched and nothing appears on screen. Apps are started the way an icon starts them, as separate processes. Each run writes a report to `logs/tests/results/` with a per-area table and one line per case. Exit code is 0 only when nothing failed.

## Last result

2026-11-20, Windows 11, Python 3.13, version 0.10.0, 361 cases.

| Run | Result | Report |
|---|---|---|
| Full suite | **357 of 361**; the four failures are explained below | `logs/tests/results/2026-11-20-011118.md` |
| The long-recording cases again, alone (T309 to T311) | 3 of 3 | `2026-11-20-012505.md` |
| Quick suite after the fixes to the tests (real-model cases skipped) | 343 of 343, 18 skipped | `2026-11-20-012850.md` |

**There is no single full run with every case passing on the final code.** The four failures of the full run:

- **T310, real and not explained.** On the eight-minute synthesized recording the accurate speech model peaked at 1,066 MB, over the 1,024 MB ceiling. It was not stopped, because the governor stops a model only above the ceiling plus ten percent for a second and a half. It has peaked at 964 to 980 MB in every other run, including the same case run alone afterwards. The names prompt added that week was suspected and measured: 973 MB with no prompt, three names or forty (`logs/scripts/measure_prompt_memory.py`). Seen once in four runs of that case. **Open.**
- **T343 and T348, the tests.** The library cases counted every memo in the shared test folder, which by then held memos from other cases (17 meetings, not 3). They now use their own memo folder and their own port.
- **T361, the test.** "Nothing is left running" stopped only the main test home; apps started in two other test homes by later cases were still up. It now stops those too.

The 18 new cases are areas P (the meeting library, T343 to T351) and Q (live meetings, T352 to T360); "stopping everything" is T361.

### Live meetings: what was checked by hand, 2026-11-20

| Checked | How | Result |
|---|---|---|
| Recording | Started from the Live tab; two minutes of synthesized two-voice speech played through the speakers | Both tracks written in aligned half-minute pieces; the recorder held 12 MB |
| Transcript as it grows | Watched in the page | Lines appeared piece by piece. Two faults found and fixed: an invented "Thank you" from the silent microphone track, and a sentence lost where it straddled two pieces. Replayed on the saved pieces afterwards: all 13 sentences, none invented |
| Notes typed during the meeting | Typed in the page | In the memo, as written |
| Stop, then the memo | "Stop and write the memo" | The full pipeline ran on the recording; the transcript was right (name and "40 lakh rupees" included), three action items with the right owners |
| Noticing a meeting | A copy of the recorder named like a call app, recording from the microphone | The banner "Zoom is using the microphone. It looks like a meeting. Do you want me to record it?" appeared within five seconds; "Not this one" dismissed it; it cleared when the program stopped |

**Not checked:** a real Teams, Zoom or browser call; a real voice at the microphone (the room was silent, so "the microphone track is you" has only been tested on made-up tracks); a meeting of hours; two people talking at once; what happens when the laptop sleeps mid-meeting. The live transcript's speech model is a provisional choice (the smallest multilingual one) and wrote the owner's name wrongly; the survey of candidates for that role on at least a hundred held-out cases has not been done.

One thing found on this machine: Windows' own list of which program last used the microphone (the one behind Settings > Privacy) is not updated on this build, so meeting detection reads the audio sessions instead (`mitra-ear who`), with that list as a second source.

## Result of 2026-11-14 (0.9.0)

2026-11-14, Windows 11, Python 3.13, version 0.9.0: **343 of 343 passed**, none skipped, in 1523 seconds. Report: `logs/tests/results/2026-11-14-142010.md`. This run is on the final code.

The 31 new cases are area O (T312 to T342); "stopping everything" moved to T343 so that it stays last. The run before it on the same day (`2026-11-14-134726.md`) failed three:

- **T341, real.** A job failed with `[WinError 5] Access is denied` while saving its own progress file. On Windows a file cannot be replaced while another process is reading it, and the launcher reads a job's file each time the page polls. Every save now retries for up to two seconds (`logs/scripts/fix_replace_race.py`). This is very likely what failed T227 once on 2026-11-13; T227 has passed in every run since.
- **T332 and T342, the tests.** T332 expected no saved pieces anywhere, but a failed job rightly keeps its own; it now checks its own job. T342 found a leftover from T341's failure.

### The first long real run, 2026-11-14, and what it found

A 2 hour 25 minute phone call was started through the running app (Accurate), with a 4-minute call queued behind it (`logs/scripts/long_call_run.py`). **It did not finish: 34 minutes in, the model was stopped from the System page and TwinMind was closed from the launcher, by hand.** What was seen before that:

| Checked on the real call | Result |
|---|---|
| Estimate before starting | 117 minutes for 145 minutes of audio: 34 windows, 29 pieces, about 52 sections |
| Second recording added while the first ran | Joined the line |
| A question in Ask Mitra while speakers were being found | Waited 58 s for its turn, answered at 529 MB |
| A document converted in Anything to MD during the job | 2.4 s |
| Pause | Ended after window 7 of 34, no model process left, shown as paused with 7 windows kept; Resume carried on from window 8 |
| Speaker windows | 29 of 34 done and on disk when it was stopped, about 75 s each, 168 to 177 MB |

Stopping it by hand exposed two defects, both fixed and now tested:

| Defect | Fix | Case |
|---|---|---|
| A model stopped by hand was treated as a model failure: TwinMind dropped the speakers and went on to the next stage | The governor reports a stop by hand as its own outcome (exit 143); the job stops with its pieces kept | T340, T341 |
| Closing TwinMind from the launcher ended the app but left its job's worker running with no app; it went on to the next recording in the line | Closing an app stops its job workers first; the job shows as unfinished next time | T342 |

**Not yet seen on a real long call:** the speech and notes stages past the first window, a question during those stages, a hard stop mid-piece and resume (done on the 8-minute synthesized recording, T339), the queued recording being written afterwards (done with transcripts, T330), and the memo of a 2-hour call being read. The saved pieces of that run are still there; TwinMind shows it as unfinished with Resume.

## Result of 2026-11-13 (0.8.0)

2026-11-13, Windows 11, Python 3.13, version 0.8.0 with the 1 GB ceiling, Whisper medium for speech and Gemma 3 1B for notes: **312 of 312 passed**, none skipped, in 699 seconds. Report: `logs/tests/results/2026-11-13-054319.md`. This run is on the final code.

The run before it on the same day (`2026-11-13-052929.md`) failed two cases after Whisper medium was added:

- **T215, the package is inside the 2 GB limit.** Real: the new model took the total to 2,219 MB. Fixed by removing two runtime programs Mitra never runs and by packaging Whisper base, not small, as the step-down. Total is now 2,024 MB.
- **T227, two apps take turns for a model.** The meeting job failed once. The case then passed three times on its own and passed in the final full run. The report had cut off the job's error, so the cause is not known; the report now keeps a failed job's error text. Treat this as an open intermittent failure, seen once in three full runs.
The run before it (`2026-11-13-040616.md`) failed four cases after the ceiling and the notes model changed. Three were tests that still stated 800 MB (T136, T137, T147). The fourth, T224, was real: Gemma writes its points as plain lines under "Points:" with no bullet marks, the parser kept only bulleted lines, and a correct set of notes came out empty. The parser now takes every line under a heading.

A passing suite did not mean a working TwinMind in 0.7.0; read the next section before trusting this number. Alongside the suite, two real phone calls (4 and 16 minutes) were run through the app's own page and the memos read.

Version 0.7.0 passed 281 of 282 earlier the same day (`logs/tests/results/2026-11-12-024004.md`); the failure, T228, was the speaker model being refused the 3.2 GB of virtual memory it reserves, with Windows at its commit limit. It passes now with memory free. Cases T001 to T281 kept their numbers; the 30 new cases are T282 to T311, and "stopping everything" moved to T312 so that it stays last.

### What the suite missed, and why 0.8.0 exists

On 2026-11-12 you gave TwinMind a real recording, a 4-minute phone call, and it failed twice. The suite had passed. It tested recordings only with a 15-second clip of two synthesized English voices, so it could not see any of this:

| What happened on the real call | Why the suite did not catch it | What was done |
|---|---|---|
| The speaker model was stopped at 251 MB against a 208 MB cap; then the speech model at 268 MB against 208 MB; the job failed | Both caps were measured on 40-second clips. Memory grows with length: 149 MB at 42 seconds, 252 MB at 4 minutes | Audio is now heard in fixed windows (speakers) and pieces (speech) of 5 minutes, so memory is the same for any length; allowances re-measured on real calls; a model stopped at its own cap is run again up to the ceiling. T293, T294, T296 to T298, T309 to T311 |
| With the caps lifted, the transcript was nonsense ("Hello, hi David", "(speaking in foreign language)", a phrase repeated a hundred times) | The call is Hindi and English mixed; the model was Whisper tiny, English only. The synthesized test voices speak clean English | Whisper small, 99 languages, writing English; compared on the call by reading five candidates (`logs/scripts/compare_transcribers.py`). T295, T298 |
| Short replies ("Thank you", "Bye-bye", "Good evening" five times) that nobody said | Each speaker turn was cut out and transcribed alone; on a one-second clip a speech model invents a pleasantry | Each 5-minute piece is transcribed whole and the sentences are then given to speakers. T282 to T288 |
| Notes: a title wrapped in `**"..."**`, "Decisions made: ... (write - None if there are none)", action item "Thank you", transcript lines offered as points | The standup fixture is five clean sentences; the model behaves on it | Guards for each, and the memo counts what was dropped. T299 to T304 |
| "Speaker 1" and "Speaker 2" with no way to say who they are | Not a failure of a test: the feature did not exist | The page asks who is who after the memo is written. T305 to T308 |

What the 0.8.0 work itself found:

| Found by | What was wrong | What was done |
|---|---|---|
| Measuring the speaker model's virtual memory | It reserves about 3.2 GB at start whatever the recording, and uses about 180 MB. That, not length, is why it stopped on 2026-11-12 with Windows at its commit limit | Its runtime's settings for this were tried and are ignored. Recorded as a limit; the stage is skipped with the reason when the reservation is refused |
| T309, the long recording | The last window was a 48-second stub; the model heard two voices as one in it and everything after the join took one name | Every window is now a full five minutes; the last one ends at the end of the recording |
| T309 again | The speaker model hears the two synthesized Windows voices as one person for the first five minutes, in both of its modes | Not fixable here. The case now checks what the pipeline guarantees: the transcript reaches the end, two voices never become three, and from where the model tells them apart each keeps its label across the join |
| T224 | The new "copied from the transcript" guard removed every point from the clean standup, where a third-person sentence that matches the transcript is a fair note | A line counts as pasted only if it is several sentences or in the first or second person |
| A 16-minute real call | Title "Speaker 2: The Elephant in the Room"; a topic in angle brackets; a made-up title unrelated to the call | Labels and brackets stripped; a title is kept only if most of its words were said, else the first topic is used |

What the runs for 0.7.0 found:

| Found by | What was wrong | What was done |
|---|---|---|
| T171, when run between midnight and 05:30 | The test harness called the governor without telling it the time zone, so the governor wrote to the UTC day's log file and one day had two files. The product always passes the zone; the harness did not | Harness corrected. The governor still falls back to UTC if a caller forgets |
| T110, T112, T119 | A defect in the new HTML converter: heading text was written into a buffer that had just been discarded | Fixed before release |
| Survey of 48 real documents (`logs/scripts/convert_survey.py`) | Word files exported by other tools use no heading styles, so they came out with no headings; one long PDF set in three text sizes was read as having no headings | Headings are now read from type size and bold when a Word file has no styled heading; a PDF's running-text sizes are those carrying a tenth of the text. 47 converted; one damaged PDF failed with a clear message |
| Looking at a converted PDF in the app | A wider gap between paragraphs was being read as a line break | The line spacing is now the commonest gap, not the median. T241 covers it |
| T228 | See above: the machine's memory, not the code | The message now says the system was out of memory instead of quoting the runtime's assertion |

What the runs for 0.6.0 found:

| Found by | What was wrong | What was done |
|---|---|---|
| T040 (closing the window ends the process) | A real defect. The launcher asks every running app "are you there?" every three seconds, and each question counted as use, so an app whose window had closed never ended while the launcher was open | Fixed in the gateway: a ping is not use. T042 now covers exactly this |
| T228 (recording, each model under its cap), once in five full runs | A small audio model peaked at 193 MB against a 186 MB cap. The job still finished; the governor samples twice a second and the peak was brief | The two audio models' allowance went from 160 to 180 MB (cap 208). Which of the two peaked was not captured; the test now names the model if it happens again |
| T018, T156, T200, T204, T210 | Mistakes in the new tests themselves (wrong expected text, a tuple compared with a list, an app left running by an earlier case, an unreliable `netstat` check) | Tests corrected; T210 now checks by connecting from the network address |
| T205, once | The router closed a rejected request without reading its body, which the caller saw as a reset | The test sends no body; the request is still refused |

## Areas

| Area | Cases | What it covers |
|---|---|---|
| A. Launcher and command | 20 | Welcome screen first, icons that launch rather than link, nothing started by looking, logo, assets, status and list commands, launcher under 40 MB |
| B. Each app is its own process | 36 | Separate pid and port per app, reuse on a second click, start under two seconds, under 40 MB each, all five at once, stop, window close, reload, launcher polling, crash of one app, restart after a crash, app starting app, `open`, `close`, `apps`, `stop`, idle exit for apps and launcher |
| C. Products kept separate | 23 | The launcher refusing convert, ask, upload and app routes; an app refusing other apps' screens and routes, the builder, the memory log, removal; models only where declared; cost logged under the app's name |
| D. Each app's screen | 21 | Every app's page and its features, file browser, byte ranges, upload-convert-save, creating an app from a prompt, its own process, removal |
| E. Conversion | 34 | One case per format (Markdown, text, PDF, scanned PDF, Word, tables, PowerPoint, Excel, HTML, CSV, TSV, JSON, notebooks, EPUB, RTF, ODT, code, subtitles), long and odd inputs, empty, unsupported, missing and damaged files |
| F. Governor | 14 | Budget refusal, kill over budget, lock release, one model at a time across apps, waiting a turn, release, stop, timeout, per-model cap, optimizer |
| G. TwinMind pipeline | 20 | Gist, grounding guards, parsing, sectioning, merge, speakers; a full memo with no model available; the MeetingNoter layout; skipped stages named; quoted commitments and decisions; meetings list, search, RTF input, empty input |
| H. Memory log | 13 | One log for every process, app start and stop with lifetime, report, saved report, recent files, most-used first, prune, per-app log files |
| I. Moving between systems | 14 | Push, checksum, installers, zip contents and size, check, update, your apps travelling, stale-file removal, tampered zip, prune, pack, install, unsafe zip, installed app running |
| J. Security | 15 | Foreign host and origin on launcher and apps, other sites unable to launch or stop apps, path escapes, ids as paths, launch query, upload names, response headers, listening on this device only |
| K. Resources and package | 11 | Request cost, no model in memory, total under 2 GB, `size` and `models` commands, models inside the package, ready with the library unplugged, CPU-only runtime, nothing left running |
| L. Real models | 9 | Assistant answer, model loaded from the package, conversation thread, meeting notes in the MeetingNoter layout, grounding of dates, two apps taking turns for a model, a two-voice recording, TwinMind's three models in sequence |
| M. Files | 52 | **Structure kept (25):** Word levels, emphasis, links, nested and numbered lists, merged cells, unstyled documents; PDF headings, paragraphs, page breaks, lists, addresses, running headers; PowerPoint titles, levels, tables; HTML tables, lists, quotes; RTF and ODT; EPUB reading order. **Which app opens what (3).** **Drop to open (14):** on the launcher, on the right app, on the wrong app, TwinMind, unknown app, unsafe names, other sites, the log, every page. **Windows (10):** preview writes nothing, one entry per app, types from the manifests, Default apps, the command run, never sets a default, user settings only, Start menu, the handler, paths with spaces |
| N. TwinMind on real speech | 30 | **Speakers and sentences (7):** a sentence goes to whoever was talking, an opening word stays with its sentence, repeats and noise tags removed. **Long recordings (6):** windows of five minutes, speakers matched across a join by the overlap or by elimination and never guessed, cuts made in pauses. **Memory (3):** a model stopped at its own cap is run again up to the ceiling, never over it; allowances are the ones measured on a real call. **Notes (6):** plain titles, placeholders and pasted lines removed, a cut-off action list keeps its finished items, commitments quoted one sentence each. **Who is who (4):** speakers listed, renamed everywhere, refused outside the TwinMind folder. **Real models (3):** a 9-minute two-voice recording end to end |
| O. Taking turns | 31 | **The line for the model (8):** nobody turned away for waiting, a question ahead of a long job, first come first served, what the model is doing, a waiter whose caller has gone, a released waiter, a running model whose caller has gone, a stale ticket. **Saved pieces (7):** speech pieces and speaker windows saved and never redone, pause and resume, step-down from the piece that was refused, fast and accurate, a changed file starts afresh, length read without converting. **The line of recordings (7):** estimate, joining the line, reorder and remove, the next one written by itself, a stopped job listed and discarded, nothing left after a finished job, pause and stop when idle. **Screens and report (2).** **With real models (7):** a question waits and is answered, a cancelled question leaves the line, the notes model steps aside, a job stopped part way resumes without redoing saved windows, a model stopped by hand stops the job, closing the app stops its job |
| P. The meeting library | 9 | An archive of transcripts listed newest first with date, project and people; filters; one meeting with its transcript as recorded and promises quoted; tags and projects saved outside the archive, which is never written to; search inside; a summary shown under its meeting and across its project; names put right; the names reaching the speech model; the page |
| Q. Live meetings | 9 | Who is recording from a microphone; only an app that declares it may ask; a call app noticed and un-noticed; two tracks in pieces of equal length that end cleanly; a line carried across a piece boundary; invented phrases on a silent piece dropped; pieces put together and the owner's voice found; recordings left without a memo; the Live tab |

## When to run

| When | What |
|---|---|
| After any code change | `test --quick` |
| Before `mitra-marketplace push` | full `test` |
| After `update` or `install` on another system | full `test` on that system |
| After changing `catalog.json`, the models or `model_budget_mb` | the nine area-L cases (`--list` shows their numbers) |
| Monthly, with the memory review | full `test`, then the manual cases |

A release is pushed only when the full run has no failures.

## Manual cases (not automated)

The suite drives the processes directly; it does not look at windows.

| Case | Steps | Expected | Done |
|---|---|---|---|
| M01 | `mitra-marketplace` in a new terminal | The welcome screen opens in its own window, with no tabs or address bar | Window started on 2026-11-11; not looked at by me |
| M02 | Click Enter, then each icon | Each app opens in its own window; a green dot and its memory appear on its icon | Checked in a browser pane with windows switched off |
| M03 | Close an app's window | About five seconds later its dot disappears and `mitra-marketplace apps` no longer lists it | Checked in a browser pane |
| M04 | Markdown Reader: open a long `.md` | Rendered text, outline, Source toggle | Done in the 0.5.1 interface review |
| M05 | Mitra PDF: open a PDF | Pages in the viewer; Text view shows extracted text | Done in the 0.5.1 review |
| M06 | Anything to MD: drag a file in | Preview appears; Save writes beside the source | Done in the 0.5.1 review |
| M07 | Ask Mitra: ask a question | An answer with model, seconds and MB; the RAM pill returns to "no model loaded" | Done in the 0.5.1 review |
| M08 | TwinMind: process a real meeting recording | A memo in `Dropbox/Mitra/TwinMind` in the MeetingNoter layout; judge accuracy by reading it | Done on 2026-11-12 with two of your phone calls (4 and 16 minutes, Hindi and English), through the app's page and by reading the memos. Transcript, speakers, gist and quoted commitments: right. Discussion points and action items from the notes model: unreliable (see README, Not done yet). Not done: a room recording, more than two people, over an hour |
| M08b | After a memo is written, name the speakers | The memo is rewritten with names; the meetings list and the reader show them | Done in a browser pane on the 4-minute call: 49 places updated, attendees filled in |
| M09 | In TwinMind, click a meeting | Markdown Reader starts as its own app, on that memo | Not done in a real window |
| M10 | Create: describe an app, create it | Its icon appears; clicking it starts its own process | Automated side covered by area D |
| M11 | System page while Ask Mitra answers | The app is listed under "Apps running now", the model under "Model running now" | Not done |
| M12 | Phone-width window | Icons reflow; nothing scrolls sideways | Welcome screen seen at 431 px; the rest not done |
| M13 | Right-click a PDF in Explorer > Open with | Mitra PDF is listed with the Mitra icon; choosing it opens the file in its own window with no console flash | Not done. Registry entries and the handler were checked; the menu was not looked at |
| M14 | Settings > Apps > Default apps, search "Mitra" | Mitra PDF, Markdown Reader, Anything to MD and TwinMind appear and can be set as default | Not done |
| M15 | Drag a file from Explorer onto the launcher, onto an icon, and onto an open app | A "Drop to open" panel appears; the file opens in the right app | Done with simulated drop events in a browser pane, not with a real drag |
| M16 | Drag a PDF over the page shown inside Mitra PDF | The panel covers the viewer and the drop opens in Mitra PDF, not inside the viewer | Panel seen covering the viewer; real drag not done |
| M17 | Start menu > Mitra | Six entries; each starts its app | Shortcut files checked on disk; not clicked |

## Platforms

| Platform | Build | Automated suite | Notes |
|---|---|---|---|
| Windows 11, x64 | Done | 281 of 282 (see Last result) | Development machine |
| macOS | Not tried | Not run | The recording case skips (needs Windows speech synthesis); `install.sh` and `build.sh` untested |
| Android Termux | Not tried | Not run | Each app is a browser tab; `llama-server` and `whisper-cli` must be built or installed there |
| Linux | Not tried | Not run | |

## Known gaps

- **A call of two hours has not been run to the end.** See "The first long real run" above. Until one has, the times for long calls are estimates and the memo of a long call has not been read.

- Nothing in the suite looks at a real window. That the bare Chrome window appears, looks right and closes its app is M01 to M03.
- Model answer quality is checked by one factual question, one follow-up, and by the memo having the right structure. Whether a summary is accurate is judged by a person (M08).
- What the suite guarantees about action items is the grounding: a shown deadline must be tied to its task in the transcript, and the spoken commitments must be quoted. Whether the model's list is complete is not tested.
- **The automated recordings are synthesized speech, and that is what let 0.7.0 through.** No real call can be shipped as a test fixture (they are your conversations). The real-call check is manual: `python logs/scripts/twinmind_real_run.py "<recording>"` runs a file through the running app and prints every stage, each model's peak memory against its cap, and the memo's shape. Run it on a real recording before every push that touches TwinMind or the audio models.
- Whether a voice keeps its speaker number across a join is proven by the unit cases (T289 to T292) and from the second window on in T309. It was judged by reading on one real 16-minute two-person call. A meeting of four or more people has not been tried.
- Overlapping speech, a noisy room and similar voices are not covered.
- The structured PDF fixture is three hand-built pages in one column. Two-column layouts, tables inside PDFs and scans are not covered; the survey of real documents counts structure but does not judge whether it is right.
- `register` itself is not run by the suite, which must not touch the registry; the suite checks the preview of what it writes. It was run once by hand on 2026-11-12.
- Drops are tested at the server (the file arrives, the right app starts). The browser side is checked by the pages containing the handler, not by dragging.
- The installers `install.ps1` and `install.sh` are not exercised; area I covers the same install logic through `update`.
- The suite has only run on Windows.
