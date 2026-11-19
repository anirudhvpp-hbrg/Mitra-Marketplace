# ============================================================================================
# Q. live meetings: noticing one, recording two tracks, the transcript as it grows (0.10.0)
# ============================================================================================
EAR = str(ROOT / "bin" / f"mitra-ear{EXE}")


def _ear(*args, timeout=30):
    if not Path(EAR).is_file():
        skip("the recorder is not built on this system")
    r = subprocess.run([EAR, *args], capture_output=True, text=True, timeout=timeout, creationflags=NOWIN)
    return r.returncode, r.stdout, r.stderr


def _tone(path, seconds, level=6000, rate=16000):
    """A WAV of a steady tone (or silence at level 0): stands in for speech where only loudness matters."""
    import math
    import wave as _wave
    from array import array as _array
    with _wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(_array("h", (int(level * math.sin(i * 0.05)) for i in range(int(seconds * rate)))).tobytes())


@case("Q", "the recorder says which programs are recording from a microphone, as JSON")
def _():
    code, out, err = _ear("who")
    t.assertEqual(code, 0, err)
    t.assertIsInstance(json.loads(out)["using"], list)
    code, out, err = _ear("devices")
    t.assertEqual(code, 0, err)
    t.assertIn("microphone", json.loads(out))


@case("Q", "only an app that declares the meetings service may ask who is using the microphone")
def _():
    s, d, _ = http("GET", "/api/mic", base=app("assistant"))
    t.assertEqual(s, 403, d)
    s, d, _ = http("GET", "/api/mic")
    t.assertEqual(s, 403, "the launcher has no business asking either")
    s, d, _ = http("GET", "/api/mic", base=app("twinmind"))
    t.assertEqual(s, 200, d)
    t.assertEqual(sorted(d), ["meeting", "using"])


@case("Q", "a call app recording from the microphone is noticed as a meeting; when it stops, it is no longer")
def _():
    if os.name != "nt":
        skip("meeting detection is built for Windows only")
    _ear("who")
    fake, d = TMP / "zoom-meeting-test.exe", TMP / "fake-meeting"
    shutil.copyfile(EAR, fake)
    p = subprocess.Popen([str(fake), "record", "--dir", str(d), "--no-system"], stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NOWIN)
    try:
        time.sleep(2.5)
        if p.poll() is not None:
            skip("this machine has no microphone to record from: " + p.stderr.read().decode(errors="replace")[:120])
        tm = app("twinmind")
        seen = _until(lambda: (lambda m: m if m["meeting"] else None)(http("GET", "/api/mic", base=tm)[1]), 8)
        t.assertEqual(seen["meeting"], "Zoom", seen)
        t.assertTrue(any(u["name"] == "zoom-meeting-test.exe" and u["meeting"] for u in seen["using"]))
    finally:
        p.stdin.close()
        p.wait(timeout=10)
    t.assertTrue(_until(lambda: http("GET", "/api/mic", base=app("twinmind"))[1]["meeting"] == "", 8))


@case("Q", "the recorder writes both tracks in pieces of the same length and ends cleanly when told to")
def _():
    if os.name != "nt":
        skip("the recorder has been run on Windows only")
    _ear("who")
    d = TMP / "ear-run"
    p = subprocess.Popen([EAR, "record", "--dir", str(d), "--segment", "5"], stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NOWIN)
    time.sleep(7.5)
    if p.poll() is not None:
        skip("this machine has no sound device to record from: " + p.stderr.read().decode(errors="replace")[:120])
    st = json.loads((d / "status.json").read_text("utf-8"))
    t.assertEqual(st["state"], "recording")
    t.assertEqual(st["pieces_done"], 1)
    (d / "stop").write_text("", "utf-8")
    t.assertEqual(p.wait(timeout=10), 0)
    t.assertEqual(json.loads((d / "status.json").read_text("utf-8"))["state"], "ended")
    t.assertEqual(list(d.glob("*.part")), [], "no half-written piece is left")
    names = [x["name"] for x in st["tracks"]]
    import wave as _wave
    for name in names:
        with _wave.open(str(d / f"{name}-0001.wav")) as w:
            t.assertEqual((w.getframerate(), w.getnchannels(), w.getsampwidth()), (16000, 1, 2))
            t.assertAlmostEqual(w.getnframes() / 16000, 5.0, delta=0.05, msg=f"{name}: every piece but the last is exactly one segment long")
        t.assertTrue((d / f"{name}-0002.wav").is_file())


_LIVE = r'''
import json, sys, wave
from pathlib import Path
from mitra_workers import live, models, library
SEGS = []
def fake_run(app, p, cmd, what=""):
    Path(cmd[cmd.index("-of") + 1] + ".json").write_text(json.dumps({"transcription": [{"text": t, "offsets": {"from": int(a * 1000), "to": int(b * 1000)}} for a, b, t in SEGS]}), "utf-8")
models._run_model = fake_run
models.transcribe_plan = lambda p: ([], "")
P = {"runtime_path": "x", "file": "f.bin", "model": "fake", "args": []}
'''


@case("Q", "a line that runs into the end of a piece is held back and heard whole with the next piece")
def _():
    a, b = DOCS / "lp-0001.wav", DOCS / "lp-0002.wav"
    _tone(a, 30); _tone(b, 30)
    d = py(_LIVE + f"a, b = Path({str(a)!r}), Path({str(b)!r})\n"
           "SEGS[:] = [(0.0, 20.0, ' First sentence.'), (27.5, 30.0, ' Second sentence starts')]\n"
           "one, held = live.hear_piece('t', P, a)\n"
           "SEGS[:] = [(0.0, 6.0, ' Second sentence starts and ends here.'), (8.0, 12.0, ' Third.')]\n"
           "two, held2 = live.hear_piece('t', P, b, a, held)\n"
           "SEGS[:] = [(0.0, 20.0, ' Alone.'), (27.5, 30.0, ' The very end.')]\n"
           "last, held3 = live.hear_piece('t', P, a, last=True)\n"
           "print(json.dumps({'one': [l['text'] for l in one], 'held': held, 'two': [(round(l['start'], 1), l['text']) for l in two], 'held2': held2,\n"
           "                  'last': len(last), 'held3': held3, 'left': [f.name for f in a.parent.glob('lp-*lead*')]}))")
    t.assertEqual(d["one"], ["First sentence."])
    t.assertAlmostEqual(d["held"], 2.5, delta=0.01)
    t.assertEqual(d["two"], [[-2.5, "Second sentence starts and ends here."], [5.5, "Third."]], "times are from the piece's own start")
    t.assertEqual((d["last"], d["held3"]), (2, 0.0), "the last piece of a recording keeps its last line")
    t.assertEqual(d["left"], [], "the temporary joined file is removed")


@case("Q", "a stock phrase heard on a near-silent piece is dropped; the same words on a spoken piece are kept")
def _():
    faint, clear = DOCS / "faint.wav", DOCS / "clear.wav"
    _tone(faint, 10, level=60); _tone(clear, 10, level=6000)
    d = py(_LIVE + f"faint, clear = Path({str(faint)!r}), Path({str(clear)!r})\n"
           "SEGS[:] = [(1.0, 2.0, ' Thank you.'), (3.0, 6.0, ' The budget is forty lakh.')]\n"
           "print(json.dumps({'faint_loud': live.loud(faint), 'clear_loud': live.loud(clear),\n"
           "                  'faint': [l['text'] for l in live.hear_piece('t', P, faint, last=True)[0]], 'clear': [l['text'] for l in live.hear_piece('t', P, clear, last=True)[0]]}))")
    t.assertLess(d["faint_loud"], 150)
    t.assertGreater(d["clear_loud"], 1000)
    t.assertEqual(d["faint"], ["The budget is forty lakh."])
    t.assertEqual(d["clear"], ["Thank you.", "The budget is forty lakh."])


@case("Q", "the pieces are put together into one recording per track and a mix, all the same length")
def _():
    home = _nm_home()
    d = home / "run" / "live" / "20260101-100000"
    d.mkdir(parents=True, exist_ok=True)
    (d / "meeting.json").write_text(json.dumps({"stamp": "2026-01-01 1000", "title": "Assembled"}), "utf-8")
    _tone(d / "mic-0001.wav", 30, 3000); _tone(d / "sys-0001.wav", 30, 0)
    _tone(d / "mic-0002.wav", 12, 0); _tone(d / "sys-0002.wav", 12.5, 5000)
    out = py("import json, wave; from pathlib import Path; from mitra_workers import live\n"
             f"f = live.assemble(Path({str(d)!r}), 'Assembled')\n"
             "n = {k: wave.open(f[k]).getnframes() for k in ('mic', 'sys', 'mix')}\n"
             "print(json.dumps({'n': n, 'name': Path(f['mix']).name, 'you': live.owner_speaker([{'start': 0, 'end': 29, 'speaker': 'Speaker 1'}, {'start': 31, 'end': 42, 'speaker': 'Speaker 2'}], Path(f['mic']), Path(f['sys']))}))", home=home)
    t.assertEqual(len(set(out["n"].values())), 1, out)
    t.assertEqual(out["n"]["mix"], int(42.5 * 16000))
    t.assertEqual(out["name"], "2026-01-01 1000 Assembled.mix.wav")
    t.assertEqual(out["you"], "Speaker 1", "the voice that is loud on the microphone track is the person at this computer")
    t.assertTrue((d / "assembled").is_file())


@case("Q", "TwinMind reports whether it can record, the live model, and recordings left without a memo")
def _():
    home = _nm_home()
    d = home / "run" / "live" / "20260102-090000"
    d.mkdir(parents=True, exist_ok=True)
    (d / "meeting.json").write_text(json.dumps({"title": "Left behind", "started": 1767340800}), "utf-8")
    _tone(d / "mic-0001.wav", 5, 0); _tone(d / "sys-0001.wav", 5, 4000)
    st = http("GET", "/api/apps/twinmind/live", base=_nm_base())[1]
    t.assertIsNone(st["recording"])
    t.assertEqual(st["recorder"], Path(EAR).is_file())
    t.assertIn("Left behind", [r["title"] for r in st["leftover"]])
    t.assertNotIn("Assembled", [r["title"] for r in st["leftover"]], "a recording already put together is not offered again")
    t.assertFalse(http("POST", "/api/apps/twinmind/live/stop", {}, base=_nm_base())[1]["stopped"])


@case("Q", "the TwinMind page has the Live tab: the offer to record, levels, the growing transcript, your notes")
def _():
    page = (ROOT / "apps" / "twinmind" / "ui" / "index.html").read_text("utf-8")
    for part in ('data-tab="live"', "Do you want me to record it?", "Not this one", "Start recording", "Stop and write the memo", 'id="liveLines"',
                 'id="liveNotes"', "M.api('/api/mic')", "api('job/live'", "Write its memo", "only while TwinMind is open"):
        t.assertIn(part, page)


