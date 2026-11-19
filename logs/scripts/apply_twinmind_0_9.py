"""0.9.0: splice the resumable, queued job code (twinmind_run_0_9.py.txt) into apps/twinmind/worker.py,
teach dispatch and Job about paused jobs, and add models.audio_seconds.
Run once from the project root: python logs/scripts/apply_twinmind_0_9.py
"""
from pathlib import Path

root = Path(".")


def patch(path, edits):
    f = root / path
    s = f.read_text("utf-8")
    for a, b in edits:
        assert s.count(a) == 1, (path, s.count(a), a[:70])
        s = s.replace(a, b)
    f.write_text(s, "utf-8")


# ---- apps/twinmind/worker.py
f = root / "apps/twinmind/worker.py"
s = f.read_text("utf-8")
a0 = s.index("def run(req):")
a1 = s.index('    job.step("write", "running")\n') + len('    job.step("write", "running")\n')
s = s[:a0] + (root / "logs/scripts/twinmind_run_0_9.py.txt").read_text("utf-8") + s[a1:]
for a, b in [
    ("import re\nfrom datetime import datetime\nfrom pathlib import Path\n\nfrom mitra_workers import convert, gist, meeting, memory, models, paths\n",
     "import json\nimport os\nimport re\nimport shutil\nimport signal\nimport time\nimport traceback\nfrom datetime import datetime\nfrom pathlib import Path\n\n"
     "from mitra_workers import convert, gist, meeting, memory, models, paths, work\n"),
    ('    return {"path": str(out), "stages": stages, "title": title}\n',
     '    w.finish()     # the memo is written: the saved pieces and the prepared audio are no longer needed\n'
     '    return {"path": str(out), "stages": stages, "title": title, "resumed": w.resumed, "yields": yields}\n'),
    ('ROUTES = {("GET", "status"): status, ("GET", "meetings"): meetings, ("GET", "search"): search, ("POST", "job/run"): run,\n'
     '          ("GET", "speakers"): speakers, ("POST", "speakers"): name_speakers}',
     'ROUTES = {("GET", "status"): status, ("GET", "meetings"): meetings, ("GET", "search"): search, ("POST", "job/run"): run,\n'
     '          ("GET", "speakers"): speakers, ("POST", "speakers"): name_speakers, ("GET", "estimate"): estimate, ("GET", "state"): state,\n'
     '          ("POST", "line"): set_line, ("POST", "pause"): pause, ("POST", "stop"): stop, ("POST", "discard"): discard}'),
    ("  understand  the meeting-notes model, section by section: points, decisions, open questions,\n",
     "  understand  the meeting-notes model, section by section: points, decisions, open questions,\n"),
]:
    assert s.count(a) == 1, (s.count(a), a[:70])
    s = s.replace(a, b)
s = s.replace('A stage that cannot run is recorded as skipped in the memo, never silently dropped.',
              'Every finished window, piece and section is saved (mitra_workers.work), so a job that stops picks up\n'
              'where it was; recordings wait in a line and run one at a time; the notes model steps aside between\n'
              'sections when another app is waiting. A stage that cannot run is recorded as skipped in the memo, never silently dropped.')
f.write_text(s, "utf-8")

# ---- dispatch: a job the route closed itself (paused) is not finished again
patch("workers/mitra_workers/dispatch.py", [(
    "        try:\n            req.job.finish(result=fn(req))\n        except Exception as e:\n"
    "            memory.log(a.id, \"error\", {\"msg\": str(e), \"trace\": traceback.format_exc()[-800:]})\n"
    "            req.job.finish(error=str(e))\n        return {\"id\": req.job_id}",
    "        try:\n            result = fn(req)            # a route may move on to another job (req.job) or close one itself (paused)\n"
    "            if req.job.state[\"status\"] == \"running\":\n                req.job.finish(result=result)\n        except Exception as e:\n"
    "            memory.log(a.id, \"error\", {\"msg\": str(e), \"trace\": traceback.format_exc()[-800:]})\n"
    "            req.job.finish(error=str(e))\n        return {\"id\": req.job_id}")])

# ---- work.note: the caller's fields win
patch("workers/mitra_workers/work.py", [(
    "        self.meta.update(fields, pid=os.getpid(), touched=time.time())",
    "        self.meta.update({\"pid\": os.getpid(), \"touched\": time.time(), **fields})")])

# ---- models.audio_seconds
patch("workers/mitra_workers/models.py", [(
    "def _quiet_point(src, around: float, span: float = 4.0) -> float:",
    '''def audio_seconds(audio: Path) -> float | None:
    """How long a recording is, without converting it: the WAV header, or what ffmpeg reports."""
    try:
        if audio.suffix.lower() == ".wav":
            return wav_seconds(audio)
    except Exception:
        pass
    cfg_ff = paths.config().get("ffmpeg")
    ffmpeg = cfg_ff if cfg_ff and Path(cfg_ff).exists() else shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    r = subprocess.run([ffmpeg, "-hide_banner", "-i", str(audio)], capture_output=True, text=True, errors="replace", creationflags=_NOWIN)
    m = re.search(r"Duration:\\s*(\\d+):(\\d+):(\\d+(?:\\.\\d+)?)", r.stderr or "")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None


def _quiet_point(src, around: float, span: float = 4.0) -> float:''')])
print("ok")
