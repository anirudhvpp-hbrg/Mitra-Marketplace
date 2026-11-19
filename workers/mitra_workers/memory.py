"""Native memory log.

Every app open, action, file, model run, refusal, eviction and error is one JSON line in
~/.mitra/memory/events/YYYY-MM-DD.jsonl. Three writers append to it: the Go gateway (browser
events), the Rust governor (model runs) and these workers. `report()` turns a period into
usage patterns and suggestions; `prune()` rolls old days into per-day counts and archives
the raw lines.
"""
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import PureWindowsPath   # reads both C:\a\b and /a/b

from . import paths

SYSTEM_TYPES = ("api.", "manager.", "model.", "governor.", "job.", "server.")


def _events_dir():
    return paths.HOME / "memory" / "events"


def log(app: str, type: str, data: dict | None = None):
    rec = {"ts": datetime.now().isoformat(timespec="seconds"), "app": app, "type": type}
    if data:
        rec["data"] = data
    d = _events_dir()
    d.mkdir(parents=True, exist_ok=True)
    with open(d / f"{date.today().isoformat()}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


def read(days: int):
    """Yield events from the last `days` days, oldest first."""
    start = date.today() - timedelta(days=days - 1)
    for f in sorted(_events_dir().glob("*.jsonl")):
        try:
            if date.fromisoformat(f.stem) < start:
                continue
        except ValueError:
            continue
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    yield json.loads(line)
                except Exception:
                    continue


def usage_counts(days: int = 30) -> dict:
    c = Counter()
    for e in read(days):
        if e["type"] == "app.open":
            c[e["app"]] += 1
    return dict(c)


def recent_files(app: str, days: int = 30, limit: int = 12) -> list[str]:
    seen = {}
    for e in read(days):
        if e["app"] == app and e["type"] == "file.open":
            p = (e.get("data") or {}).get("path")
            if p:
                seen.pop(p, None)
                seen[p] = True
    return list(reversed(list(seen)))[:limit]


def _new_stats():
    return {"opens": 0, "active_min": 0.0, "actions": Counter(), "errors": Counter(), "evictions": 0, "denied": 0,
            "requests": 0, "worker_peak_mb": 0, "worker_ms": 0,
            "model_calls": defaultdict(lambda: {"n": 0, "ms": 0, "peak_mb": 0}), "last_used": None}


def _add(s: dict, e: dict):
    d, t = e.get("data") or {}, e["type"]
    if t == "app.open":
        s["opens"] += 1
        s["last_used"] = e["ts"]
    elif t == "app.close":
        s["active_min"] += d.get("active_ms", 0) / 60000
    elif t == "error":
        s["errors"][str(d.get("msg", "unknown"))[:120]] += 1
    elif t == "model.run":
        m = s["model_calls"][d.get("name", "?")]
        m["n"] += 1
        m["ms"] += d.get("ms", 0)
        m["peak_mb"] = max(m["peak_mb"], d.get("peak_mb", 0))
        # "over" means over the cap that run was given, not near the global ceiling: a model that
        # is meant to use 750 of 800 MB is working as designed.
        if d.get("budget_mb") and d.get("peak_mb", 0) > d["budget_mb"]:
            m["over"] = m.get("over", 0) + 1
    elif t == "governor.denied":
        s["denied"] += 1
    elif t == "api.call":
        s["requests"] += 1
        s["worker_peak_mb"] = max(s["worker_peak_mb"], d.get("worker_mb", 0) or 0)
        s["worker_ms"] += d.get("ms", 0)
    elif not t.startswith(SYSTEM_TYPES):
        s["actions"][t] += 1


def _finish(s: dict) -> dict:
    s["active_min"] = round(s["active_min"], 1)
    s["actions"] = dict(s["actions"].most_common(10))
    s["errors"] = dict(s["errors"].most_common(5))
    s["model_calls"] = {k: {**v, "avg_ms": round(v["ms"] / max(v["n"], 1))} for k, v in s["model_calls"].items()}
    return s


def app_stats(app: str, days: int = 7) -> dict:
    s = _new_stats()
    for e in read(days):
        if e["type"] == "governor.evict" and app in ((e.get("data") or {}).get("apps") or []):
            s["evictions"] += 1
        if e["app"] == app:
            _add(s, e)
    return _finish(s)


def report(days: int, installed: list[str], names: dict | None = None) -> dict:
    names = names or {}
    label = lambda a: names.get(a, a)   # noqa: E731  people read app names, not folder ids
    apps = {a: _new_stats() for a in installed}
    files, evictions, total, idle_exits, turns = Counter(), Counter(), 0, 0, Counter()
    for e in read(days):
        total += 1
        d = e.get("data") or {}
        if e["type"] == "file.open" and d.get("path"):
            files[d["path"]] += 1
        elif e["type"] == "governor.evict":
            evictions[f"{d.get('name', '?')} ({d.get('reason', '?')})"] += 1
            for a in d.get("apps") or []:
                if a in apps:
                    apps[a]["evictions"] += 1
        elif e["type"] == "server.idle_exit":
            idle_exits += 1
        elif e["type"] in ("model.wait", "model.yield", "job.queued", "job.resumed", "job.paused", "job.stopped"):
            turns[e["type"]] += 1
        if e["app"] in apps:
            _add(apps[e["app"]], e)
    apps = {a: _finish(s) for a, s in apps.items()}
    budget = paths.config()["model_budget_mb"]

    # A tip about a model this device no longer picks (one replaced since) is history, not advice.
    from . import models
    current = {models.pick(c).get("model") for c in models.catalog() if not c.startswith("_")}
    tips = []
    unused = [label(a) for a, s in apps.items() if s["opens"] == 0]
    if unused:
        tips.append(f"Not opened in {days} days: {', '.join(unused)}. Candidates to remove or rethink.")
    for a, s in apps.items():
        if sum(s["errors"].values()) >= 3:
            tips.append(f"{label(a)}: {sum(s['errors'].values())} errors. Most common: {next(iter(s['errors']))}")
        if s["denied"] >= 3:
            tips.append(f"{label(a)}: {s['denied']} model loads refused. Free RAM was short or two models were wanted at once.")
        for m, mc in s["model_calls"].items():
            if m not in current:
                continue
            if mc.get("over"):
                tips.append(f"{label(a)}: {m} went over its own RAM cap on {mc['over']} of {mc['n']} runs (peak {mc['peak_mb']} MB). Move to a lighter candidate in catalog.json.")
            if mc["n"] >= 3 and mc["avg_ms"] > 20000:
                tips.append(f"{label(a)}: {m} averages {mc['avg_ms'] // 1000} s per run.")
    for name, n in evictions.items():
        if n >= 3:
            tips.append(f"Stopped by the governor {n} times: {name}.")
    for p, n in files.most_common(3):
        if n >= 5:
            tips.append(f"Opened {n} times: {p}. Worth pinning.")

    return {"days": days, "generated": datetime.now().isoformat(timespec="seconds"), "events": total, "apps": apps, "names": names,
            "top_files": files.most_common(10), "evictions": dict(evictions), "idle_exits": idle_exits,
            "budget_mb": budget, "suggestions": tips,
            "turns": {"waited_for_model": turns["model.wait"], "stepped_aside": turns["model.yield"], "queued": turns["job.queued"],
                      "resumed": turns["job.resumed"], "paused": turns["job.paused"], "stopped": turns["job.stopped"]}}


def render(rep: dict) -> str:
    def when(ts):
        try:
            return datetime.fromisoformat(ts).strftime("%d %b, %H:%M")
        except (TypeError, ValueError):
            return "never"

    def plain(action):   # "action.meeting_processed" -> "meeting processed"
        return action.split(".", 1)[-1].replace("_", " ") if action.startswith("action.") else action.replace(".", " ").replace("_", " ")

    names = rep.get("names") or {}
    label = lambda a: names.get(a, a)   # noqa: E731
    idle = rep["idle_exits"]
    out = [f"# Mitra memory report: last {rep['days']} days", "",
           f"Written {when(rep['generated'])} from {rep['events']:,} logged events."
           + (f" The launcher closed itself after going unused {idle} time{'s' if idle != 1 else ''}." if idle else ""), "",
           "## Usage by app", "", "| App | Opens | Active min | Errors | Last used | Top actions |", "|---|---|---|---|---|---|"]
    # starting, opening and ending an app are counted under Opens; they are not things you did in it
    plumbing = ("app.", "file.open", "palette.")
    for a, s in sorted(rep["apps"].items(), key=lambda kv: -kv[1]["opens"]):
        acts = ", ".join([f"{plain(k)} ({v})" for k, v in s["actions"].items() if not k.startswith(plumbing)][:4]) or "-"
        out.append(f"| {label(a)} | {s['opens']} | {s['active_min']} | {sum(s['errors'].values())} | {when(s['last_used'])} | {acts} |")
    out += ["", "## RAM and time per app", "",
            "The server process stays at about 20 MB. Everything else exists only while a request runs.", "",
            "| App | Requests | Largest worker MB | Avg ms per request | Largest model MB |", "|---|---|---|---|---|"]
    for a, s in sorted(rep["apps"].items(), key=lambda kv: -kv[1]["requests"]):
        model_peak = max([mc["peak_mb"] for mc in s["model_calls"].values()] or [0])
        avg = round(s["worker_ms"] / s["requests"]) if s["requests"] else 0
        out.append(f"| {label(a)} | {s['requests']} | {s['worker_peak_mb'] or '-'} | {avg or '-'} | {model_peak or 'no model'} |")
    out += ["", f"## Model runs (ceiling {rep['budget_mb']} MB)", ""]
    rows = [(a, m, mc) for a, s in rep["apps"].items() for m, mc in s["model_calls"].items()]
    if rows:
        out += ["| App | Model | Runs | Avg seconds | Peak MB |", "|---|---|---|---|---|"]
        out += [f"| {label(a)} | {m} | {mc['n']} | {mc['avg_ms'] / 1000:.1f} | {mc['peak_mb']} |" for a, m, mc in rows]
    else:
        out.append("No model ran in this period.")
    if rep["evictions"]:
        out += ["", "Stopped by the governor: " + ", ".join(f"{k} x{v}" for k, v in rep["evictions"].items())]
    t = rep.get("turns") or {}
    if any(t.values()):
        out += ["", "## Taking turns", "",
                f"Waited in line for the model {t['waited_for_model']} times; a long job stepped aside for a question {t['stepped_aside']} times. "
                f"Recordings queued: {t['queued']}. Jobs resumed after a stop: {t['resumed']}; paused by you: {t['paused']}; stopped by you: {t['stopped']}."]
    out += ["", "## Most used files", ""]
    # the name first, the folder after it: a temporary or deep path should not hide which file it was
    out += [f"- {n}x **{PureWindowsPath(p).name}** in `{PureWindowsPath(p).parent}`" for p, n in rep["top_files"]] or ["None logged."]
    out += ["", "## Suggestions", ""]
    out += [f"- {t}" for t in rep["suggestions"]] or ["Nothing stands out for this period."]
    return "\n".join(out) + "\n"


def save_report(rep: dict) -> str:
    f = paths.HOME / "memory" / "reports" / f"{date.today().isoformat()}-{rep['days']}d.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(render(rep), "utf-8")
    return str(f)


def prune(keep_days: int = 90) -> dict:
    """Roll raw event files older than keep_days into daily counts; gzip the raw lines into archive/."""
    import gzip
    cutoff = date.today() - timedelta(days=keep_days)
    rolled = 0
    for f in sorted(_events_dir().glob("*.jsonl")):
        try:
            if date.fromisoformat(f.stem) >= cutoff:
                continue
        except ValueError:
            continue
        counts, raw = Counter(), f.read_bytes()
        for line in raw.decode("utf-8", "ignore").splitlines():
            try:
                e = json.loads(line)
                counts[f"{e['app']}|{e['type']}"] += 1
            except Exception:
                pass
        for sub in ("rollups", "archive"):
            (paths.HOME / "memory" / sub).mkdir(parents=True, exist_ok=True)
        (paths.HOME / "memory" / "rollups" / f"{f.stem}.json").write_text(json.dumps(counts), "utf-8")
        with gzip.open(paths.HOME / "memory" / "archive" / f"{f.stem}.jsonl.gz", "wb") as gz:
            gz.write(raw)
        f.unlink()
        rolled += 1
    log("shell", "memory.prune", {"keep_days": keep_days, "days_rolled": rolled})
    return {"days_rolled": rolled, "keep_days": keep_days}
