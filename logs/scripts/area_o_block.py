# ============================================================================================
# O. taking turns: the line for the model, saved pieces and resume, the line of recordings (0.9.0)
# ============================================================================================
def _hold(name, seconds, *extra):
    return subprocess.Popen([GOV, "run", "--app", "holder", "--name", name, "--est-mb", "10", *extra, "--", *burner(5, seconds)], env=env(), creationflags=NOWIN)


def _status(home=HOME):
    return json.loads(gov("status", home=home)[1])


def _until(test, within=10.0, every=0.25):
    end = time.time() + within
    while time.time() < end:
        v = test()
        if v:
            return v
        time.sleep(every)
    return test()


@case("O", "nobody is turned away for waiting: with no limit given a second model waits its turn and runs")
def _():
    first = _hold("line-first", 4)
    time.sleep(1.2)
    t0 = time.time()
    code, _, err = gov("run", "--app", "app-two", "--name", "line-second", "--est-mb", "10", "--", *burner(5, 1))
    first.wait(timeout=20)
    t.assertEqual(code, 0, err)
    t.assertGreater(time.time() - t0, 2.0, "it must have waited for the first")
    load = [e for e in events() if e["type"] == "model.load" and e["data"]["name"] == "line-second"][-1]
    t.assertGreaterEqual(load["data"]["waited_s"], 1)
    t.assertEqual(_status()["line"], [])


@case("O", "a question goes ahead of a long job that was already waiting")
def _():
    first = _hold("order-first", 5)
    time.sleep(1.2)
    bg = subprocess.Popen([GOV, "run", "--app", "twinmind", "--name", "order-job", "--est-mb", "10", "--what", "piece 2 of 9", "--", *burner(5, 1)], env=env(), creationflags=NOWIN)
    time.sleep(0.8)
    ask = subprocess.Popen([GOV, "run", "--app", "assistant", "--name", "order-question", "--est-mb", "10", "--priority", "interactive", "--what", "a question",
                            "--", *burner(5, 1)], env=env(), creationflags=NOWIN)
    line = _until(lambda: (lambda l: l if len(l) == 2 else None)(_status()["line"]), 5)
    t.assertEqual([x["name"] for x in line], ["order-question", "order-job"], "the question is first in line though it came second")
    t.assertEqual(line[0]["priority"], "interactive")
    t.assertEqual(line[1]["what"], "piece 2 of 9")
    t.assertEqual(line[1]["app"], "twinmind")
    t.assertGreaterEqual(line[1]["waited_s"], 0)
    for p in (first, ask, bg):
        t.assertEqual(p.wait(timeout=30), 0)
    loads = [e["data"]["name"] for e in events() if e["type"] == "model.load" and e["data"]["name"].startswith("order-")][-3:]
    t.assertEqual(loads, ["order-first", "order-question", "order-job"])
    t.assertEqual(_status()["line"], [])


@case("O", "two long jobs get the model in the order they asked")
def _():
    first = _hold("fifo-first", 3)
    time.sleep(1.0)
    a = subprocess.Popen([GOV, "run", "--app", "x", "--name", "fifo-a", "--est-mb", "10", "--", *burner(5, 1)], env=env(), creationflags=NOWIN)
    time.sleep(0.6)
    b = subprocess.Popen([GOV, "run", "--app", "y", "--name", "fifo-b", "--est-mb", "10", "--", *burner(5, 1)], env=env(), creationflags=NOWIN)
    for p in (first, a, b):
        t.assertEqual(p.wait(timeout=30), 0)
    loads = [e["data"]["name"] for e in events() if e["type"] == "model.load" and e["data"]["name"].startswith("fifo-")][-3:]
    t.assertEqual(loads, ["fifo-first", "fifo-a", "fifo-b"])


@case("O", "the running model says what it is doing and for whom")
def _():
    p = _hold("doing", 3, "--what", "what was said, piece 7 of 24")
    lease = _until(lambda: (_status()["leases"] or [None])[0], 5)
    t.assertEqual(lease["what"], "what was said, piece 7 of 24")
    t.assertEqual(lease["apps"], ["holder"])
    p.wait(timeout=20)


def _parent_of(gov_args):
    """A Python process that starts a governor and waits for it: the governor's caller."""
    code = f"import subprocess, sys; subprocess.run({[GOV, *gov_args]!r}, creationflags={NOWIN})"
    return subprocess.Popen([sys.executable, "-c", code], env=env(), creationflags=NOWIN)


@case("O", "a waiter whose caller has gone leaves the line and never runs")
def _():
    first = _hold("gone-first", 7)
    time.sleep(1.2)
    parent = _parent_of(["run", "--app", "assistant", "--name", "gone-waiter", "--est-mb", "10", "--priority", "interactive", "--", *burner(5, 1)])
    t.assertTrue(_until(lambda: len(_status()["line"]) == 1, 5), "the waiter should be in line")
    kill_pid(parent.pid)
    t.assertTrue(_until(lambda: _status()["line"] == [], 6), "the line should empty once the caller is gone")
    first.wait(timeout=20)
    time.sleep(0.5)
    t.assertEqual([e for e in events() if e["type"] == "model.load" and e["data"]["name"] == "gone-waiter"], [])
    t.assertTrue([e for e in events() if e["type"] == "model.wait_left" and e["data"]["name"] == "gone-waiter"])


@case("O", "a waiter that is released while waiting leaves the line")
def _():
    first = _hold("rel-first", 5)
    time.sleep(1.2)
    w = subprocess.Popen([GOV, "run", "--app", "assistant", "--name", "rel-waiter", "--est-mb", "10", "--hold-stdin", "--", *burner(5, 30)],
                         stdin=subprocess.PIPE, env=env(), creationflags=NOWIN)
    t.assertTrue(_until(lambda: len(_status()["line"]) == 1, 5))
    w.stdin.close()
    t.assertEqual(w.wait(timeout=6), 0)
    t.assertEqual(_status()["line"], [])
    first.wait(timeout=20)


@case("O", "a running model whose caller has gone is stopped")
def _():
    parent = _parent_of(["run", "--app", "twinmind", "--name", "orphan", "--est-mb", "10", "--", *burner(5, 60)])
    t.assertTrue(_until(lambda: _status()["leases"], 6), "the model should be running")
    kill_pid(parent.pid)
    t.assertTrue(_until(lambda: _status()["leases"] == [], 8), "the model should stop once its caller is gone")
    run = _until(lambda: [e for e in events() if e["type"] == "model.run" and e["data"]["name"] == "orphan"], 4)[-1]
    t.assertEqual(run["data"]["end"], "its caller is gone")


@case("O", "a ticket left behind by a crash does not block the line")
def _():
    d = HOME / "run" / "line"
    d.mkdir(parents=True, exist_ok=True)
    (d / "000000000000001-999999.json").write_text(json.dumps({"pid": 999999, "app": "ghost", "name": "ghost", "priority": "interactive"}), "utf-8")
    code, _, err = gov("run", "--app", "x", "--name", "after-ghost", "--est-mb", "10", "--", *burner(5, 1))
    t.assertEqual(code, 0, err)
    t.assertEqual(list(d.glob("*.json")), [])


# ---- saved pieces --------------------------------------------------------------------------
_FAKE = r'''
import json, sys, wave, time
from pathlib import Path
from mitra_workers import models, work
calls = []
def silent(path, seconds):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        for _ in range(int(seconds // 10)):
            w.writeframes(bytes(16000 * 2 * 10))
def fake_run(app, p, cmd, what=""):
    calls.append((p["model"], what))
    if HOOK:
        HOOK(len(calls), p)
    if "-of" in cmd:
        Path(cmd[cmd.index("-of") + 1] + ".json").write_text(json.dumps({"result": {"language": "en"},
            "transcription": [{"text": " piece", "offsets": {"from": 0, "to": 400}}, {"text": " %d." % len(calls), "offsets": {"from": 500, "to": 900}}]}), "utf-8")
    if "--turns-out" in cmd:
        Path(cmd[cmd.index("--turns-out") + 1]).write_text(json.dumps([{"start": 1.0, "end": 200.0, "speaker": "a"}, {"start": 201.0, "end": 290.0, "speaker": "b"}]), "utf-8")
HOOK = None
models._run_model = fake_run
CANDS = [{"ready": True, "model": "big", "file": "big.bin", "est_mb": 900, "runtime_path": "x", "args": []},
         {"ready": True, "model": "small", "file": "small.bin", "est_mb": 500, "runtime_path": "x", "args": []}]
def fake_pick(capability, exclude=()):
    if capability == "diarization":
        return {"ready": True, "model": "diar", "file": "d.gguf", "est_mb": 200, "runtime_path": "x"}
    return next((c for c in CANDS if c["model"] not in exclude), {"ready": False, "hint": "none left"})
models.pick = fake_pick
'''


def _fake(body, home=HOME):
    wav = DOCS / "silent-16min.wav"
    return py(_FAKE + f"wav = Path({str(wav)!r})\nif not wav.exists(): silent(wav, 960)\n" + body, home=home)


@case("O", "every finished piece of speech is saved, and a second run does none of them again")
def _():
    d = _fake("w = work.Work(wav, 'accurate', 'english'); work.recycle(w.dir); w = work.Work(wav, 'accurate', 'english')\n"
              "a = models.transcribe('twinmind', wav, wav_ready=True, work=w); n1 = len(calls)\n"
              "saved = sorted(f.name for f in w.dir.glob('words-*.json'))\n"
              "w2 = work.Work(wav, 'accurate', 'english'); b = models.transcribe('twinmind', wav, wav_ready=True, work=w2); n2 = len(calls) - n1\n"
              "(w2.dir / 'words-0001.json').unlink(); c = models.transcribe('twinmind', wav, wav_ready=True, work=w2); n3 = len(calls) - n1 - n2\n"
              "print(json.dumps({'n1': n1, 'n2': n2, 'n3': n3, 'saved': saved, 'same': a == b, 'resumed': w2.resumed, 'progress': w2.meta['progress'],\n"
              "                  'what': calls[0][1], 'texts': [x['text'] for x in a]}))")
    t.assertEqual(d["n1"], 3, "16 minutes is three pieces")
    t.assertEqual(d["saved"], ["words-0000.json", "words-0001.json", "words-0002.json"])
    t.assertEqual(d["n2"], 0, "nothing is heard twice")
    t.assertEqual(d["n3"], 1, "only the missing piece is redone")
    t.assertTrue(d["same"])
    t.assertTrue(d["resumed"])
    t.assertEqual(d["progress"]["transcribe"], [3, 3])
    t.assertEqual(d["what"], "what was said, piece 1 of 3")


@case("O", "every finished speaker window is saved, and a second run hears none of them again")
def _():
    d = _fake("w = work.Work(wav, 'd'); work.recycle(w.dir); w = work.Work(wav, 'd')\n"
              "a = models.diarize('twinmind', wav, work=w); n1 = len(calls)\n"
              "b = models.diarize('twinmind', wav, work=work.Work(wav, 'd')); n2 = len(calls) - n1\n"
              "print(json.dumps({'n1': n1, 'n2': n2, 'windows': len(models.diar_windows(960)), 'same': a == b, 'speakers': sorted({t['speaker'] for t in a})}))")
    t.assertEqual(d["n1"], d["windows"])
    t.assertGreaterEqual(d["windows"], 4)
    t.assertEqual(d["n2"], 0)
    t.assertTrue(d["same"])
    t.assertEqual(d["speakers"], ["Speaker 1", "Speaker 2"])


@case("O", "pause stops after the piece in hand; resume does only what was left")
def _():
    d = _fake("w = work.Work(wav, 'p'); work.recycle(w.dir); w = work.Work(wav, 'p')\n"
              "def hook(n, p):\n    if n == 1: (w.dir / 'pause').write_text('')\n"
              "HOOK = hook\n"
              "try:\n    models.transcribe('twinmind', wav, wav_ready=True, work=w); paused = False\n"
              "except work.Paused:\n    paused = True\n"
              "n1 = len(calls); HOOK = None; (w.dir / 'pause').unlink()\n"
              "out = models.transcribe('twinmind', wav, wav_ready=True, work=work.Work(wav, 'p'))\n"
              "print(json.dumps({'paused': paused, 'n1': n1, 'n2': len(calls) - n1, 'lines': len(out)}))")
    t.assertEqual(d, {"paused": True, "n1": 1, "n2": 2, "lines": d["lines"]})
    t.assertGreaterEqual(d["lines"], 1)


@case("O", "a speech model refused memory is replaced from that piece on, not from the start")
def _():
    d = _fake("w = work.Work(wav, 'm'); work.recycle(w.dir); w = work.Work(wav, 'm')\n"
              "def hook(n, p):\n    if n == 2 and p['model'] == 'big': raise models.MemoryDenied('no room')\n"
              "HOOK = hook; info = {}\n"
              "models.transcribe('twinmind', wav, wav_ready=True, work=w, info=info)\n"
              "print(json.dumps({'calls': [c[0] for c in calls], 'pieces': [w.load('words-%04d' % i)['model'] for i in range(3)], 'info': info}))")
    t.assertEqual(d["calls"], ["big", "big", "small", "small"])
    t.assertEqual(d["pieces"], ["big", "small", "small"])
    t.assertEqual(d["info"]["stepped_down_from"], "big")
    t.assertEqual(d["info"]["model"], "big then small")
    t.assertTrue([e for e in events() if e["type"] == "model.fallback" and e["data"].get("piece") == 2])


@case("O", "fast speed uses the next speech model down; accurate uses the first")
def _():
    d = _fake("print(json.dumps([models.transcription_choice('accurate')['model'], models.transcription_choice('fast')['model'],\n"
              "                  models.transcription_choice('fast', ('big',))['model']]))")
    t.assertEqual(d, ["big", "small", "small"])


@case("O", "saved pieces belong to one recording at one speed: a changed file or another speed starts afresh")
def _():
    d = py("import json, os, time; from pathlib import Path; from mitra_workers import work\n"
           f"f = Path({str(DOCS / 'fp.txt')!r}); f.write_text('one', 'utf-8')\n"
           "a = work.fingerprint(f, 'accurate'); b = work.fingerprint(f, 'fast'); a2 = work.fingerprint(f, 'accurate')\n"
           "f.write_text('one two', 'utf-8'); c = work.fingerprint(f, 'accurate')\n"
           "print(json.dumps([a == a2, a != b, a != c]))")
    t.assertEqual(d, [True, True, True])


@case("O", "the length of a recording is read without converting it")
def _():
    wav = DOCS / "silent-16min.wav"
    d = py(f"import json; from pathlib import Path; from mitra_workers import models; print(json.dumps(models.audio_seconds(Path({str(wav)!r}))))")
    t.assertAlmostEqual(d, 960, delta=1)


# ---- the line of recordings, through the app ---------------------------------------------------
def _tm(method, name, body=None, base=None):
    s, d, _ = http(method, "/api/apps/twinmind/" + name, body, base=base or _nm_base())
    t.assertEqual(s, 200, d)
    return d


@case("O", "before anything runs the page is told how long a recording will take at each speed")
def _():
    wav = DOCS / "silent-16min.wav"
    d = _tm("GET", "estimate?path=" + q(wav))
    t.assertTrue(d["audio"])
    t.assertAlmostEqual(d["seconds"], 960, delta=1)
    for speed in ("accurate", "fast"):
        t.assertEqual(d[speed]["pieces"], 3)
        t.assertGreaterEqual(d[speed]["windows"], 4)
        t.assertGreater(d[speed]["seconds"], 60)
    t.assertFalse(_tm("GET", "estimate?path=" + q(DOCS / "standup.txt"))["audio"])


@case("O", "while a recording is being worked on, another one joins the line instead of starting")
def _():
    base, home = _nm_base(), _nm_home()
    (home / "run").mkdir(parents=True, exist_ok=True)
    (home / "run" / "twinmind-line.json").unlink(missing_ok=True)
    (home / "run" / "twinmind-runner.json").write_text(json.dumps({"pid": os.getpid(), "job": "busy"}), "utf-8")   # this test process stands in for a job at work
    for n, name in enumerate(("q1.txt", "q2.txt", "q3.txt")):
        (DOCS / name).write_text(TRANSCRIPT, "utf-8")
        job = _job(base, {"path": str(DOCS / name), "title": f"Queued {n + 1}", "speed": "fast" if n == 1 else "accurate"})
        t.assertEqual(job["status"], "done", job)
        t.assertEqual(job["result"], {"queued": True, "position": n + 1})
    st = _tm("GET", "state", base=base)
    t.assertEqual(st["running"]["job"], "busy")
    t.assertEqual([i["title"] for i in st["line"]], ["Queued 1", "Queued 2", "Queued 3"])
    t.assertEqual([i["speed"] for i in st["line"]], ["accurate", "fast", "accurate"])
    t.assertEqual(len([e for e in events(home) if e["type"] == "job.queued"]), 3)


@case("O", "the line can be reordered and a recording removed from it")
def _():
    base = _nm_base()
    _tm("POST", "line", {"order": [1, 0]}, base=base)      # second first, third removed
    t.assertEqual([i["title"] for i in _tm("GET", "state", base=base)["line"]], ["Queued 2", "Queued 1"])


@case("O", "when a recording is done the next in line is written by itself, each as its own job")
def _():
    base, home = _nm_base(), _nm_home()
    (home / "run" / "twinmind-runner.json").unlink()          # the stand-in job is over
    s, r, _ = http("POST", "/api/apps/twinmind/job/run", {"path": str(DOCS / "standup.txt"), "title": "Head of line"}, base=base)
    titles, jid = [], r["id"]
    for _ in range(3):
        job = _until(lambda: (lambda j: j if j["status"] in ("done", "failed") else None)(http("GET", "/api/jobs/" + jid, base=base)[1]), 60, 0.5)
        t.assertEqual(job["status"], "done", job)
        titles.append(job["result"]["title"])
        jid = job.get("next")
        if not jid:
            break
    t.assertEqual(titles, ["Head of line", "Queued 2", "Queued 1"])
    st = _tm("GET", "state", base=base)
    t.assertEqual((st["running"], st["line"]), (None, []))
    for title in titles:
        t.assertTrue(list((TMP / "dropbox").rglob(f"* {title}.md")), title)


@case("O", "a job that stopped is listed with what was kept, and discarding it removes the pieces")
def _():
    base, home = _nm_base(), _nm_home()
    src = DOCS / "standup.txt"
    key = py(f"import json; from pathlib import Path; from mitra_workers import work\n"
             f"w = work.Work(Path({str(src)!r}), 'accurate', 'english'); w.save('words-0000', {{'words': []}})\n"
             "w.note(state='running', stage='transcribe', item={'path': w.meta['source'], 'name': 'standup.txt', 'speed': 'accurate', 'title': '', 'attendees': ''}, pid=999999)\n"
             "w.meta['progress'] = {'diarize': [29, 29], 'transcribe': [16, 24]}; w.save('job', w.meta); print(json.dumps(w.key))", home=home)
    u = [x for x in _tm("GET", "state", base=base)["unfinished"] if x["key"] == key]
    t.assertEqual(len(u), 1)
    t.assertEqual(u[0]["progress"]["transcribe"], [16, 24])
    t.assertEqual(u[0]["stage"], "transcribe")
    t.assertEqual(u[0]["name"], "standup.txt")
    t.assertFalse(u[0]["source_missing"])
    d = _tm("POST", "discard", {"key": key}, base=base)
    t.assertTrue(d["discarded"])
    t.assertFalse((home / "run" / "work" / key).exists())
    t.assertEqual([x for x in _tm("GET", "state", base=base)["unfinished"] if x["key"] == key], [])
    t.assertFalse(_tm("POST", "discard", {"key": "../../config"}, base=base)["discarded"], "only a job's own folder can be discarded")


@case("O", "a finished job leaves no saved pieces behind")
def _():
    base, home = _nm_base(), _nm_home()
    job = _job(base, {"path": str(DOCS / "standup.txt"), "title": "Leaves nothing"})
    t.assertEqual(job["status"], "done", job)
    t.assertFalse(job["result"]["resumed"])
    key = py(f"import json; from pathlib import Path; from mitra_workers import work; print(json.dumps(work.fingerprint(Path({str(DOCS / 'standup.txt')!r}), 'accurate', 'english')))", home=home)
    t.assertFalse((home / "run" / "work" / key).exists(), "the pieces of a finished job must be gone (a failed job's are kept)")


@case("O", "pause and stop are harmless when nothing is running")
def _():
    base = _nm_base()
    t.assertFalse(_tm("POST", "pause", {}, base=base)["paused"])
    t.assertFalse(_tm("POST", "stop", {}, base=base)["stopped"])


@case("O", "the memory report counts waits, queued recordings and resumed jobs")
def _():
    rep = http("GET", "/api/memory/report?days=1")[1]
    t.assertGreaterEqual(rep["report"]["turns"]["waited_for_model"], 3)
    t.assertIn("## Taking turns", rep["markdown"])


@case("O", "the screens show the line: TwinMind, Ask Mitra and the launcher")
def _():
    tm = (ROOT / "apps" / "twinmind" / "ui" / "index.html").read_text("utf-8")
    for part in ("Add to the line", "api('pause'", "api('stop'", "api('discard'", "Resume", "Start over", "Next up", 'value="fast"', "left`", "did not finish"):
        t.assertIn(part, tm)
    ask = (ROOT / "apps" / "assistant" / "ui" / "index.html").read_text("utf-8")
    for part in ("Waiting for a turn", "Cancel question", "ctl.abort()"):
        t.assertIn(part, ask)
    home_page = (ROOT / "web" / "index.html").read_text("utf-8")
    for part in ("Waiting for the model", 'id="busy"', "goes next"):
        t.assertIn(part, home_page)


# ---- with real models ------------------------------------------------------------------------
@case("O", "a question asked while another model is held waits for its turn and is then answered")
def _():
    _ready("assistant")
    first = _hold("ask-blocker", 8)
    time.sleep(1.5)
    t0 = time.time()
    s, d, _ = http("POST", "/api/ask", {"app_id": "assistant", "prompt": "Reply with the single word: ready."}, base=app("assistant"), timeout=240)
    first.wait(timeout=20)
    t.assertEqual(s, 200, d)
    t.assertGreater(time.time() - t0, 5, "it must have waited for the model that was held")
    t.assertGreater(d["waited_ms"], 3000)
    t.assertTrue(d["text"])
    waits = [e for e in events() if e["type"] == "model.wait" and e["app"] == "assistant"]
    t.assertEqual(waits[-1]["data"]["priority"], "interactive")


@case("O", "a question cancelled while waiting leaves the line and loads nothing")
def _():
    _ready("assistant")
    base = app("assistant")
    first = _hold("cancel-blocker", 9)
    time.sleep(1.5)
    before = len([e for e in events() if e["type"] == "model.load" and e["app"] == "assistant"])
    try:
        http("POST", "/api/ask", {"app_id": "assistant", "prompt": "Never answered."}, base=base, timeout=3)
        t.fail("the question should still have been waiting")
    except (TimeoutError, urllib.error.URLError, OSError):
        pass                                                   # the page gave up, as Cancel question does
    t.assertTrue(_until(lambda: _status()["line"] == [], 8), "the cancelled question should leave the line")
    first.wait(timeout=20)
    time.sleep(1)
    t.assertEqual(len([e for e in events() if e["type"] == "model.load" and e["app"] == "assistant"]), before)
    t.assertEqual(_status()["leases"], [])


LONG_TALK = "\n".join(f"[00:{m:02d}:{s:02d}] {who}: {line}" for (m, s, who, line) in [
    (i // 2, 30 * (i % 2), ("Priya", "Sam", "Dana")[i % 3],
     (f"On item {i + 1}, the export job fails when an invoice has more than {200 + i} lines, so the client cannot close the month. "
      f"Sam will send the fix for item {i + 1} by Thursday and Dana will check it on the staging database before it ships. "
      "We agreed the release waits until that check has passed, and Priya will tell the client about the new date today."))
    for i in range(30)])


@case("O", "the notes model steps aside between sections for a question, and the memo is still complete")
def _():
    _ready("meeting-notes")
    _ready("assistant")
    src = DOCS / "long-talk.txt"
    src.write_text(LONG_TALK, "utf-8")
    tm, am = app("twinmind"), app("assistant")
    mark = len(events())
    s, r, _ = http("POST", "/api/apps/twinmind/job/run", {"path": str(src), "title": "Stepping aside"}, base=tm)
    t.assertEqual(s, 200, r)
    job = _until(lambda: (lambda j: j if (j.get("progress") or {}).get("understand", [0])[0] >= 1 or j["status"] not in ("running", "starting") else None)(http("GET", "/api/jobs/" + r["id"], base=tm)[1]), 240, 1)
    t.assertEqual(job["status"], "running", job)
    total = job["progress"]["understand"][1]
    t.assertGreaterEqual(total, 3, "the transcript must be long enough for several sections")
    s, d, _ = http("POST", "/api/ask", {"app_id": "assistant", "prompt": "Reply with the single word: ready."}, base=am, timeout=300)
    t.assertEqual(s, 200, d)
    mid = http("GET", "/api/jobs/" + r["id"], base=tm)[1]
    t.assertEqual(mid["status"], "running", "the question was answered while the notes were still being written")
    job = _until(lambda: (lambda j: j if j["status"] not in ("running", "starting") else None)(http("GET", "/api/jobs/" + r["id"], base=tm)[1]), 900, 2)
    t.assertEqual(job["status"], "done", job)
    t.assertGreaterEqual(job["result"]["yields"], 1)
    new = events()[mark:]
    t.assertTrue([e for e in new if e["type"] == "model.yield"])
    t.assertEqual(job["progress"]["understand"], [total, total])
    memo = Path(job["result"]["path"]).read_text("utf-8")
    t.assertIn("stepped aside for another app", memo)
    runs = sorted((datetime.fromisoformat(e["ts"]) - timedelta(milliseconds=e["data"].get("ms", 0)), datetime.fromisoformat(e["ts"])) for e in new if e["type"] == "model.run")
    for (s1, e1), (s2, e2) in zip(runs, runs[1:]):
        t.assertLessEqual(e1, s2 + timedelta(seconds=1), "two models overlapped")
    for e in new:
        if e["type"] == "model.run":
            t.assertLessEqual(e["data"]["peak_mb"], 1024)


@case("O", "a job stopped part way keeps its pieces, shows as unfinished, and resumes without redoing them")
def _():
    _ready("transcription")
    wav = DOCS / "long-spoken.wav"
    if not wav.exists():
        skip("the long recording was not made")
    tm = app("twinmind")
    s, r, _ = http("POST", "/api/apps/twinmind/job/run", {"path": str(wav), "title": "Stopped and resumed", "speed": "fast"}, base=tm)
    job = _until(lambda: (lambda j: j if (j.get("progress") or {}).get("diarize", [0])[0] >= 1 or j["status"] not in ("running", "starting") else None)(http("GET", "/api/jobs/" + r["id"], base=tm)[1]), 400, 1)
    t.assertEqual(job["status"], "running", job)
    t.assertTrue(_tm("POST", "stop", {}, base=tm)["stopped"])
    t.assertEqual(http("GET", "/api/jobs/" + r["id"], base=tm)[1]["status"], "stopped")
    t.assertTrue(_until(lambda: _status()["leases"] == [] and _status()["line"] == [], 10), "the model must stop with the job")
    u = [x for x in _tm("GET", "state", base=tm)["unfinished"] if x["name"] == wav.name]
    t.assertEqual(len(u), 1)
    kept = u[0]["progress"]["diarize"][0]
    t.assertGreaterEqual(kept, 1)
    t.assertEqual(u[0]["state"], "stopped")
    mark = len(events())
    job = _job(tm, {**u[0]["item"]}, wait=900)
    t.assertEqual(job["status"], "done", job)
    t.assertTrue(job["result"]["resumed"])
    new = events()[mark:]
    t.assertTrue([e for e in new if e["type"] == "job.resumed"])
    windows = job["progress"]["diarize"][1]
    heard = len([e for e in new if e["type"] == "model.run" and "diarization" in e["data"]["name"]])
    t.assertEqual(heard, windows - kept, "saved windows must not be heard again")
    memo = Path(job["result"]["path"]).read_text("utf-8")
    t.assertIn("picked up from saved pieces after a stop", memo)
    t.assertIn("fast speed was chosen", memo)
    body = [l for l in memo.split("Appendix: Transcript")[1].splitlines() if l.startswith("[")]
    t.assertRegex(body[-1], r"^\[00:0[6-9]:", "the transcript must reach the end of the recording")
    t.assertEqual([x for x in _tm("GET", "state", base=tm)["unfinished"] if x["name"] == wav.name], [])


