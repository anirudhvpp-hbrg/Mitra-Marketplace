"""0.10.0: record the suite results of 2026-11-20 and the live-meeting check in TEST_PLAN.md and README.md.
Run once from the project root: python logs/scripts/apply_test_plan_0_10.py
"""
from pathlib import Path

LAST = '''## Last result

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
'''

f = Path("TEST_PLAN.md")
s = f.read_text("utf-8")
a0 = s.index("## Last result\n")
a1 = s.index("2026-11-14, Windows 11, Python 3.13, version 0.9.0")
s = s[:a0] + LAST + "\n" + s[a1:]
for a, b in [
    ("all 343 automated cases, about 26 minutes", "all 361 automated cases, about 25 minutes"),
    ("\n## When to run\n",
     "| P. The meeting library | 9 | An archive of transcripts listed newest first with date, project and people; filters; one meeting with its transcript as recorded and promises quoted; tags and projects saved outside the archive, which is never written to; search inside; a summary shown under its meeting and across its project; names put right; the names reaching the speech model; the page |\n"
     "| Q. Live meetings | 9 | Who is recording from a microphone; only an app that declares it may ask; a call app noticed and un-noticed; two tracks in pieces of equal length that end cleanly; a line carried across a piece boundary; invented phrases on a silent piece dropped; pieces put together and the owner's voice found; recordings left without a memo; the Live tab |\n"
     "\n## When to run\n"),
]:
    assert s.count(a) == 1, a[:50]
    s = s.replace(a, b)
s = s.replace("|\n\n| P. The meeting library", "|\n| P. The meeting library")
f.write_text(s, "utf-8")

r = Path("README.md")
t = r.read_text("utf-8")
a = "Last full run: 343 of 343 on 2026-11-14 (version 0.9.0). Nine library cases were added afterwards and pass; the full suite has not been rerun with them."
assert t.count(a) == 1
t = t.replace(a, "Last full run: 357 of 361 on 2026-11-20 (version 0.10.0). Three of the four failures were faults in new tests, since fixed and passing; the fourth is real and open: the speech model once peaked at 1,066 MB, over the 1,024 MB ceiling, and did not do so again when rerun.")
a = "| TwinMind: meeting library (old and new meetings, tags, projects, search inside, across-meetings view, people list) | Built 2026-11-14. Its own tests pass and the page was checked against a real archive of 2,597 transcripts. The full suite has not been rerun since |"
assert t.count(a) == 1
t = t.replace(a, "| TwinMind: meeting library (old and new meetings, tags, projects, search inside, across-meetings view, people list) | Built 2026-11-14. Tested, and the page was checked against a real archive of 2,597 transcripts |")
a = "| Memory governor: one model at a time, a waiting line, per-model caps | Works. Tested, and held on a real 2 h 25 min recording (peak 975 MB under a 1,024 MB ceiling) |"
assert t.count(a) == 1
t = t.replace(a, "| Memory governor: one model at a time, a waiting line, per-model caps | Works. Tested, and held on a real 2 h 25 min recording (peak 975 MB under a 1,024 MB ceiling). One open case: a model is stopped only above the ceiling plus ten percent, and the speech model was once seen at 1,066 MB |")
r.write_text(t, "utf-8")
print("ok")
