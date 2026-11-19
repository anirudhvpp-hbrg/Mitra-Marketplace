"""App registry: an app is a folder with mitra.app.json, an optional ui/ and an optional worker.py.

worker.py exposes ROUTES = {("GET", "status"): fn, ("POST", "job/run"): fn}; each fn takes the
request and returns JSON-serialisable data. They are served under /api/apps/<id>/<name>.
"""
import importlib.util
import json
from pathlib import Path

from . import models, paths


class App:
    def __init__(self, folder: Path, builtin: bool):
        self.dir, self.builtin = folder, builtin
        self.manifest = json.loads((folder / "mitra.app.json").read_text("utf-8"))
        self.id = self.manifest["id"]

    def public(self) -> dict:
        m = dict(self.manifest)
        m["builtin"], m["dir"] = self.builtin, str(self.dir)
        m["needs"] = [models.pick(c) for c in self.manifest.get("needs", [])]
        conns = []
        for c in m.get("connectors", []):
            p = paths.resolve_connector(c)
            conns.append({**c, "resolved": str(p) if p else None, "available": bool(p and p.exists())})
        m["connectors"] = conns
        return m

    def routes(self) -> dict:
        f = self.dir / "worker.py"
        if not f.exists():
            return {}
        spec = importlib.util.spec_from_file_location(f"mitra_app_{self.id.replace('-', '_')}", f)
        mod = importlib.util.module_from_spec(spec)
        mod.APP = self
        spec.loader.exec_module(mod)
        return getattr(mod, "ROUTES", {})


def discover() -> dict[str, App]:
    apps = {}
    for root, builtin in ((paths.BUILTIN_APPS, True), (paths.USER_APPS, False)):
        if not root.exists():
            continue
        for d in sorted(root.iterdir()):
            if (d / "mitra.app.json").exists():
                try:
                    a = App(d, builtin)
                    apps[a.id] = a
                except Exception:
                    continue
    return apps
