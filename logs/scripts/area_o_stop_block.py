@case("O", "a model stopped by hand ends with its own outcome, not as a failure")
def _():
    p = subprocess.Popen([GOV, "run", "--app", "t", "--name", "by-hand", "--est-mb", "10", "--", *burner(5, 60)], env=env(), creationflags=NOWIN)
    t.assertTrue(_until(lambda: _status()["leases"], 6))
    t.assertTrue(json.loads(gov("kill")[1])["evicted"])
    t.assertEqual(p.wait(timeout=10), 143)
    run = [e for e in events() if e["type"] == "model.run" and e["data"]["name"] == "by-hand"][-1]
    t.assertEqual(run["data"]["end"], "stopped by hand")
    out = py("import json; from mitra_workers import models\n"
             "try:\n    models._raise_for(143, ''); print(json.dumps('no'))\nexcept models.Stopped as e:\n    print(json.dumps('stopped'))")
    t.assertEqual(out, "stopped")


def _notes_job_at_work(title):
    """A TwinMind job on a long transcript, returned once its notes model has finished a section."""
    src = DOCS / "long-talk.txt"
    src.write_text(LONG_TALK + f"\n[00:16:00] Priya: That is all for {title}.\n", "utf-8")
    tm = app("twinmind")
    s, r, _ = http("POST", "/api/apps/twinmind/job/run", {"path": str(src), "title": title}, base=tm)
    t.assertEqual(s, 200, r)
    job = _until(lambda: (lambda j: j if (j.get("progress") or {}).get("understand", [0])[0] >= 1 or j["status"] not in ("running", "starting") else None)(http("GET", "/api/jobs/" + r["id"], base=tm)[1]), 240, 1)
    t.assertEqual(job["status"], "running", job)
    return tm, r["id"], src


@case("O", "stopping the model by hand stops the job and keeps its pieces; the job does not carry on without them")
def _():
    _ready("meeting-notes")
    tm, jid, src = _notes_job_at_work("Stopped by hand")
    time.sleep(2)                                              # into the next section
    t.assertTrue(http("POST", "/api/system/evict", {}, base=tm)[1]["evicted"])
    job = _until(lambda: (lambda j: j if j["status"] != "running" else None)(http("GET", "/api/jobs/" + jid, base=tm)[1]), 30, 0.5)
    t.assertEqual(job["status"], "stopped", job)
    t.assertFalse(list((TMP / "dropbox").rglob("* Stopped by hand.md")), "no memo may be written from a job that was stopped")
    u = [x for x in _tm("GET", "state", base=tm)["unfinished"] if x["name"] == src.name]
    t.assertEqual(len(u), 1)
    t.assertEqual(u[0]["state"], "stopped")
    t.assertGreaterEqual(u[0]["progress"]["understand"][0], 1)
    t.assertEqual(_status()["leases"], [])
    job = _job(tm, {**u[0]["item"]}, wait=600)
    t.assertEqual(job["status"], "done", job)
    t.assertTrue(job["result"]["resumed"])
    t.assertTrue(list((TMP / "dropbox").rglob("* Stopped by hand.md")))


@case("O", "closing an app stops its job with it: no worker or model is left running, and the job can be resumed")
def _():
    _ready("meeting-notes")
    tm, jid, src = _notes_job_at_work("Closed with the app")
    s, d, _ = http("POST", "/api/stop/twinmind", {})
    t.assertEqual(s, 200, d)
    t.assertTrue(gone(tm), "the app should have ended")
    left = lambda: [p[:160] for p in mitra_processes() if "mitra_workers" in p or "llama-server" in p or "mitra-governor" in p]   # noqa: E731
    _until(lambda: not left(), 12)
    t.assertEqual(left(), [], "the job's worker and its model must end with the app")
    t.assertEqual(json.loads((HOME / "run" / "jobs" / f"{jid}.json").read_text("utf-8"))["status"], "stopped")
    t.assertFalse(list((TMP / "dropbox").rglob("* Closed with the app.md")))
    tm = app("twinmind")
    st = _tm("GET", "state", base=tm)
    t.assertIsNone(st["running"])
    u = [x for x in st["unfinished"] if x["name"] == src.name]
    t.assertEqual(len(u), 1)
    t.assertGreaterEqual(u[0]["progress"]["understand"][0], 1)
    t.assertTrue(_tm("POST", "discard", {"key": u[0]["key"]}, base=tm)["discarded"])


