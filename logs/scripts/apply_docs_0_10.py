"""0.10.0 documentation: live meetings in README and docs/ARCHITECTURE.md, and the pieces of a live
recording are removed once they have been put together (they were being kept twice).
TEST_PLAN.md is updated by apply_test_plan_0_10.py when the suite's result is known.
Run once from the project root: python logs/scripts/apply_docs_0_10.py
"""
from pathlib import Path


def patch(path, edits):
    f = Path(path)
    s = f.read_text("utf-8")
    for a, b in edits:
        assert s.count(a) == 1, (path, s.count(a), a[:70])
        s = s.replace(a, b)
    f.write_text(s, "utf-8")


patch("workers/mitra_workers/live.py", [(
    '    (d / "assembled").write_text(str(base), "utf-8")\n',
    '    (d / "assembled").write_text(str(base), "utf-8")\n'
    '    for f in d.glob("*-[0-9][0-9][0-9][0-9].wav"):      # the pieces are now in the three files above\n'
    '        f.unlink(missing_ok=True)\n')])

LIVE = '''### A meeting as it happens (0.10.0)

| Step | How |
|---|---|
| **Noticing a meeting** | While TwinMind's window is open it asks its own process every five seconds which programs are recording from a microphone. The answer comes from Windows' audio sessions, read by `mitra-ear who`; nothing is listened to. If one of them is a call app (Teams, Zoom, Webex, Slack, WhatsApp, a browser and so on) a banner asks "Do you want me to record it?", with "Not this one". Someone talking near the laptop is not a meeting, and neither is a dictation tool. Nothing watches when Mitra is closed |
| **Recording** | `mitra-ear` (Rust, about 12 MB, no model) records two tracks at 16 kHz: your microphone, and whatever the computer plays, which in a call is everyone else. Nothing joins the call. Each track is written in half-minute pieces under a temporary name and renamed when complete, so a crash loses at most the half minute in hand, and both tracks follow the wall clock so piece N covers the same half minute on each |
| **The transcript as it grows** | Each finished piece goes through the smallest multilingual speech model (Whisper base, about 2 s per piece, 356 MB while it runs, nothing between pieces). A silent piece runs no model. A line that runs into the end of a piece is held back and heard whole with the next one. Lines are marked with your name or "Others" by track |
| **Your notes** | A box beside the transcript; what you type is saved as you go and put in the memo as written |
| **When you stop** | The pieces are put together into one recording per track and a mix, and the full pipeline writes the memo: speakers, the accurate speech model, notes, the check. The speaker heard on the microphone track is named as you. Recordings are kept 30 days (`keep_recordings_days`), then go to the Recycle Bin |
| **If the app is closed mid-meeting** | The recorder ends cleanly and the Live tab offers "Write its memo" next time |

Memory is flat for any length: one piece is handled at a time and everything so far is on disk. Checked on 2026-11-20 with a two-minute recording of synthesized speech played through the speakers: both tracks recorded, every sentence in the live transcript after two faults were fixed (an invented "Thank you" from the silent microphone track, and a sentence lost at a piece boundary), and a correct memo with the typed note in it. **Not yet run on a real meeting, on a real voice at the microphone, or for hours**; the live speech model is a provisional choice that gets names wrong (the memo's model does not).

'''

patch("README.md", [
    ("| **TwinMind: notice a meeting and offer to record it** | **Not built** |\n| **TwinMind: live transcript during a meeting** | **Not built** |\n",
     "| TwinMind: notice a meeting and offer to record it | Built 2026-11-20, Windows only, and only while TwinMind is open. Tested with a stand-in call app; not yet seen with a real Teams or Zoom call |\n"
     "| TwinMind: record a meeting and show the transcript as it runs | Built 2026-11-20. Checked end to end with two minutes of synthesized speech; **not yet run on a real meeting or for hours**. The live model is provisional and misspells names |\n"),
    ("Version 0.9.0, with 0.10.0 in progress.", "Version 0.10.0."),
    ("### The meeting library\n", LIVE + "### The meeting library\n"),
    ("| Memory governor, the windowless file handler | Rust | Must be tiny, exact about memory, and present only while a model runs | `governor/` |",
     "| Memory governor, the windowless file handler | Rust | Must be tiny, exact about memory, and present only while a model runs | `governor/` |\n"
     "| The recorder (microphone and system audio, two tracks) | Rust | Must run for hours in about 12 MB and never lose what it has heard | `ear/` |"),
    ("This builds `bin/mitra-marketplace`, `bin/mitra-governor` and `bin/mitra-open`.", "This builds `bin/mitra-marketplace`, `bin/mitra-governor`, `bin/mitra-open` and `bin/mitra-ear`."),
    ("governor/            Rust: the memory governor and the windowless file handler\n",
     "governor/            Rust: the memory governor and the windowless file handler\near/                 Rust: the recorder (two tracks in saved pieces) and \"who is using the microphone\"\n"),
    ("1. **Live meetings.** While Mitra is open, notice that a meeting app is using the microphone and ask whether to record; capture microphone and system audio in saved pieces; show the transcript as the meeting runs; write the memo when it ends. Sized for meetings of two to three hours.\n",
     "1. **Live meetings, proven.** Built in 0.10.0. Still to do: a real meeting of two to three hours recorded and read; a survey of every candidate for the live speech model on at least a hundred held-out cases, so names come out right in the running transcript too; a notification when TwinMind's window is not in front.\n"),
    ("| `meeting_archive` | none | A folder of old transcripts for TwinMind's library, read only |",
     "| `meeting_archive` | none | A folder of old transcripts for TwinMind's library, read only |\n| `keep_recordings_days` | 30 | How long live recordings are kept before they go to the Recycle Bin |"),
    ("| P | The meeting library: an archive listed and filtered, tags kept outside it, search inside, names put right |",
     "| P | The meeting library: an archive listed and filtered, tags kept outside it, search inside, names put right |\n"
     "| Q | Live meetings: who is using the microphone, a call app noticed and un-noticed, two tracks in equal pieces, a line carried across a piece boundary, invented phrases dropped, tracks put together, the Live tab |"),
])

patch("docs/ARCHITECTURE.md", [
    ("**Other features**\n", LIVE.replace("### A meeting as it happens (0.10.0)", "**A meeting as it happens (0.10.0)**") + "**Other features**\n"),
    ("`bin/mitra-open.exe` is a second small Rust program",
     "`bin/mitra-ear.exe` (`ear/`, Rust, about 12 MB) records the microphone and the system's audio as two tracks in half-minute pieces, and reports which programs are recording from a microphone. `bin/mitra-open.exe` is another small Rust program"),
])
print("ok")
