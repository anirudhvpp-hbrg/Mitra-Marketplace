"""0.9.0 documentation: README, docs/ARCHITECTURE.md and docs/wireframes.html say what was built
(the line for the model, saved pieces and resume, the line of recordings, speed choice) and what
was and was not run on a real long call. TEST_PLAN.md is updated by apply_test_plan_0_9.py once
the full suite's result is known. Run once from the project root.
"""
from pathlib import Path


def patch(path, edits):
    f = Path(path)
    s = f.read_text("utf-8")
    for a, b in edits:
        assert s.count(a) == 1, (path, s.count(a), a[:70])
        s = s.replace(a, b)
    f.write_text(s, "utf-8")


TURNS = '''### Long calls and several apps at once (0.9.0)

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

'''

patch("README.md", [
    ("so if TwinMind is summarising, Ask Mitra waits its turn (up to two minutes) instead of loading a second model.",
     "so if TwinMind is summarising, Ask Mitra waits in a line for its turn instead of loading a second model. A question goes ahead of a long job at its next piece; nothing in the line times out."),
    ("`\"transcribe_language\"` in the config: `\"english\"` (default)", TURNS + "`\"transcribe_language\"` in the config: `\"english\"` (default)"),
])

patch("docs/ARCHITECTURE.md", [
    ("Version 0.8.0, written 2026-11-13.", "Version 0.9.0, written 2026-11-13, updated 2026-11-14 (section 5.4, \"Long calls and several apps at once\")."),
    ("- **One at a time.** A lock shared by every app. If TwinMind is using a model, Ask Mitra waits its turn (up to two minutes).",
     "- **One at a time, in a line.** A lock shared by every app, and a ticket for each one waiting (`~/.mitra/run/line`). The model goes to the head of the line: a question (`--priority interactive`) ahead of long jobs, then first come first served. Nothing in the line times out unless the caller sets a limit. `mitra-governor status` lists the line and what the running model is doing.\n"
     "- **Callers that go away.** A waiter whose caller has gone (a cancelled question) leaves the line; a running model whose caller has gone is stopped. A model stopped by hand ends with its own code (143), which the job treats as a stop, not a failure."),
    ("**Other features**\n", TURNS.replace("### Long calls and several apps at once (0.9.0)", "**Long calls and several apps at once (0.9.0)**") + "**Other features**\n"),
    ("| `governor.denied`, `governor.evict`, `model.cap_raised`, `model.fallback` | A refusal, a stop, a retry at the ceiling, a switch to a smaller model |",
     "| `governor.denied`, `governor.evict`, `model.cap_raised`, `model.fallback` | A refusal, a stop, a retry at the ceiling, a switch to a smaller model |\n"
     "| `model.wait`, `model.wait_left`, `model.yield` | Someone waited in line for the model, left the line, or a long job stepped aside for a question |\n"
     "| `job.queued`, `job.paused`, `job.stopped`, `job.resumed` | A recording joined the line; a job was paused, stopped, or picked up from its saved pieces |"),
    ("  logs/tests/          run_tests.py and results/", "  logs/tests/          run_tests.py and results/\n  docs/wireframes.html every screen and state, with notes"),
    ("~/.mitra/              config.json · apps/ (yours) · memory/ · logs/ · handlers/ · tmp/",
     "~/.mitra/              config.json · apps/ (yours) · memory/ · logs/ · handlers/ · tmp/\n"
     "~/.mitra/run/          model.lock · line/ (tickets) · work/<job>/ (saved pieces) · jobs/ · twinmind-line.json (recordings waiting)"),
])

patch("docs/wireframes.html", [
    ("final design · 0.8.0 as built, plus the agreed plan (queue, resume, yield, speed choice)",
     "final design · built in 0.9.0 (2026-11-14): queue, resume, stepping aside, speed choice"),
    ("<span><i class=\"n\"></i>New in the agreed plan</span>", "<span><i class=\"n\"></i>New in 0.9.0 (the agreed plan), now built</span>"),
    ("Nothing new is built yet.</p>", "All of it is built in 0.9.0. One difference from the drawing: there is no \"Same person as\" menu; giving two voices the same name merges them.</p>"),
])
print("ok")
