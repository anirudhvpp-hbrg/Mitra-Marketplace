"""A long real recording through the running apps, used the way a person would on a busy day.

    python logs/scripts/long_call_run.py "<long recording>" "<short recording>" [--doc "<a document>"]

While the long recording is being written up (Accurate), this script:
  - adds the short recording to the line (Fast);
  - asks Ask Mitra a question during each model stage (speakers, speech, notes) and times the wait;
  - converts a document in Anything to MD during the job (no model);
  - pauses the job once and resumes it, then stops it hard once and resumes it;
  - follows the line to the second recording.
It then reports times, every model's peak memory against its cap, waits and yields from the memory
log, and the shape of both memos. No words of the recordings are printed.
"""
import json
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

HOME = Path.home() / ".mitra"
T0 = time.time()


def say(*a):
    print(f"[{(time.time() - T0) / 60:6.1f} min]", *a, flush=True)


def call(url, body=None, timeout=900):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"} if body is not None else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def app_url(app: str) -> str:
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


def events(since: str):
    out = []
    for f in sorted((HOME / "memory" / "events").glob("*.jsonl"))[-3:]:
        for l in f.read_text("utf-8", errors="replace").splitlines():
            try:
                e = json.loads(l)
            except ValueError:
                continue
            if e.get("ts", "") >= since:
                out.append(e)
    return out


def model_processes() -> int:
    ps = "(Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'llama-server|whisper-cli|audiocpp_cli' }).Count"
    return int((subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout.strip() or "0"))


def main():
    long_src, short_src = sys.argv[1], sys.argv[2]
    doc = sys.argv[sys.argv.index("--doc") + 1] if "--doc" in sys.argv else None
    since = time.strftime("%Y-%m-%dT%H:%M:%S")
    tm, am = app_url("twinmind"), app_url("assistant")
    api = lambda name, body=None: call(f"{tm}/api/apps/twinmind/{name}", body)   # noqa: E731
    est = api("estimate?path=" + urllib.parse.quote(long_src, safe=""))
    say(f"long recording: {est['seconds'] / 60:.0f} min of audio; estimate accurate {est['accurate']['seconds'] / 60:.0f} min "
        f"({est['accurate']['windows']} windows, {est['accurate']['pieces']} pieces, ~{est['accurate']['sections']} sections), "
        f"fast {est['fast']['seconds'] / 60:.0f} min; measured rates: {est['accurate']['measured']}")
    if "--attach" in sys.argv:       # the job is already running (this script was restarted): follow it
        job = api("state")["running"]["job"]
    elif "--resume" in sys.argv:     # pick the long recording up from its saved pieces, then line the short one up again
        u = [x for x in api("state")["unfinished"] if x["name"] == Path(long_src).name]
        say(f"resuming: {u[0]['progress']} kept, state {u[0]['state']}")
        job = api("job/run", u[0]["item"])["id"]
        time.sleep(3)
        api("job/run", {"path": short_src, "speed": "fast"})
        time.sleep(3)
    else:
        job = api("job/run", {"path": long_src, "speed": "accurate"})["id"]
        time.sleep(3)
        api("job/run", {"path": short_src, "speed": "fast"})
        time.sleep(3)
    st = api("state")
    say(f"second recording queued: line has {len(st['line'])}; running job {st['running'] and st['running']['job']}")

    asked, answers, done_marks = set(), [], set()

    def ask(tag):
        def go():
            t = time.time()
            try:
                # an app with no window open ends itself after a while, so find (or start) it at the time of asking
                r = call(f"{app_url('assistant')}/api/ask", {"app_id": "assistant", "prompt": "In one sentence, what is a meeting agenda for?"})
                answers.append((tag, round(time.time() - t), round(r.get("waited_ms", 0) / 1000), r.get("mb"), bool(r.get("text"))))
                say(f"Ask Mitra during {tag}: answered in {time.time() - t:.0f} s (waited {r.get('waited_ms', 0) / 1000:.0f} s for a turn, {r.get('mb')} MB)")
            except Exception as e:
                answers.append((tag, round(time.time() - t), None, None, False))
                say(f"Ask Mitra during {tag}: FAILED after {time.time() - t:.0f} s: {e}")
        threading.Thread(target=go, daemon=True).start()

    def once(mark):
        if mark in done_marks:
            return False
        done_marks.add(mark)
        return True

    def resume(why):
        u = api("state")["unfinished"]
        say(f"{why}: unfinished shows {[(x['name'][:12], x['state'], x['progress']) for x in u]}; model processes alive: {model_processes()}")
        if not u:
            raise SystemExit("nothing to resume")
        return api("job/run", u[0]["item"])["id"]

    memos, last, order = [], "", ["diarize", "transcribe", "understand"]
    while True:
        try:
            j = call(f"{tm}/api/jobs/{job}", timeout=30)
        except Exception as e:
            say("poll failed:", e)
            time.sleep(5)
            continue
        prog = j.get("progress") or {}
        line = f"{j['status']} " + " ".join(f"{k}={prog[k][0]}/{prog[k][1]}" for k in order if k in prog) + (f" eta {j['eta_s'] / 60:.0f} min" if j.get("eta_s") else "")
        if line != last:
            last = line
            say(line)
        name = (j.get("item") or {}).get("name", "")
        first = name == Path(long_src).name
        d, tr, un = (prog.get(k, [0, 0])[0] for k in order)
        if first and j["status"] == "running":
            if d >= 3 and not tr and once("ask-d"):
                ask("who speaks when")
            if d >= 4 and not tr and doc and once("doc"):
                t = time.time()
                try:
                    r = call(f"{app_url('to-markdown')}/api/convert?path=" + urllib.parse.quote(doc, safe=""))
                    say(f"Anything to MD converted a document in {time.time() - t:.1f} s ({len(r['markdown'])} chars) while the job ran")
                except Exception as e:
                    say("convert FAILED:", e)
            if d >= 6 and not tr and once("pause"):
                api("pause", {})
                say("pause requested")
            if tr >= 2 and once("ask-t"):
                ask("what was said")
            if tr >= 4 and once("stop"):
                time.sleep(20)                       # part way through a piece
                api("stop", {})
                say("stop requested, mid-piece")
                time.sleep(6)
                job = resume("after stop")
                continue
            if un >= 3 and once("ask-n"):
                ask("notes")
        if j["status"] == "paused":
            time.sleep(5)
            job = resume("after pause")
            continue
        if j["status"] in ("done", "failed", "stopped"):
            if j["status"] == "done" and (j.get("result") or {}).get("path"):
                memos.append((name, j["result"], j.get("seconds"), j.get("steps")))
                say(f"memo written for {name[:14]}: job took {j.get('seconds')} s; resumed={j['result'].get('resumed')} yields={j['result'].get('yields')}")
            elif j["status"] != "done":
                say(f"job ended {j['status']}: {j.get('error')}")
            if j.get("next"):
                job = j["next"]
                continue
            break
        time.sleep(2)
    time.sleep(3)

    ev = events(since)
    print("\n== result ==")
    print(f"wall time {(time.time() - T0) / 60:.1f} min; line now {len(api('state')['line'])}; unfinished {len(api('state')['unfinished'])}; model processes alive {model_processes()}")
    for name, res, secs, steps in memos:
        print(f"\n{name[:14]}…  job seconds {secs}")
        for s in steps or []:
            print(f"  {s['stage']:<11} {s['status']:<8} {(s.get('note') or '')[:200]}")
        text = Path(res["path"]).read_text("utf-8")
        tr = text.split("Appendix: Transcript", 1)[-1]
        stamps = re.findall(r"^\[(\d\d:\d\d:\d\d)\]", tr, re.M)
        who = {}
        for m in re.finditer(r"^\[[\d:]+\] ([^:]{1,30}):", tr, re.M):
            who[m.group(1)] = who.get(m.group(1), 0) + 1
        print(f"  memo {Path(res['path']).name} ({len(text)} chars); transcript lines {len(stamps)}, last at {stamps[-1] if stamps else '-'}; speakers {who}")
        for h in re.findall(r"^## .*$", text, re.M):
            body = text.split(h, 1)[1].split("\n## ", 1)[0]
            print(f"    {h[:50]:<52} {len([x for x in body.splitlines() if x.strip()])} lines")
    runs = [e for e in ev if e["type"] == "model.run"]
    by = {}
    for e in runs:
        d = e["data"]
        b = by.setdefault((e["app"], d["name"]), {"n": 0, "peak": 0, "cap": 0, "s": 0, "ends": {}})
        b["n"] += 1
        b["peak"], b["cap"], b["s"] = max(b["peak"], d.get("peak_mb", 0)), max(b["cap"], d.get("budget_mb", 0)), b["s"] + d.get("ms", 0) / 1000
        b["ends"][d.get("end")] = b["ends"].get(d.get("end"), 0) + 1
    print("\nmodels:")
    for (a, n), b in by.items():
        print(f"  {a:<10} {n:<34} runs {b['n']:>3}  peak {b['peak']:>4} MB  cap {b['cap']:>4} MB  {b['s'] / 60:6.1f} min  ends {b['ends']}")
    spans = sorted((time.mktime(time.strptime(e["ts"], "%Y-%m-%dT%H:%M:%S")) - e["data"].get("ms", 0) / 1000, time.mktime(time.strptime(e["ts"], "%Y-%m-%dT%H:%M:%S"))) for e in runs)
    overlaps = sum(1 for (s1, e1), (s2, e2) in zip(spans, spans[1:]) if e1 > s2 + 1.5)
    count = lambda t: len([e for e in ev if e["type"] == t])   # noqa: E731
    print(f"\ntwo models at once: {overlaps} times; over-cap stops {count('governor.evict')}; cap raised {count('model.cap_raised')}; refused {count('governor.denied')}; "
          f"stepped down {count('model.fallback')}; waited in line {count('model.wait')}; stepped aside {count('model.yield')}; "
          f"queued {count('job.queued')}; paused {count('job.paused')}; stopped {count('job.stopped')}; resumed {count('job.resumed')}; errors {count('error')}")
    for e in ev:
        if e["type"] == "error":
            print("  error:", str(e["data"].get("msg"))[:200])
    print("questions:", answers)
    print("DONE")


main()
