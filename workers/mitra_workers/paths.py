"""Locations and configuration. Source lives in ROOT; everything Mitra writes lives in HOME (~/.mitra)."""
import json
import os
from pathlib import Path

ROOT = Path(os.environ.get("MITRA_ROOT") or Path(__file__).resolve().parents[2])
HOME = Path(os.environ.get("MITRA_HOME") or Path.home() / ".mitra")
BUILTIN_APPS = ROOT / "apps"
USER_APPS = HOME / "apps"
GOVERNOR = os.environ.get("MITRA_GOVERNOR") or str(ROOT / "bin" / ("mitra-governor.exe" if os.name == "nt" else "mitra-governor"))
_cfg = None

# The governor stamps its log lines in local time using this offset; the gateway sets it, and
# this covers workers started any other way.
if "MITRA_TZ_OFFSET_MIN" not in os.environ:
    import time as _time
    os.environ["MITRA_TZ_OFFSET_MIN"] = str(int(_time.localtime().tm_gmtoff // 60))


def config() -> dict:
    """Defaults suit any 8 GB machine with no GPU; ~/.mitra/config.json overrides them per device."""
    global _cfg
    if _cfg is None:
        _cfg = {
            "port": 7421,
            "model_budget_mb": 1024,     # ceiling for any model; each model is further capped at its own measured need
            "reserve_mb": 800,          # free RAM that must remain after a model loads
            "threads": max(1, (os.cpu_count() or 4) // 2),
            "idle_exit_min": 30,        # the gateway exits after this long with no browser activity
            "assistant_ctx": 1536,      # context window in tokens; the cache for it is part of the model's RAM
            # 8-bit context cache: measured 881 -> 778 MB on Qwen3 0.6B with unchanged answers.
            # A 4-bit cache saved 57 MB more and produced garbage, so it is not used.
            # --cache-ram 0: the server's prompt cache otherwise grows with every distinct prompt
            # (APTM measured 6.25 GB after about 500 meeting sections); off, memory stays flat.
            "assistant_args": ["-fa", "on", "-ctk", "q8_0", "-ctv", "q8_0", "--cache-ram", "0", "--no-repack"],
            "models_dir": str(HOME / "models"),
            "finetuned_dir": str(HOME / "models" / "finetuned"),
            "llama_server": "",         # path override; otherwise found on PATH or inside Ollama
            "whisper_cli": "",          # otherwise found on PATH or in <root>/runtimes/whisper.cpp
            "ffmpeg": "",               # otherwise found on PATH
            "connectors": {},           # e.g. {"dropbox": "/sdcard/Dropbox"} where no Dropbox client exists
        }
        f = HOME / "config.json"
        if f.exists():
            try:
                _cfg.update(json.loads(f.read_text("utf-8")))
            except Exception:
                pass
    return _cfg


def dropbox_root() -> Path | None:
    override = config()["connectors"].get("dropbox")
    if override:
        return Path(override).expanduser()
    candidates = [Path.home() / ".dropbox" / "info.json"]
    for env in ("LOCALAPPDATA", "APPDATA"):
        if os.environ.get(env):
            candidates.append(Path(os.environ[env]) / "Dropbox" / "info.json")
    for info in candidates:
        if info.exists():
            try:
                data = json.loads(info.read_text("utf-8"))
                for kind in ("personal", "business"):
                    if kind in data and Path(data[kind]["path"]).exists():
                        return Path(data[kind]["path"])
            except Exception:
                pass
    p = Path.home() / "Dropbox"
    return p if p.exists() else None


def resolve_connector(conn: dict) -> Path | None:
    kind, sub = conn.get("type"), conn.get("path", "")
    if kind == "dropbox":
        root = dropbox_root()
        return (root / sub) if root else None
    if kind == "folder":
        return Path(os.path.expandvars(sub)).expanduser()
    return None


def replace(tmp: Path, dest: Path) -> None:
    """Put `tmp` in place of `dest`. On Windows this is refused while another process is reading
    `dest` (the launcher reads a job's file whenever the page polls), so try again for two seconds."""
    import time
    for attempt in range(40):
        try:
            tmp.replace(dest)
            return
        except PermissionError:
            if attempt == 39:
                raise
            time.sleep(0.05)
