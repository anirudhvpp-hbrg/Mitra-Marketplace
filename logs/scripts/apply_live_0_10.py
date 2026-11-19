"""0.10.0, part 3: live meetings in TwinMind's worker.

  - job/live: record with mitra-ear, write the live transcript piece by piece, and when the meeting
    is stopped put the recording together and write the memo with the full pipeline
  - live (state and new lines), live/stop, live/notes (what you type during the meeting)
  - job/live-finish: write the memo for a recording whose app was closed before it ended
  - in the memo: the speaker heard on the microphone track is named as you; your own notes are kept
Run once from the project root: python logs/scripts/apply_live_0_10.py
"""
from pathlib import Path


def patch(path, edits):
    f = Path(path)
    s = f.read_text("utf-8")
    for a, b in edits:
        assert s.count(a) == 1, (path, s.count(a), a[:70])
        s = s.replace(a, b)
    f.write_text(s, "utf-8")


# live.py: a plainer way to choose the live model
f = Path("workers/mitra_workers/live.py")
s = f.read_text("utf-8")
a0, a1 = s.index("    cands = [c for c in models.catalog()"), s.index("def peak(wav: Path)")
s = s[:a0] + '''    cap = models.catalog()["transcription"]
    rt = models.runtime_path(cap["runtime"])
    budget = paths.config()["model_budget_mb"]
    for c in sorted(cap["candidates"], key=lambda c: c["est_mb"]):
        if "en-cpp" in c["id"] or "tiny" in c["id"] or c["est_mb"] > budget:
            continue                          # English-only and the tiny models cannot follow a mixed-language call
        found = models.find_model(c["id"])
        if found:
            return {"ready": bool(rt), "model": c["id"], "file": str(found), "est_mb": c["est_mb"], "runtime_path": rt, "args": c.get("args", [])}
    return {"ready": False, "hint": "No speech model for the live transcript is on this device."}


''' + s[a1:]
f.write_text(s, "utf-8")

LIVE_ROUTES = '''
# ---- a meeting as it happens -----------------------------------------------------------------
class _Shim:
    """What `run` needs of a request, for a recording that came from the recorder and not from the page."""
    def __init__(self, job, body):
        self.job, self._body = job, body

    def json(self):
        return self._body


def _memo_for(job, d: Path, title: str, attendees: str, req):
    files = live.assemble(d, title)
    notes_file = d / "notes.md"
    body = {"path": files["mix"], "name": (title or "Meeting") + " (recorded live)", "title": title, "attendees": attendees, "speed": "accurate",
            "tracks": {"mic": files["mic"], "sys": files["sys"]}, "my_notes": notes_file.read_text("utf-8") if notes_file.is_file() else ""}
    shim = _Shim(job, body)
    out = run(shim)
    req.job = shim.job
    return out


def live_job(req):
    """Record a meeting until it is stopped, with a transcript that grows as it goes; then write the memo."""
    b = req.json()
    if live.current():
        return {"already": True}
    live.tidy()
    title, attendees = (b.get("title") or "").strip(), (b.get("attendees") or "").strip()
    rec = live.record("twinmind", req.job, title, attendees)
    d = Path(rec["dir"])
    meta = json.loads((d / "meeting.json").read_text("utf-8"))        # the title may have been typed during the meeting
    if rec["seconds"] < 5:
        return {"recorded": False, "why": "The recording was stopped before anything was captured."}
    return _memo_for(req.job, d, meta.get("title") or title, meta.get("attendees") or attendees, req)


def live_finish(req):
    """Write the memo for a recording that ended without one (the app was closed during the meeting)."""
    rid = re.sub(r"[^0-9\\-]", "", str(req.json().get("id") or ""))
    d = live.LIVE / rid
    if not rid or not d.is_dir() or (live.current() or {}).get("id") == rid:
        raise ValueError("No such recording.")
    meta = json.loads((d / "meeting.json").read_text("utf-8"))
    return _memo_for(req.job, d, meta.get("title") or "", meta.get("attendees") or "", req)


def live_state(req):
    """Is a meeting being recorded, how far along, and the new lines of its transcript."""
    cur = live.current()
    out = {"recording": cur, "owner": live.owner(), "model": live.live_model().get("model"), "leftover": live.unassembled(),
           "recorder": Path(live.EAR).is_file()}
    if cur:
        out.update(live.tail(cur["id"], int(req.q("after") or 0)))
    return out


def live_stop(req):
    cur = live.current()
    if not cur:
        return {"stopped": False}
    (Path(cur["dir"]) / "stop").write_text("", "utf-8")
    memory.log("twinmind", "live.stop", {"id": cur["id"]})
    return {"stopped": True}


def live_notes(req):
    """What you type during the meeting, and its title: kept beside the recording and put in the memo."""
    cur, b = live.current(), req.json()
    if not cur:
        return {"saved": False}
    d = Path(cur["dir"])
    if "notes" in b:
        (d / "notes.md").write_text(str(b["notes"])[:20000], "utf-8")
    if "title" in b or "attendees" in b:
        meta = json.loads((d / "meeting.json").read_text("utf-8"))
        meta.update({k: str(b[k]).strip()[:200] for k in ("title", "attendees") if k in b})
        (d / "meeting.json").write_text(json.dumps(meta, ensure_ascii=False), "utf-8")
    return {"saved": True}


'''

f = Path("apps/twinmind/worker.py")
s = f.read_text("utf-8")
for a, b in [
    ("from mitra_workers import convert, gist, library, meeting, memory, models, paths, work\n",
     "from mitra_workers import convert, gist, library, live, meeting, memory, models, paths, work\n"),
    ("def _memo(path: str) -> Path:", LIVE_ROUTES.lstrip("\n") + "def _memo(path: str) -> Path:"),
    ('          ("GET", "people"): people, ("POST", "people"): set_people, ("GET", "across"): across}',
     '          ("GET", "people"): people, ("POST", "people"): set_people, ("GET", "across"): across,\n'
     '          ("POST", "job/live"): live_job, ("POST", "job/live-finish"): live_finish, ("GET", "live"): live_state,\n'
     '          ("POST", "live/stop"): live_stop, ("POST", "live/notes"): live_notes}'),
    # an item from the recorder carries its two tracks and the notes typed during the meeting
    ('            "fresh": bool(b.get("fresh")), "added": time.time()}',
     '            "fresh": bool(b.get("fresh")), "added": time.time(),\n'
     '            **({"tracks": b["tracks"]} if isinstance(b.get("tracks"), dict) else {}), **({"my_notes": str(b["my_notes"])} if b.get("my_notes") else {})}'),
    # the voice on the microphone track is the person at this computer
    ("            who = len({t[\"speaker\"] for t in turns})\n",
     "            if item.get(\"tracks\"):\n"
     "                mine = live.owner_speaker(turns, Path(item[\"tracks\"][\"mic\"]), Path(item[\"tracks\"][\"sys\"]))\n"
     "                if mine:\n"
     "                    me = live.owner()\n"
     "                    for t in turns:\n"
     "                        if t[\"speaker\"] == mine:\n"
     "                            t[\"speaker\"] = me\n"
     "            who = len({t[\"speaker\"] for t in turns})\n"),
    ("    md += [\"\", f\"## {H_POINTS}\", \"\"]\n",
     "    if item.get(\"my_notes\", \"\").strip():\n"
     "        md += [\"\", \"## Your notes\", \"\", item[\"my_notes\"].strip(), \"\", \"_Typed by you during the meeting, kept as written._\"]\n"
     "    md += [\"\", f\"## {H_POINTS}\", \"\"]\n"),
]:
    assert s.count(a) == 1, (s.count(a), a[:70])
    s = s.replace(a, b)
f.write_text(s, "utf-8")

# the recorder is built and installed with the rest
patch("build.ps1", [(
    "Push-Location \"$root\\gateway\"",
    "Push-Location \"$root\\ear\"\ncargo build --release\nCopy-Item \"target\\release\\mitra-ear.exe\" \"$root\\bin\\\" -Force     # records the microphone and system audio as two tracks\nPop-Location\n\nPush-Location \"$root\\gateway\"")])
patch("build.sh", [(
    '(cd "$root/gateway" && go build',
    '(cd "$root/ear" && cargo build --release && cp target/release/mitra-ear "$root/bin/") || echo "mitra-ear was not built: live recording will be unavailable on this system"\n(cd "$root/gateway" && go build')])
g = Path(".gitignore")
g.write_text(g.read_text("utf-8").replace("governor/target/\n", "governor/target/\near/target/\n"), "utf-8")
print("ok")
