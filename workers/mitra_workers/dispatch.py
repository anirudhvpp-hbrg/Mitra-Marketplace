"""One request in, one answer out, then exit.

The Go gateway runs `python -m mitra_workers.dispatch` with a JSON request on stdin
({method, path, query, body, job}) and reads {"status": int, "body": ...} from stdout.
With `job` set, the gateway does not wait: progress goes to the job file instead.
"""
import json
import re
import sys
import time
import traceback
from pathlib import Path

from . import memory, models, paths, registry
from .jobs import Job


class _Lazy:
    """Import a module the first time it is used. A worker lives for one request, so it should
    load only what that request needs: converting a file must not pay for the app builder."""

    def __init__(self, name):
        self._name, self._mod = name, None

    def __getattr__(self, attr):
        if self._mod is None:
            import importlib
            self._mod = importlib.import_module(f"{__package__}.{self._name}")
        return getattr(self._mod, attr)


builder, convert, manager = _Lazy("builder"), _Lazy("convert"), _Lazy("manager")

ROUTES: list[tuple[str, re.Pattern, callable]] = []


class HTTPError(Exception):
    def __init__(self, status, detail):
        self.status, self.detail = status, detail


class Req:
    def __init__(self, raw: dict):
        self.method, self.path = raw["method"], raw["path"]
        self.query, self.body, self.job_id = raw.get("query") or {}, raw.get("body") or "", raw.get("job")
        self.args, self.job = {}, None

    def json(self) -> dict:
        try:
            return json.loads(self.body or "{}")
        except Exception:
            raise HTTPError(400, "Body must be JSON")

    def q(self, name, default=None, required=False):
        v = self.query.get(name, default)
        if required and v is None:
            raise HTTPError(400, f"Missing '{name}'")
        return v


def route(method, pattern):
    rx = re.compile("^" + re.sub(r"\{(\w+):path\}", r"(?P<\1>.*)", re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern)) + "$")
    def deco(fn):
        ROUTES.append((method, rx, fn))
        return fn
    return deco


_apps = None


def apps() -> dict:
    global _apps
    if _apps is None:
        _apps = registry.discover()
    return _apps


def app(app_id) -> registry.App:
    if app_id not in apps():
        raise HTTPError(404, f"No app '{app_id}'")
    return apps()[app_id]


def existing(path) -> Path:
    p = Path(path).expanduser()
    if not p.exists():
        raise HTTPError(404, f"Not found: {path}")
    return p.resolve()


# ---- apps -------------------------------------------------------------
@route("GET", "/api/apps")
def list_apps(req):
    use = memory.usage_counts(30)
    out = [{**a.public(), "opens_30d": use.get(a.id, 0)} for a in apps().values()]
    return sorted(out, key=lambda a: (-a["opens_30d"], a["name"].lower()))


@route("GET", "/api/apps/{app_id}")
def get_app(req):
    return app(req.args["app_id"]).public()


@route("DELETE", "/api/apps/{app_id}")
def remove_app(req):
    a = app(req.args["app_id"])
    if a.builtin:
        raise HTTPError(400, "Built-in apps cannot be removed.")
    trash = paths.HOME / "removed-apps" / f"{a.id}-{int(time.time())}"
    trash.parent.mkdir(parents=True, exist_ok=True)
    a.dir.rename(trash)  # moved aside, not deleted
    memory.log("shell", "app.remove", {"id": a.id, "moved_to": str(trash)})
    return {"moved_to": str(trash)}


@route("GET", "/api/apps/{app_id}/{name:path}")
@route("POST", "/api/apps/{app_id}/{name:path}")
def app_route(req):
    a = app(req.args["app_id"])
    fn = a.routes().get((req.method, req.args["name"]))
    if not fn:
        raise HTTPError(404, f"{a.id} has no {req.method} {req.args['name']}")
    if req.job_id:
        req.job = Job(req.job_id, a.id)
        try:
            result = fn(req)            # a route may move on to another job (req.job) or close one itself (paused)
            if req.job.state["status"] == "running":
                req.job.finish(result=result)
        except Exception as e:
            memory.log(a.id, "error", {"msg": str(e), "trace": traceback.format_exc()[-800:]})
            req.job.finish(error=str(e))
        return {"id": req.job_id}
    return fn(req)


# ---- memory / manager / models ---------------------------------------
@route("GET", "/api/memory/report")
def memory_report(req):
    rep = memory.report(max(1, min(int(req.q("days", 7)), 365)), list(apps()), {k: a.manifest.get("name", k) for k, a in apps().items()})
    return {"report": rep, "markdown": memory.render(rep), "saved": memory.save_report(rep) if req.q("save") else None}


@route("POST", "/api/memory/prune")
def memory_prune(req):
    return memory.prune(max(7, int(req.json().get("keep_days") or 90)))


@route("GET", "/api/recent/all")
def recent_all(req):
    """The last few files opened in any app, newest first, for the home screen's 'pick up where you left off'."""
    seen = {}
    for e in memory.read(14):
        p = (e.get("data") or {}).get("path")
        if e["type"] == "file.open" and p and e["app"] in apps():
            seen.pop(p, None)
            seen[p] = e["app"]
    out = []
    for p, a in reversed(list(seen.items())):
        if Path(p).is_file():
            m = apps()[a].manifest
            out.append({"app": a, "app_name": m.get("name", a), "glyph": m.get("glyph", "doc"), "path": p, "name": Path(p).name})
        if len(out) == 6:
            break
    return out


@route("GET", "/api/recent")
def recent(req):
    return [p for p in memory.recent_files(req.q("app_id", required=True)) if Path(p).exists()]


@route("GET", "/api/manager/{app_id}")
def manager_review(req):
    return manager.review(app(req.args["app_id"]))


@route("GET", "/api/models")
def model_catalog(req):
    cfg = paths.config()
    return {"models_dir": cfg["models_dir"], "finetuned_dir": cfg["finetuned_dir"], "budget_mb": cfg["model_budget_mb"],
            "capabilities": [models.pick(c) for c in models.catalog()]}


@route("POST", "/api/ask")
def ask(req):
    b = req.json()
    a = app(b.get("app_id"))
    if "assistant" not in a.manifest.get("needs", []):
        raise HTTPError(400, f"{a.id} does not declare the assistant capability in its manifest.")
    return models.ask(a.id, b.get("prompt", ""), b.get("system"), int(b.get("max_tokens") or 400), b.get("history"))


# ---- documents --------------------------------------------------------
@route("GET", "/api/convert")
def convert_path(req):
    p = existing(req.q("path", required=True))
    try:
        return {"markdown": convert.to_markdown(p), "name": p.name, "path": str(p), "dir": str(p.parent)}
    except Exception as e:
        raise HTTPError(422, f"Could not convert {p.name}: {e}")


@route("GET", "/api/convert/formats")
def convert_formats(req):
    return convert.SUPPORTED


@route("POST", "/api/convert/save")
def convert_save(req):
    b = req.json()
    src = Path(b["source"]) if b.get("source") else Path.home() / "Downloads" / Path(b.get("name") or "converted").name
    return {"saved": str(convert.save_markdown(src, b.get("markdown", "")))}


# ---- builder ----------------------------------------------------------
@route("POST", "/api/builder/draft")
def builder_draft(req):
    prompt = req.json().get("prompt", "")
    memory.log("shell", "builder.draft", {"prompt": prompt[:300]})
    return builder.draft(prompt)


@route("POST", "/api/builder/create")
def builder_create(req):
    try:
        folder = builder.create(req.json().get("manifest") or {}, set(apps()))
    except (ValueError, FileExistsError) as e:
        raise HTTPError(400, str(e))
    a = registry.App(Path(folder), False)
    memory.log("shell", "builder.create", {"id": a.id})
    return a.public()


def handle(raw: dict) -> tuple[int, object]:
    req = Req(raw)
    try:
        for method, rx, fn in ROUTES:
            m = rx.match(req.path) if method == req.method else None
            if m:
                req.args = m.groupdict()
                return 200, fn(req)
        return 404, {"detail": f"No route {req.method} {req.path}"}
    except HTTPError as e:
        return e.status, {"detail": e.detail}
    except models.MemoryDenied as e:
        return 507, {"detail": str(e)}
    except models.Stopped as e:
        return 409, {"detail": str(e)}
    except models.ModelUnavailable as e:
        return 503, {"detail": str(e)}
    except Exception as e:
        memory.log("shell", "error", {"msg": f"{type(e).__name__}: {e}", "path": req.path, "trace": traceback.format_exc()[-800:]})
        return 500, {"detail": f"{type(e).__name__}: {e}"}


def peak_mb() -> int:
    """The most RAM this worker process held, so every request's cost lands in the memory log."""
    try:
        if sys.platform == "win32":
            import ctypes

            class PMC(ctypes.Structure):
                _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong)] + \
                           [(n, ctypes.c_size_t) for n in ("peak", "wss", "a", "b", "c", "d", "e", "f")]
            k = ctypes.windll.kernel32
            k.GetCurrentProcess.restype = ctypes.c_void_p
            pmc = PMC()
            pmc.cb = ctypes.sizeof(PMC)
            k.K32GetProcessMemoryInfo(ctypes.c_void_p(k.GetCurrentProcess()), ctypes.byref(pmc), pmc.cb)
            return pmc.peak // (1024 * 1024)
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return peak // (1024 * 1024) if sys.platform == "darwin" else peak // 1024
    except Exception:
        return 0


def main():
    raw = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    real_out, sys.stdout = sys.stdout, sys.stderr  # stray prints must not corrupt the answer
    status, body = handle(raw)
    real_out.buffer.write(json.dumps({"status": status, "body": body, "peak_mb": peak_mb()}, ensure_ascii=False, default=str).encode("utf-8"))
    real_out.flush()


if __name__ == "__main__":
    main()
