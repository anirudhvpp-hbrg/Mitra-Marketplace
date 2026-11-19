"""Run a real file through the running TwinMind app, the way its page does, and report.

    python logs/scripts/twinmind_real_run.py "<recording or transcript>" [--attendees "A, B"] [--show]

Starts TwinMind through the launcher if it is not running, posts the job, follows the steps, then
prints each stage, the memory every model used (from the memory log), and the memo's shape
(section names, counts). The memo's words are printed only with --show.
"""
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HOME = Path.home() / ".mitra"


def get(url, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"} if body is not None else {})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def app_url() -> str:
    for _ in range(2):
        out = subprocess.run(["mitra-marketplace", "apps"], capture_output=True, text=True).stdout
        m = re.search(r"twinmind\s+pid \d+\s+(http://\S+?)/apps/twinmind/", out)
        if m:
            return m.group(1)
        subprocess.run(["mitra-marketplace", "open", "twinmind"], capture_output=True, text=True)
        time.sleep(2)
    raise SystemExit("TwinMind did not start")


def main():
    src = sys.argv[1]
    att = sys.argv[sys.argv.index("--attendees") + 1] if "--attendees" in sys.argv else ""
    base = app_url()
    t0 = time.time()
    since = time.strftime("%Y-%m-%dT%H:%M:%S")
    job = get(f"{base}/api/apps/twinmind/job/run", {"path": src, "title": "", "attendees": att})
    seen = ""
    while True:
        j = get(f"{base}/api/jobs/{job['id']}")
        line = " / ".join(f"{s['stage']}:{s['status']}" for s in j["steps"])
        if line != seen:
            seen = line
            print(f"[{time.time() - t0:5.0f}s] {line}", flush=True)
        if j["status"] in ("done", "failed"):
            break
        time.sleep(1)
    print("status:", j["status"], "in", round(time.time() - t0), "s")
    if j["status"] == "failed":
        print("error:", j.get("error"))
    for s in j["steps"]:
        print(f"  {s['stage']:<11} {s['status']:<8} {(s.get('note') or '')[:170]}")
    print("models (from the memory log):")
    for f in sorted((HOME / "memory" / "events").glob("*.jsonl"))[-2:]:
        for l in f.read_text("utf-8", errors="replace").splitlines():
            if '"twinmind"' in l and ('"model.run"' in l or '"model.cap_raised"' in l or '"governor.evict"' in l):
                e = json.loads(l)
                if e["ts"] >= since:
                    d = e["data"]
                    print(f"  {e['type']:<17} {d.get('name') or d.get('model')}: peak {d.get('peak_mb', d.get('mb'))} MB, "
                          f"cap {d.get('budget_mb', d.get('ceiling_mb'))} MB, {d.get('end', d.get('why', ''))}")
    if j["status"] == "done":
        memo = Path(j["result"]["path"])
        text = memo.read_text("utf-8")
        print("memo:", memo.name, f"({len(text)} chars)")
        for h in re.findall(r"^##+ .*$", text, re.M):
            body = text.split(h, 1)[1].split("\n## ", 1)[0]
            print(f"  {h[:60]:<62} {len([x for x in body.splitlines() if x.strip()])} lines")
        tr = text.split("Appendix: Transcript", 1)[-1]
        who = sorted(set(re.findall(r"^\[[\d:]+\] ([^:]{1,30}):", tr, re.M)))
        print("  transcript lines:", len([x for x in tr.splitlines() if x.startswith("[")]), "| speakers:", who)
        if "--show" in sys.argv:
            print(text)


main()
