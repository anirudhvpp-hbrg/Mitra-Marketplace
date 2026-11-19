# ============================================================================================
# N. TwinMind on real speech (added in 0.8.0 after a real 4-minute call failed: the audio models
#    were stopped by caps sized on 40-second clips, and the tiny English model could not follow
#    a call that moves between Hindi and English). Placed at the end so earlier numbers hold.
# ============================================================================================
def _words(spec):
    """'0.0-0.4 Hello,|0.5-0.9 hi' -> timed words"""
    out = []
    for part in spec.split("|"):
        span, text = part.strip().split(" ", 1)
        a, z = span.split("-")
        out.append({"start": float(a), "end": float(z), "text": text})
    return out


def _lines(words, turns=None):
    return py(f"import json; from mitra_workers import models; print(json.dumps(models.words_to_lines({words!r}, {turns!r})))")


A, B = "Speaker 1", "Speaker 2"


@case("N", "each sentence goes to the speaker who was talking for most of it")
def _():
    words = _words("0.0-0.3 Hello,|0.4-0.6 hi|0.7-1.1 Dilip.|2.0-2.3 Hi,|2.4-2.8 good|2.9-3.4 evening.|4.0-4.3 Yeah,|4.4-4.7 tell|4.8-5.0 me.")
    turns = [{"start": 0.0, "end": 1.3, "speaker": A}, {"start": 1.9, "end": 3.9, "speaker": B}, {"start": 4.2, "end": 5.2, "speaker": A}]
    d = _lines(words, turns)
    t.assertEqual([(x["speaker"], x["text"]) for x in d], [(A, "Hello, hi Dilip."), (B, "Hi, good evening."), (A, "Yeah, tell me.")])


@case("N", "a short opening word stays with its own sentence, not the previous speaker's line")
def _():
    # "No," is timed inside the other person's turn (word timings are approximate); the sentence decides
    words = _words("0.0-0.5 Is|0.6-0.9 it|1.0-1.5 ready?|1.6-1.8 No,|2.2-2.5 I|2.6-2.9 have|3.0-3.2 to|3.3-3.8 change|3.9-4.2 it.")
    turns = [{"start": 0.0, "end": 2.0, "speaker": A}, {"start": 2.1, "end": 4.4, "speaker": B}]
    d = _lines(words, turns)
    t.assertEqual([(x["speaker"], x["text"]) for x in d], [(A, "Is it ready?"), (B, "No, I have to change it.")])


@case("N", "one speaker's consecutive sentences are one line; a change of speaker starts a new one")
def _():
    words = _words("0.0-0.5 One.|0.6-1.0 Two.|1.1-1.5 Three.|2.0-2.5 Four.")
    turns = [{"start": 0.0, "end": 1.6, "speaker": A}, {"start": 1.9, "end": 2.6, "speaker": B}]
    t.assertEqual([x["text"] for x in _lines(words, turns)], ["One. Two. Three.", "Four."])


@case("N", "a word the model repeats over and over is cut to two")
def _():
    words = _words("|".join(f"{i * 0.3:.1f}-{i * 0.3 + 0.2:.1f} then," for i in range(40)) + "|12.5-13.0 so|13.1-13.5 actually.")
    d = _lines(words)
    t.assertEqual(" ".join(x["text"] for x in d).count("then"), 2)
    t.assertIn("so actually.", d[-1]["text"])


@case("N", "the same line three times running is kept twice at most")
def _():
    words = _words("|".join(f"{i * 6}.0-{i * 6}.5 Thank|{i * 6}.6-{i * 6 + 1}.0 you." for i in range(5)))
    turns = [{"start": i * 6.0, "end": i * 6.0 + 1.2, "speaker": (A, B)[i % 2]} for i in range(5)]
    t.assertLessEqual(len(_lines(words, turns)), 2)


@case("N", "without speaker turns the transcript is plain sentences with no speaker")
def _():
    d = _lines(_words("0.0-0.5 The|0.6-1.0 release|1.1-1.5 stays.|5.0-5.5 Disk|5.6-6.0 is|6.1-6.5 full."))
    t.assertEqual([x["text"] for x in d], ["The release stays.", "Disk is full."])
    t.assertTrue(all("speaker" not in x for x in d))


@case("N", "noise tags and bracketed asides never reach the transcript")
def _():
    code = ("import json; from mitra_workers import models; "
            "print(json.dumps([models._NOISE.sub(' ', s).strip() for s in ['[BLANK_AUDIO]', '(speaking in foreign language)', '[laughs]', '[inaudible]', 'Fine (I think) then']]))")
    t.assertEqual(py(code), ["", "", "", "", "Fine (I think) then"])


def _link(before, local, o0, o1):
    return py(f"import json; from mitra_workers import models; print(json.dumps(models.link_windows({before!r}, {local!r}, {o0}, {o1})))")


def _t(a, z, s):
    return {"start": a, "end": z, "speaker": s}


@case("N", "a long recording's windows: speakers numbered differently in the next window are matched by the overlap")
def _():
    before = [_t(0, 100, A), _t(100, 200, B), _t(255, 275, B), _t(275, 300, A)]
    local = [_t(255, 275, A), _t(275, 300, B), _t(300, 400, A), _t(400, 500, B)]     # the same two voices, numbers swapped
    d = _link(before, local, 255, 300)
    who = {(x["start"], x["end"]): x["speaker"] for x in d}
    t.assertEqual(who[(300, 400)], B)
    t.assertEqual(who[(400, 500)], A)
    t.assertEqual({x["speaker"] for x in d}, {A, B})


@case("N", "a voice silent in the overlap is matched by elimination when only one is left")
def _():
    before = [_t(0, 120, A), _t(120, 250, B), _t(255, 300, A)]
    local = [_t(255, 300, B), _t(300, 380, B), _t(380, 450, A)]      # local B = earlier A; local A did not speak in the overlap
    d = _link(before, local, 255, 300)
    t.assertEqual({x["speaker"] for x in d}, {A, B})
    t.assertEqual(next(x["speaker"] for x in d if x["start"] == 380), B)


@case("N", "two voices that cannot be told apart at a join get new numbers, never someone else's name")
def _():
    before = [_t(0, 100, A), _t(100, 180, B), _t(180, 250, "Speaker 3"), _t(255, 300, A)]
    local = [_t(255, 300, "Speaker 1"), _t(300, 350, "Speaker 2"), _t(350, 400, "Speaker 3")]
    d = _link(before, local, 255, 300)
    later = {x["speaker"] for x in d if x["start"] >= 300}
    t.assertEqual(later, {"Speaker 4", "Speaker 5"}, "guessing between two unmatched voices would mislabel one of them")


@case("N", "joined windows cover each moment once, cut in the middle of the overlap")
def _():
    before = [_t(0, 200, A), _t(200, 300, B)]
    local = [_t(255, 330, A), _t(330, 500, B)]
    d = _link(before, local, 255, 300)
    spans = sorted((x["start"], x["end"]) for x in d)
    for (a1, z1), (a2, z2) in zip(spans, spans[1:]):
        t.assertLessEqual(z1, a2 + 1e-6, "two turns overlap after the join")
    t.assertIn(277.5, [z for _, z in spans])


@case("N", "a recording of any length is heard in windows of five minutes that overlap")
def _():
    d = py("import json; from mitra_workers import models; print(json.dumps({str(n): models.diar_windows(n) for n in (42, 359, 361, 950, 3600)}))")
    t.assertEqual(d["42"], [[0.0, 42]])
    t.assertEqual(len(d["359"]), 1, "a recording just over five minutes is one window, not a window and a stub")
    for total in ("361", "950", "3600"):
        w = d[total]
        t.assertEqual(w[0][0], 0.0)
        t.assertEqual(w[-1][1], float(total))
        t.assertTrue(all(z - a <= 300.0 for a, z in w), "a window longer than five minutes would need more memory")
        t.assertTrue(all(w[i][1] - w[i + 1][0] >= 44.9 for i in range(len(w) - 1)), "windows must overlap so speakers can be matched")
    t.assertEqual(len(d["3600"]), 14)


@case("N", "a long recording is cut for transcription in a pause, not in the middle of a word")
def _():
    code = (
        "import json, wave, math, struct; from pathlib import Path; from mitra_workers import models, paths\n"
        "p = paths.HOME / 'tmp' / 'quiet.wav'; p.parent.mkdir(parents=True, exist_ok=True)\n"
        "rate = 16000\n"
        "def tone(sec): return b''.join(struct.pack('<h', int(9000 * math.sin(i * 0.2))) for i in range(int(sec * rate)))\n"
        "with wave.open(str(p), 'wb') as w:\n"
        "    w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)\n"
        "    w.writeframes(tone(8.6) + b'\\x00\\x00' * int(0.8 * rate) + tone(6))\n"
        "with wave.open(str(p), 'rb') as src:\n"
        "    at = models._quiet_point(src, 10.0)\n"
        "    models._write_piece(src, 0.0, at, p.with_name('piece.wav'))\n"
        "print(json.dumps([at, models.wav_seconds(p.with_name('piece.wav'))]))")
    at, piece = py(code)
    t.assertTrue(8.6 <= at <= 9.4, f"cut at {at} s; the silence is from 8.6 to 9.4")
    t.assertAlmostEqual(piece, at, delta=0.01)


@case("N", "language: English by default whatever is spoken, original language or a set language on request")
def _():
    code = ("import json; from mitra_workers import models, paths\n"
            "multi, en = {'file': 'x/ggml-small-q5_1.bin'}, {'file': 'x/ggml-tiny.en-q5_1.bin'}\n"
            "out = [models.transcribe_plan(multi)[0], models.transcribe_plan(en)[0]]\n"
            "real = paths.config\n"
            "for want in ('original', 'hi'):\n"
            "    paths.config = lambda want=want: {**real(), 'transcribe_language': want}\n"
            "    out.append(models.transcribe_plan(multi)[0])\n"
            "print(json.dumps(out))")
    t.assertEqual(py(code), [["-l", "auto", "-tr"], [], ["-l", "auto"], ["-l", "hi"]])


def _run_capped(est, burn_mb, home):
    code = ("import json; from mitra_workers import models\n"
            f"p = {{'model': 'cap-test', 'est_mb': {est}}}\n"
            "try:\n"
            f"    models._run_model('twinmind', p, {burner(burn_mb, 3)!r}); print(json.dumps('ran'))\n"
            "except models.MemoryDenied as e:\n    print(json.dumps('denied: ' + str(e)))")
    return py(code, home=home)


@case("N", "a model stopped at its own cap is run once more up to the ceiling, and that is logged")
def _():
    before = len([e for e in events() if e["type"] == "model.cap_raised"])
    t.assertEqual(_run_capped(40, 150, HOME), "ran", "150 MB is over this model's own 54 MB cap but far under the ceiling")
    raised = [e for e in events() if e["type"] == "model.cap_raised"][before:]
    t.assertEqual(len(raised), 1)
    t.assertEqual(raised[0]["data"]["own_cap_mb"], 54)
    runs = [e["data"] for e in events() if e["type"] == "model.run" and e["data"]["name"] == "cap-test"][-2:]
    t.assertEqual([r["end"] for r in runs][0], "over budget")
    t.assertEqual(runs[1]["exit"], 0)


@case("N", "the ceiling itself is never exceeded: over it, the model is stopped and the reason given")
def _():
    out = _run_capped(40, 220, S["nm_home"])      # that home's ceiling is 100 MB
    t.assertTrue(out.startswith("denied"), out)
    t.assertIn("budget", out)
    t.assertEqual(json.loads(gov("status", home=S["nm_home"])[1])["leases"], [])


@case("N", "the speech and speaker models' allowances are the ones measured on a real call")
def _():
    cat = json.loads((ROOT / "catalog.json").read_text("utf-8"))
    tr = {c["id"]: c for c in cat["transcription"]["candidates"]}
    t.assertEqual(cat["transcription"]["candidates"][0]["id"], "whisper-small-q5_1-cpp", "the model that follows mixed Hindi and English comes first")
    t.assertGreaterEqual(tr["whisper-small-q5_1-cpp"]["est_mb"], 620)
    t.assertGreaterEqual(tr["whisper-tiny-en-cpp"]["est_mb"], 290, "a real 4-minute call needed 283 MB; 180 stopped it")
    t.assertGreaterEqual(cat["diarization"]["candidates"][0]["est_mb"], 190)
    for c in list(tr.values()) + cat["diarization"]["candidates"]:
        t.assertLessEqual(int(c["est_mb"] * 1.1) + 10, 800 if c["id"] != "whisper-tiny-en-cpp" else 800)
        t.assertIn("Measured", c["why"].replace("measured", "Measured"), c["id"])


@case("N", "a title or topic is plain words: no asterisks, quotes or repeated 'Title:'")
def _():
    raw = ['**"Meeting on Wednesday, 18th"**', 'AI Stack and Use Case Transcript Title: "AI Stack and Use Case', "Title: Budget review", "Meeting on Proposal for COE Design", "", "Export fix\nsecond line"]
    d = py(f"import json; from mitra_workers import meeting; print(json.dumps([meeting.tidy(x) for x in {raw!r}]))")
    t.assertEqual(d, ["Wednesday, 18th", "AI Stack and Use Case", "Budget review", "Proposal for COE Design", "", "Export fix"])


SPOKEN = ("[00:00:05] Speaker 2: So, the problem will come. I have to recreate the design. I would require it until at least Wednesday, if it's okay.\n"
          "[00:00:20] Speaker 1: Correct.\n[00:00:22] Speaker 2: You tell the client, we will be sharing it by Wednesday.\n[00:00:30] Speaker 1: Thank you.")


@case("N", "a note that says nothing, copies a line, or echoes the format is removed")
def _():
    bullets = ["Correct.", "Thank you.", "I have to recreate the design.", "... (write - None if there are none)",
               "The design will be recreated and shared with the client by Wednesday."]
    d = py(f"import json; from mitra_workers import grounding; print(json.dumps(grounding.guard_bullets({bullets!r}, {SPOKEN!r})))")
    t.assertEqual(d[0], ["The design will be recreated and shared with the client by Wednesday."])
    t.assertEqual(len(d[1]), 3, "the placeholder is dropped silently; the other three are reported")


@case("N", "a note that begins with a transcript label loses the label")
def _():
    d = py(r"import json; from mitra_workers import meeting; print(json.dumps(meeting.parse_notes('Topic: **Design**\nPoints:\n- Speaker 2: The design is recreated by Wednesday.\n- [00:01:02] Speaker 1: The client is told.\nDecisions:\n- None')))")
    t.assertEqual(d["points"], ["The design is recreated by Wednesday.", "The client is told."])


@case("N", "an action item that is only 'Correct', or a pasted transcript line, is removed")
def _():
    acts = [{"owner": "Speaker 1", "task": "Speaker 1: Correct.", "due": None}, {"owner": "Speaker 1", "task": "Thank you", "due": None},
            {"owner": "Speaker 2", "task": "Speaker 2: You tell the client, we will be sharing it by Wednesday.", "due": None},
            {"owner": "Speaker 2", "task": "recreate the design", "due": "Wednesday"}]
    d = py(f"import json; from mitra_workers import grounding; print(json.dumps(grounding.guard_actions({acts!r}, {SPOKEN!r})))")
    t.assertEqual([(a["owner"], a["task"], a["due"]) for a in d[0]], [("Speaker 2", "recreate the design", "Wednesday")])
    t.assertEqual(len(d[1]), 3)


@case("N", "an action list cut off by the length cap keeps the items that were finished")
def _():
    cut = '{"actions": [{"owner": "Sam", "task": "fix the export", "due": "Thursday"}, {"owner": "Dana", "task": "clear the sn'
    d = py(f"import json; from mitra_workers import meeting; print(json.dumps(meeting.parse_actions({cut!r})))")
    t.assertEqual(d, [[{"owner": "Sam", "task": "fix the export", "due": "Thursday"}], True])


def _nm_base():
    return re.search(r"http://[\d.:]+", cli("open", "twinmind", home=S["nm_home"])[1]).group(0)


@case("N", "commitments are quoted one sentence each; 'the problem will come' is not a commitment")
def _():
    src = DOCS / "spoken-call.txt"
    src.write_text(SPOKEN + "\n[00:00:40] Speaker 1: Sam will send the notes tomorrow. Wednesday will be fine.\n", "utf-8")
    base = _nm_base()
    job = _job(base, {"path": str(src), "title": "Spoken call"})
    t.assertEqual(job["status"], "done", job)
    S["call_memo"] = job["result"]["path"]
    heard = Path(S["call_memo"]).read_text("utf-8").split("### Commitments heard")[1].split("## ")[0]
    lines = [l[2:] for l in heard.splitlines() if l.startswith("- ")]
    t.assertIn("[00:00:05] Speaker 2: I have to recreate the design.", lines)
    t.assertIn("[00:00:05] Speaker 2: I would require it until at least Wednesday, if it's okay.", lines)
    t.assertIn("[00:00:22] Speaker 2: You tell the client, we will be sharing it by Wednesday.", lines)
    t.assertIn("[00:00:40] Speaker 1: Sam will send the notes tomorrow.", lines)
    t.assertFalse(any("problem will come" in l or "Wednesday will be fine" in l for l in lines), lines)


@case("N", "who is who: the memo's speakers are listed with a line to recognise each by")
def _():
    s, d, _ = http("GET", "/api/apps/twinmind/speakers?path=" + q(S["call_memo"]), base=_nm_base())
    t.assertEqual(s, 200, d)
    t.assertEqual([(x["speaker"], x["lines"]) for x in d], [("Speaker 2", 2), ("Speaker 1", 3)])
    t.assertIn("recreate the design", d[0]["sample"])


@case("N", "naming a speaker rewrites the memo everywhere, and fills in who attended")
def _():
    base = _nm_base()
    s, d, _ = http("POST", "/api/apps/twinmind/speakers", {"path": S["call_memo"], "names": {"Speaker 1": "Anirudh", "Speaker 2": "Dilip", "Speaker 9": "Nobody"}}, base=base)
    t.assertEqual(s, 200, d)
    memo = Path(S["call_memo"]).read_text("utf-8")
    t.assertNotRegex(memo, r"Speaker [12]\b")
    t.assertIn("[00:00:22] Dilip: You tell the client", memo)
    t.assertIn("- [00:00:05] Dilip: I have to recreate the design.", memo)
    t.assertIn("**Attendees:** Anirudh, Dilip", memo)
    t.assertNotIn("Nobody", memo)
    t.assertEqual(http("GET", "/api/apps/twinmind/speakers?path=" + q(S["call_memo"]), base=base)[1][0]["speaker"], "Dilip")
    t.assertTrue(any(e["type"] == "action.speakers_named" for e in events(S["nm_home"])))


@case("N", "naming speakers is refused for a file that is not a memo in the TwinMind folder")
def _():
    base = _nm_base()
    outside = DOCS / "standup.txt"
    before = outside.read_text("utf-8")
    for path in (str(outside), str(Path(S["call_memo"]).parent / ".." / ".." / "docs" / "standup.txt"), str(ROOT / "README.md")):
        s, d, _ = http("POST", "/api/apps/twinmind/speakers", {"path": path, "names": {"Priya": "X"}}, base=base)
        t.assertGreaterEqual(s, 400, d)
    t.assertEqual(outside.read_text("utf-8"), before)
    t.assertGreaterEqual(http("GET", "/api/apps/twinmind/speakers?path=" + q(ROOT / "README.md"), base=base)[0], 400)


@case("N", "the TwinMind page asks who is who once a memo is written")
def _():
    page = (ROOT / "apps" / "twinmind" / "ui" / "index.html").read_text("utf-8")
    for part in ("askNames(job.result.path)", "api('speakers'", "Who is who?", "Use these names"):
        t.assertIn(part, page)


def _two_voice_wav(wav, rounds):
    """Two installed voices taking turns for `rounds` exchanges; returns how many voices there were."""
    a = "Round {n}. Please fix the export before the release. The export fails on large invoices and the client is waiting."
    b = "Understood, round {n}. The staging database is nearly full, so I will clear old snapshots this afternoon and report back."
    ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          "$v = @($s.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object { $_.VoiceInfo.Name }); "
          f"$s.SetOutputToWaveFile('{wav}'); "
          f"for ($n = 1; $n -le {rounds}; $n++) {{ $s.SelectVoice($v[0]); $s.Speak('{a}'.Replace('{{n}}', $n)); "
          f"if ($v.Count -gt 1) {{ $s.SelectVoice($v[1]) }}; $s.Speak('{b}'.Replace('{{n}}', $n)) }}; "
          "$s.Dispose(); Write-Output $v.Count")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, capture_output=True, text=True, creationflags=NOWIN).stdout
    return int(out.strip().splitlines()[-1])


@case("N", "a recording longer than one window keeps the same two speakers from start to finish")
def _():
    _ready("transcription")
    if os.name != "nt":
        skip("needs Windows speech synthesis to make the recording")
    diar = next(c for c in http("GET", "/api/models")[1]["capabilities"] if c["capability"] == "diarization")
    if not diar["ready"]:
        skip("diarization not available on this device")
    wav = DOCS / "long-spoken.wav"
    voices = _two_voice_wav(wav, 30)
    secs = py(f"import json; from mitra_workers import models; from pathlib import Path; print(json.dumps(models.wav_seconds(Path({str(wav)!r}))))")
    t.assertGreater(secs, 362, "the recording must be long enough to need two windows")
    S["long_secs"] = secs
    mark = len(events())
    job = _job(app("twinmind"), {"path": str(wav), "title": "Long spoken test"}, wait=900)
    t.assertEqual(job["status"], "done", job)
    S["long_events"] = events()[mark:]
    memo = Path(job["result"]["path"]).read_text("utf-8")
    S["long_memo"] = memo
    body = [l for l in memo.split("Appendix: Transcript")[1].splitlines() if l.startswith("[")]
    t.assertRegex(body[-1], r"^\[00:0[6-9]:", "the transcript must reach the end of the recording")
    if voices < 2:
        skip("only one voice is installed, so there is one speaker to find")
    who = lambda word: [re.match(r"\[[\d:]+\] ([^:]+):", l).group(1) for l in body if word in l.lower() and re.match(r"\[[\d:]+\] ([^:]+):", l)]
    asks, answers = who("export"), who("snapshots")
    t.assertGreater(len(asks), 15)
    top = lambda xs: max(set(xs), key=xs.count)
    t.assertGreaterEqual(asks.count(top(asks)) / len(asks), 0.9, f"the first voice's lines are split between speakers: {sorted(set(asks))}")
    t.assertGreaterEqual(answers.count(top(answers)) / len(answers), 0.9, f"the second voice's lines are split between speakers: {sorted(set(answers))}")
    t.assertNotEqual(top(asks), top(answers))
    t.assertRegex(memo, r"diarize: .*\b2 speakers")


@case("N", "on that long recording every model stayed under its cap and none was run twice for memory")
def _():
    if "long_events" not in S:
        skip("the long recording test did not run")
    runs = [e["data"] for e in S["long_events"] if e["type"] == "model.run"]
    t.assertGreaterEqual(len([r for r in runs if "diarization" in r["name"]]), 2, "one run per window")
    t.assertGreaterEqual(len([r for r in runs if r["name"].startswith("whisper")]), 2, "one run per piece")
    for r in runs:
        t.assertLessEqual(r["peak_mb"], r["budget_mb"], f"{r['name']} peaked at {r['peak_mb']} MB")
        t.assertLessEqual(r["budget_mb"], 800)
    t.assertEqual([e for e in S["long_events"] if e["type"] in ("model.cap_raised", "governor.evict")], [])
    longest = max(r["peak_mb"] for r in runs if "diarization" in r["name"])
    t.assertLessEqual(longest, 215, "the speaker model's memory must not grow with the length of the recording")


@case("N", "the long recording's models ran one at a time")
def _():
    if "long_events" not in S:
        skip("the long recording test did not run")
    runs = [e for e in S["long_events"] if e["type"] == "model.run"]
    spans = sorted((datetime.fromisoformat(r["ts"]) - timedelta(milliseconds=r["data"].get("ms", 0)), datetime.fromisoformat(r["ts"])) for r in runs)
    for (s1, e1), (s2, e2) in zip(spans, spans[1:]):
        t.assertLessEqual(e1, s2 + timedelta(seconds=1), "two model runs overlapped")


