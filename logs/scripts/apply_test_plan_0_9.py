"""0.9.0: record the suite result and the real long-call run in TEST_PLAN.md, and the new counts in
README.md, docs/ARCHITECTURE.md and docs/architecture.html. Run once from the project root.
"""
import re
from pathlib import Path

log = (Path.home() / ".mitra" / "tmp" / "suite-run.log").read_text("utf-8", errors="replace")
m = re.search(r"(\d+) passed, (\d+) failed, (\d+) skipped of (\d+) in (\d+) s\s+Report: .*?([\d-]+\.md)", log)
passed, failed, skipped, total, secs, report = m.groups()
assert failed == "0", "do not record a failing run as the last result"


def patch(path, edits):
    f = Path(path)
    s = f.read_text("utf-8")
    for a, b in edits:
        assert s.count(a) == 1, (path, s.count(a), a[:70])
        s = s.replace(a, b)
    f.write_text(s, "utf-8")


LAST = f'''## Last result

2026-11-14, Windows 11, Python 3.13, version 0.9.0: **{passed} of {total} passed**, none skipped, in {secs} seconds. Report: `logs/tests/results/{report}`. This run is on the final code.

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
'''

AREA_O = ("| O. Taking turns | 31 | **The line for the model (8):** nobody turned away for waiting, a question ahead of a long job, first come first served, "
          "what the model is doing, a waiter whose caller has gone, a released waiter, a running model whose caller has gone, a stale ticket. "
          "**Saved pieces (7):** speech pieces and speaker windows saved and never redone, pause and resume, step-down from the piece that was refused, "
          "fast and accurate, a changed file starts afresh, length read without converting. **The line of recordings (7):** estimate, joining the line, "
          "reorder and remove, the next one written by itself, a stopped job listed and discarded, nothing left after a finished job, pause and stop when idle. "
          "**Screens and report (2).** **With real models (7):** a question waits and is answered, a cancelled question leaves the line, the notes model steps aside, "
          "a job stopped part way resumes without redoing saved windows, a model stopped by hand stops the job, closing the app stops its job |\n")

f = Path("TEST_PLAN.md")
s = f.read_text("utf-8")
a0, a1 = s.index("## Last result\n"), s.index("2026-11-13, Windows 11, Python 3.13, version 0.8.0")
s = s[:a0] + LAST + "\n" + s[a1:]
for a, b in [
    ("mitra-marketplace test             all 312 automated cases, about twelve minutes (eight of them are one long recording)",
     f"mitra-marketplace test             all {total} automated cases, about 26 minutes (most of it two long recordings and the real-model cases)"),
    ("mitra-marketplace test --quick     skips the 12 that load real models; two and a half minutes",
     "mitra-marketplace test --quick     skips the cases that load real models; about four minutes"),
    ("\n## When to run\n", "\n" + AREA_O.rstrip("\n") + "\n\n## When to run\n"),
    ("## Known gaps\n", "## Known gaps\n\n- **A call of two hours has not been run to the end.** See \"The first long real run\" above. Until one has, the times for long calls are estimates and the memo of a long call has not been read.\n"),
]:
    assert s.count(a) == 1, (s.count(a), a[:60])
    s = s.replace(a, b)
# the area table must stay one block: move the O row up against the N row
s = s.replace("\n\n" + AREA_O.rstrip("\n") + "\n\n## When to run", "\n" + AREA_O.rstrip("\n") + "\n\n## When to run")
f.write_text(s, "utf-8")

patch("docs/ARCHITECTURE.md", [(
    "`mitra-marketplace test` runs 312 cases in about twelve minutes; `--quick` skips the 12 that load real models. The suite uses its own port and temporary home, so your log, apps and Dropbox are untouched. Last full run: 312 of 312 on 2026-11-13.",
    f"`mitra-marketplace test` runs {total} cases in about 26 minutes; `--quick` skips the ones that load real models. The suite uses its own port and temporary home, so your log, apps and Dropbox are untouched. Last full run: {passed} of {total} on 2026-11-14. A real call of over two hours was started on 2026-11-14 and stopped by hand at 34 minutes; it has not been run to the end (see `TEST_PLAN.md`).")])
patch("docs/architecture.html", [('<b data-count="312" data-suffix="">312</b>', f'<b data-count="{total}" data-suffix="">{total}</b>')])
patch("README.md", [(
    "- Transcription and diarization have been run on two real phone calls of yours (4 and 16 minutes, two people, Hindi and English) and on synthesized speech. Not tried: a room recording, more than two people, a call over an hour, another language pair.",
    "- Transcription and diarization have been run on two real phone calls of yours (4 and 16 minutes, two people, Hindi and English) and on synthesized speech. Not tried: a room recording, more than two people, another language pair.\n"
    "- **A call of over an hour has not been run to the end.** A 2 hour 25 minute call was started on 2026-11-14 (estimate: 117 minutes) and was stopped by hand 34 minutes in, with 29 of 34 speaker windows saved; pause, resume, the line and a question in Ask Mitra worked on it up to there. The speech and notes stages of a long call, and its memo, have not been seen. TwinMind shows that job as unfinished with Resume.")])
print("ok", passed, total, report)
