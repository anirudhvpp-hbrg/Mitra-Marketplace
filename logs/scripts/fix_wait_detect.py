"""The assistant counts as waiting until its own governor holds the model lock (a ticket can be
written a moment after the process starts, so looking for the ticket missed short waits).
Also: tests treat a job that is still 'starting' as live. Run once from the project root."""
from pathlib import Path
f = Path("workers/mitra_workers/models.py"); s = f.read_text("utf-8")
a = "                if _in_line(self.proc.pid):\n                    time.sleep(0.3)\n                    continue\n"
b = "                if not _holds_model(self.proc.pid):\n                    time.sleep(0.2)\n                    continue\n"
assert s.count(a) == 1; s = s.replace(a, b)
a0 = s.index("def _in_line(pid: int) -> bool:"); a1 = s.index("def _run_model(")
s = s[:a0] + '''def _holds_model(pid: int) -> bool:
    """True once the governor with this pid has the model lock (until then it is waiting its turn)."""
    try:
        return json.loads((paths.HOME / "run" / "model.lock").read_text("utf-8")).get("governor_pid") == pid
    except (OSError, ValueError):
        return False


''' + s[a1:]
f.write_text(s, "utf-8")
for p in ("logs/tests/run_tests.py", "logs/scripts/area_o_block.py"):
    f = Path(p); s = f.read_text("utf-8")
    a = '''[0] >= 1 or j["status"] != "running" else None)(http("GET", "/api/jobs/" + r["id"], base=tm)[1]), 240, 1)'''
    assert s.count(a) == 1
    s = s.replace(a, '''[0] >= 1 or j["status"] not in ("running", "starting") else None)(http("GET", "/api/jobs/" + r["id"], base=tm)[1]), 240, 1)''')
    a = '''job = _until(lambda: (lambda j: j if j["status"] != "running" else None)(http("GET", "/api/jobs/" + r["id"], base=tm)[1]), 900, 2)'''
    assert s.count(a) == 1
    s = s.replace(a, '''job = _until(lambda: (lambda j: j if j["status"] not in ("running", "starting") else None)(http("GET", "/api/jobs/" + r["id"], base=tm)[1]), 900, 2)''')
    f.write_text(s, "utf-8")
print("ok")
