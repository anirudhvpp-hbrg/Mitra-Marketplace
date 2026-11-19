"""Put an unfinished TwinMind job back to work through the running app: it resumes at once, or joins
the line if a recording is being written up. Then follow jobs until nothing is running, and say
which memos were written.   python logs/scripts/queue_unfinished.py "<part of the recording's name>" """
import json, sys, time, urllib.request
from pathlib import Path
HOME = Path.home() / ".mitra"
base = f"http://127.0.0.1:{json.loads((HOME / 'run' / 'apps' / 'twinmind.json').read_text('utf-8'))['port']}"
def call(path, body=None):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"} if body is not None else {})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())
st = call("/api/apps/twinmind/state")
u = [x for x in st["unfinished"] if sys.argv[1] in x["name"]]
print("unfinished:", [(x["name"][:14], x["state"], x["progress"]) for x in st["unfinished"]], "| running:", bool(st["running"]), flush=True)
jid = call("/api/apps/twinmind/job/run", u[0]["item"])["id"]
time.sleep(3)
print("line:", [l["name"][:14] for l in call("/api/apps/twinmind/state")["line"]], flush=True)
seen = set()
while True:
    st = call("/api/apps/twinmind/state")
    if st["running"] and st["running"]["job"] not in seen:
        seen.add(st["running"]["job"]); print("now running job", st["running"]["job"], flush=True)
    if not st["running"] and not st["line"]:
        break
    time.sleep(5)
for j in seen:
    d = call("/api/jobs/" + j)
    print("job", j, d["status"], (d.get("item") or {}).get("name", "")[:14], d.get("progress"), "seconds", d.get("seconds"),
          "| memo:", Path((d.get("result") or {}).get("path", "-")).name, "| resumed", (d.get("result") or {}).get("resumed"), flush=True)
print("unfinished now:", [(x["name"][:14], x["state"]) for x in call("/api/apps/twinmind/state")["unfinished"]])
print("DONE")
