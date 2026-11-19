"""Work that survives a stop.

A long job (a two-hour recording) is done in pieces, and each finished piece is written here
before the next begins. If the job stops (the app is closed, the computer restarts, the model is
refused memory) the next run of the same source finds the pieces and carries on from there.

One folder per job under ~/.mitra/run/work, named by a fingerprint of the source file (path,
size, modified time) and the settings that change the result, so a recording that was edited or
is run at another speed never picks up the wrong pieces.
"""
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

from . import paths

ROOT = paths.HOME / "run" / "work"


class Paused(Exception):
    """The person asked for the job to stop after the piece in hand."""


def alive(pid: int) -> bool:
    if not pid:
        return False
    if sys.platform == "win32":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, int(pid))      # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259           # STILL_ACTIVE
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def recycle(path: Path) -> str:
    """Remove a file or folder the recoverable way: the Recycle Bin on Windows, and elsewhere a
    dated folder under ~/.mitra/removed. Returns where it went."""
    path = Path(path)
    if not path.exists():
        return ""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class OP(ctypes.Structure):
            _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                        ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL), ("hNameMappings", ctypes.c_void_p),
                        ("lpszProgressTitle", wintypes.LPCWSTR)]
        op = OP(None, 3, str(path.resolve()) + "\0\0", None, 0x0040 | 0x0010 | 0x0004 | 0x0400, False, None, None)  # delete, allow undo, silent
        if ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) == 0 and not path.exists():
            return "Recycle Bin"
    dest = paths.HOME / "removed" / f"{time.strftime('%Y-%m-%d-%H%M%S')}-{path.name}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(dest))
    return str(dest)


def fingerprint(src: Path, *settings) -> str:
    st = src.stat()
    return hashlib.sha1("|".join([str(src.resolve()), str(st.st_size), str(st.st_mtime_ns), *map(str, settings)]).encode()).hexdigest()[:16]


class Work:
    def __init__(self, src: Path, *settings, key: str | None = None):
        self.key = key or fingerprint(src, *settings)
        self.dir = ROOT / self.key
        self.resumed = (self.dir / "job.json").is_file()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.meta = self.load("job") or {"key": self.key, "source": str(src), "created": time.time(), "progress": {}}
        self.on_tick = None

    def load(self, name: str):
        try:
            return json.loads((self.dir / f"{name}.json").read_text("utf-8"))
        except (OSError, ValueError):
            return None

    def save(self, name: str, obj) -> None:
        tmp = self.dir / f"{name}.tmp"
        tmp.write_text(json.dumps(obj, ensure_ascii=False), "utf-8")
        paths.replace(tmp, self.dir / f"{name}.json")

    def note(self, **fields) -> None:
        self.meta.update({"pid": os.getpid(), "touched": time.time(), **fields})
        self.save("job", self.meta)

    def tick(self, stage: str, done: int, total: int) -> None:
        """`done` of `total` pieces of a stage are on disk."""
        self.meta.setdefault("progress", {})[stage] = [done, total]
        self.note()
        if self.on_tick:
            self.on_tick(stage, done, total)

    def check(self) -> None:
        if (self.dir / "pause").exists():
            raise Paused()

    def finish(self) -> None:
        """The memo is written: the pieces are no longer needed."""
        shutil.rmtree(self.dir, ignore_errors=True)


def unfinished() -> list[dict]:
    """Jobs with pieces on disk and nobody working on them."""
    out = []
    for f in sorted(ROOT.glob("*/job.json"), key=lambda f: f.stat().st_mtime, reverse=True):
        try:
            m = json.loads(f.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        if alive(m.get("pid")) and m.get("state") == "running":
            continue
        if not Path(m.get("source", "")).is_file():
            m["source_missing"] = True
        out.append(m)
    return out
