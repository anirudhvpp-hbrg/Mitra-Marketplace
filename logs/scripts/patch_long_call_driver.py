"""long_call_run.py: start apps as windowless processes (no window appears on screen), and add
--resume, which picks the long recording up from its saved pieces. Run once from the project root."""
from pathlib import Path
f = Path("logs/scripts/long_call_run.py"); s = f.read_text("utf-8")
a0 = s.index("def app_url(app: str) -> str:"); a1 = s.index("def events(since: str):")
s = s[:a0] + '''def app_url(app: str) -> str:
    """The address of an app's own process, started without a window if it is not running."""
    exe = Path(__file__).resolve().parents[2] / "bin" / "mitra-marketplace.exe"
    info = HOME / "run" / "apps" / f"{app}.json"
    for attempt in range(20):
        try:
            url = f"http://127.0.0.1:{json.loads(info.read_text('utf-8'))['port']}"
            call(url + "/api/ping", timeout=3)
            return url
        except Exception:
            if attempt == 0:
                subprocess.Popen([str(exe), "app", app], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(0.5)
    raise SystemExit(f"{app} did not start")


''' + s[a1:]
a = '''    if "--attach" in sys.argv:       # the job is already running (this script was restarted): follow it
        job = api("state")["running"]["job"]
'''
b = '''    if "--attach" in sys.argv:       # the job is already running (this script was restarted): follow it
        job = api("state")["running"]["job"]
    elif "--resume" in sys.argv:     # pick the long recording up from its saved pieces, then line the short one up again
        u = [x for x in api("state")["unfinished"] if x["name"] == Path(long_src).name]
        say(f"resuming: {u[0]['progress']} kept, state {u[0]['state']}")
        job = api("job/run", u[0]["item"])["id"]
        time.sleep(3)
        api("job/run", {"path": short_src, "speed": "fast"})
        time.sleep(3)
'''
assert s.count(a) == 1; s = s.replace(a, b)
f.write_text(s, "utf-8"); print("ok")
